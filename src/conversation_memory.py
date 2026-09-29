"""Bounded model context over an unbounded, portable conversation archive."""
import json
import re
import hashlib
from datetime import datetime,timezone

CHAT_KINDS={"chat","user","weixin"}
CONTINUATION_HINT='用户的短回复可能是在接您上一条主动消息（开场、图片评论、论文、提醒等），先按消息顺序理解指代，不无故重新自我介绍。历史主动消息只是您当时说的话，不是新的观察或用户已确认的事实。'
SUMMARY_KIND="memory_summary"
RECENT_MESSAGE_LIMIT=100
RECENT_CHARACTER_BUDGET=48000
MIN_RECALL_OVERLAP=2   # 至少两个词重合才算相关：一个词的巧合太多


def eligible(rows):
    return [r for r in rows if r.get("role") in ("user","assistant")
            and r.get("kind","chat") in CHAT_KINDS and r.get("text","").strip()]


def recent_turns(rows, count=6):
    turns=[]
    pending={}
    grouped={}
    for row in eligible(rows):
        channel="weixin" if row.get("kind")=="weixin" else "desktop"
        group_id = row.get('turn_id', '')
        group_id = group_id if isinstance(group_id, str) and group_id.startswith('wxreply:') else None
        if row["role"]=="user":
            pending[channel]=row
            grouped.pop(channel, None)
        elif channel in pending:
            user=pending.pop(channel)
            turns.append({"user":user["text"],"assistant":row["text"],
                          "ids":(user.get("id"),row.get("id")),"created":row.get("created",0),
                          "times":{'user':user.get('created'),'assistant':row.get('created')}})
            if group_id:
                grouped[channel]=(group_id, turns[-1])
        elif group_id and channel in grouped:
            group, turn = grouped[channel]
            if group_id == group:
                turn['assistant'] += '\n\n' + row['text']
                turn['ids'] += (row.get('id'),)
                turn['created'] = row.get('created', 0)
                turn['times']['assistant'] = row.get('created')
    return sorted(turns,key=lambda t:t["created"])[-count:] if count>0 else []


def recent_messages(rows, limit=RECENT_MESSAGE_LIMIT, budget=RECENT_CHARACTER_BUDGET, dated=False,current_user_id=None,time_precision='minutes'):
    """All real user/assistant dialogue, including assistant-led exchanges, in order.

    Proactive text is context only: eligible()/summary_batch() retain their existing
    user-grounded memory rules. Only the caller's current user message is excluded
    because it is appended once at the end of that request; source markers and
    memory summaries are not spoken messages.
    """
    if limit<=0:return []
    turns=recent_turns(rows,len(rows))
    completed={ident for turn in turns for ident in turn['ids']}
    partners={ident:turn['ids'][0] for turn in turns for ident in turn['ids'][1:]}
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
                label=datetime.fromtimestamp(when,timezone.utc).astimezone().isoformat(timespec=time_precision) if when else '原时间未知'
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


# 历史时间戳包装只在 recent_messages(dated=True) 生成；送进模型前由下面两个共享函数净化，
# 时间信息移入 system 的元数据块。桌面、微信与 release smoke 必须共用，不要各写一份。
DATED_PREFIX_RE = re.compile(
    r'^\[历史消息时间：'
    r'(?P<time>原时间未知|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)'
    r'；相对日期以此为准(?P<origin>；此前主动消息(?:，来源：[^\]]{0,40})?)?\]\n?')


def sanitize_dated_history(messages):
    """剥离历史时间戳包装，返回 (clean_messages, time_lines, notes)。

    - 严格匹配：包装剥掉，时间与“此前主动消息/来源”保留进 time_lines；
    - 行首像包装但严格解析失败：直接移除首行（缺右括号/超长/坏格式均不再依赖右括号），
      无换行则丢弃整条消息；异常包装不得继续进入模型输入，notes 记录；
    - 剥离后正文为空：丢弃该条消息，notes 记录；
    - time_lines 只登记最终保留的消息，dialogue_index 按最终列表重新编号；
    - 行中提及“历史消息时间”或其它方括号文本不受影响。
    """
    clean = []
    time_lines = []
    notes = []
    for message in messages or []:
        content = message.get('content', '') if isinstance(message, dict) else ''
        if not isinstance(content, str) or not content.startswith('[历史消息时间'):
            clean.append(message)
            continue
        match = DATED_PREFIX_RE.match(content)
        if match:
            time_line = {'role': message.get('role'), 'time': match.group('time'),
                         'origin': match.group('origin') or ''}
            value = content[match.end():]
        else:
            time_line = None
            notes.append({'role': message.get('role'), 'reason': 'malformed_prefix'})
            value = content.split('\n', 1)[1] if '\n' in content else ''
        if not value.strip():
            notes.append({'role': message.get('role'), 'reason': 'empty_after_strip'})
            continue
        if time_line is not None:
            time_line['dialogue_index'] = len(clean)
            time_lines.append(time_line)
        clean.append({**message, 'content': value})
    return clean, time_lines, notes


