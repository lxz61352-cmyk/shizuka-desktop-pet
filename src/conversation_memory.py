"""Bounded model context over an unbounded, portable conversation archive."""
import json
import re
import hashlib
from datetime import datetime,timezone

CHAT_KINDS={"chat","user","weixin"}
CONTINUATION_HINT='用户的短回复可能是在接您上一条主动消息（开场、图片评论、论文、提醒等），先按消息顺序理解指代，自然接话，不无故重新自我介绍。历史主动消息只是您当时说的话，不是新的观察或用户已确认的事实。'
SUMMARY_KIND="memory_summary"
RECENT_MESSAGE_LIMIT=100
RECENT_CHARACTER_BUDGET=48000


def eligible(rows):
    return [r for r in rows if r.get("role") in ("user","assistant")
            and r.get("kind","chat") in CHAT_KINDS and r.get("text","").strip()]


def recent_turns(rows, count=6):
    turns=[]
    pending={}
    for row in eligible(rows):
        channel="weixin" if row.get("kind")=="weixin" else "desktop"
        if row["role"]=="user":
            pending[channel]=row
        elif channel in pending:
            user=pending.pop(channel)
            turns.append({"user":user["text"],"assistant":row["text"],
                          "ids":(user.get("id"),row.get("id")),"created":row.get("created",0),
                          "times":{'user':user.get('created'),'assistant':row.get('created')}})
    return sorted(turns,key=lambda t:t["created"])[-count:] if count>0 else []


def recent_messages(rows, limit=RECENT_MESSAGE_LIMIT, budget=RECENT_CHARACTER_BUDGET, dated=False,current_user_id=None):
    """All real user/assistant dialogue, including assistant-led exchanges, in order.

    Proactive text is context only: eligible()/summary_batch() retain their existing
    user-grounded memory rules. Only the caller's current user message is excluded
    because it is appended once at the end of that request; source markers and
    memory summaries are not spoken messages.
    """
    if limit<=0:return []
    turns=recent_turns(rows,len(rows))
    completed={ident for turn in turns for ident in turn['ids']}
    partners={turn['ids'][1]:turn['ids'][0] for turn in turns}
    candidates=[];source=''
    for row in rows:
        if row.get('role')=='source':
            source=row.get('text','').removeprefix('内容来自');continue
        standalone=row.get('role')=='assistant' and row.get('kind')!=SUMMARY_KIND
        proactive=standalone and (row.get('kind') not in CHAT_KINDS or row.get('id') not in completed)
        spoken=row.get('role') in ('user','assistant') and row.get('kind')!=SUMMARY_KIND
        if spoken and (current_user_id is None or row.get('id')!=current_user_id):
            value=row.get('text','')
            if not value.strip():continue
            if len(value)>8000:value=value[:6000]+'\n[中段省略，完整原文仍在记录中]\n'+value[-1800:]
            if dated:
                when=row.get('created')
                label=datetime.fromtimestamp(when,timezone.utc).astimezone().isoformat(timespec='minutes') if when else '原时间未知'
                origin_source='微信' if row.get('kind','').startswith('weixin') else source
                origin=('；此前主动消息'+('，来源：'+origin_source if origin_source else '')) if proactive else ''
                value='[历史消息时间：'+label+'；相对日期以此为准'+origin+']\n'+value
            candidates.append((row,{'role':row['role'],'content':value}))
        if row.get('role')=='assistant':source=''
    selected=[];size=0
    for row,message in reversed(candidates):
        if len(selected)>=limit or selected and size+len(message['content'])>budget:break
        selected.insert(0,(row,message));size+=len(message['content'])
    # A budget boundary may keep an assistant answer but lose its paired user turn.
    ids={row.get('id') for row,_ in selected}
    return [message for row,message in selected if row.get('id') not in partners or partners[row['id']] in ids]


def tokens(text):
    text=text.lower()
    result=set(re.findall(r"[a-z0-9]{2,}",text))
    for phrase in re.findall(r"[\u4e00-\u9fff]+",text):
        result.update(phrase[i:i+2] for i in range(len(phrase)-1))
    return result


def recall(rows, query, recent_count=6, budget=10000):
    """Return dated excerpts as quoted data, never merge them into role instructions."""
    recent={ident for turn in recent_turns(rows,recent_count) for ident in turn["ids"]}
    query_tokens=tokens(query)
    candidates=[]
    for row in rows:
        if row.get("id") in recent:continue
        summary=row.get("kind")==SUMMARY_KIND
        if not summary and (row.get("kind","chat") not in CHAT_KINDS
                or row.get("role") not in ("user","assistant")):continue
        text=row.get("text","")
        overlap=len(query_tokens & tokens(text))
        if overlap or summary:
            candidates.append((overlap+(0.2 if summary else 0),row.get("created",0),row))
    result=[];size=0
    for _,_,row in sorted(candidates,key=lambda x:(x[0],x[1]),reverse=True)[:10]:
        excerpt={k:row.get(k) for k in ("created","role","kind","text")}
        if excerpt.get('created'):excerpt['记录时间']=datetime.fromtimestamp(excerpt['created'],timezone.utc).astimezone().isoformat(timespec='minutes')
        excerpt["text"]=str(excerpt["text"] or "")[:1800]
        serialized=json.dumps(excerpt,ensure_ascii=False)
        if size+len(serialized)>budget:break
        result.append(excerpt);size+=len(serialized)
    return result


def summary_batch(rows, size=12):
    processed=set()
    for row in rows:
        if row.get("kind")==SUMMARY_KIND:
            try:processed.update(json.loads(row.get("turn_id","[]")))
            except (TypeError,ValueError):pass
    complete={ident for turn in recent_turns(rows,len(rows)) for ident in turn["ids"]}
    pending=[r for r in eligible(rows) if r.get("id") and r["id"] in complete and r["id"] not in processed]
    if len(pending)<size:return []
    return pending[:size]


def summary_record(batch, text, now):
    ids=[r["id"] for r in batch]
    digest=hashlib.sha256(json.dumps(ids,separators=(",",":")).encode()).hexdigest()[:32]
    return {"id":"summary_"+digest,"created":now,"role":"assistant","kind":SUMMARY_KIND,
            "turn_id":json.dumps(ids,separators=(",",":")),"text":"对话自动摘要（可核对原文）："+text.strip()}