def render_time_metadata(time_lines):
    """单一共享渲染：桌面、微信与 release smoke 共用此块文本；无时间行时返回空串。"""
    if not time_lines:
        return ''
    lines = ['【本轮时间元数据】以下仅为内部参考，禁止在输出或回复中复述其格式：']
    for entry in time_lines:
        line = 'dialogue_index=%s role=%s time=%s' % (
            entry.get('dialogue_index'), entry.get('role'), entry.get('time'))
        origin = (entry.get('origin') or '').lstrip('；')
        if origin:
            line += ' note=%s' % origin
        lines.append(line)
    return '\n'.join(lines)


def tokens(text):
    text=text.lower()
    result=set(re.findall(r"[a-z0-9]{2,}",text))
    for phrase in re.findall(r"[\u4e00-\u9fff]+",text):
        result.update(phrase[i:i+2] for i in range(len(phrase)-1))
    return result


def recall(rows, query, recent_count=6, budget=2400, exclude_ids=()):
    """Return dated excerpts as quoted data, never merge them into role instructions.

    只召回**用户说过的话**和自动摘要：助手自己的旧回复既不算资料，也容易被模型原样照抄
    （之前出过一次：输入里只有「压力」一个词重合，就把一条无关旧回复整段背了出来）。"""
    from dialogue_context import relevance
    recent={ident for turn in recent_turns(rows,recent_count) for ident in turn["ids"]} | set(exclude_ids)
    # 本轮这句刚落库、还没配回复：它是最后一条用户消息，别当历史资料召回
    current=(query or "").strip()
    last_user=next((row for row in reversed(rows)
                    if row.get("role")=="user" and row.get("kind","chat") in CHAT_KINDS),None)
    current_id=last_user.get("id") if last_user and (last_user.get("text") or "").strip()==current else None
    candidates=[]
    sources={r.get('id'):r for r in rows if r.get('role')=='user'}
    for row in rows:
        if row.get("id") in recent or row.get("id")==current_id:continue
        summary=row.get("kind")==SUMMARY_KIND
        if not summary and (row.get("role")!="user" or row.get("kind","chat") not in CHAT_KINDS):
            continue
        if summary:
            # Old free-form summaries remain in the archive. Their inferred
            # "unresolved problems" must not become ongoing user requests.
            if row.get('context_revision') != 2:continue
            notes=row.get('source_quotes',[])
            for note in notes if isinstance(notes,list) else []:
                if not isinstance(note,dict):continue
                source=sources.get(note.get('source_id'))
                quote=note.get('quote','')
                if not source or source.get('id') in recent or source.get('id')==current_id:continue
                if not isinstance(quote,str) or not quote or quote not in source.get('text',''):continue
                score=relevance(query,quote)
                if score:candidates.append((score,source.get('created',0),{**source,'text':quote}))
            continue
        text=row.get("text","")
        score=relevance(query,text)
        if score:
            candidates.append((score,row.get("created",0),row))
    result=[];size=0
    seen=set()
    for _,_,row in sorted(candidates,key=lambda x:(x[0],x[1]),reverse=True):
        if row.get('id') in seen:continue
        excerpt={k:row.get(k) for k in ("id","created","role","kind","text")}
        if excerpt.get('created'):excerpt['记录时间']=datetime.fromtimestamp(excerpt['created'],timezone.utc).astimezone().isoformat(timespec='minutes')
        excerpt["text"]=str(excerpt["text"] or "")[:1800]
        serialized=json.dumps(excerpt,ensure_ascii=False)
        if size+len(serialized)>budget:continue
        result.append(excerpt);size+=len(serialized);seen.add(row.get('id'))
        if len(result)>=3:break
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


def grounded_summary_record(batch, payload, now):
    """A summary indexes verbatim user quotes; never invents open obligations."""
    sources={row.get('id'):row for row in batch if row.get('role')=='user'}
    notes=[];seen=set()
    for item in (payload.get('notes',[]) if isinstance(payload,dict) else [])[:8]:
        if not isinstance(item,dict):continue
        source=sources.get(item.get('source_id'));quote=item.get('quote')
        if not source or not isinstance(quote,str) or not 2<=len(quote)<=500:continue
        if quote not in source.get('text','') or (source['id'],quote) in seen:continue
        seen.add((source['id'],quote));notes.append({'source_id':source['id'],'quote':quote})
    record=summary_record(batch,'\n'.join('- '+item['quote'] for item in notes) or '本批没有需要保留的连续性片段。',now)
    record.update(context_revision=2,source_quotes=notes)
    return record
