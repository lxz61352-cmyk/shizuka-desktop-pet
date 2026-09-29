"""Read-only selection over the full archive; shared by desktop and WeChat.

No data deletion, model calls, rewritten assistant examples or hidden classifier.
"""
import json
import re
import conversation_memory as cm

REVISION = 'current-context-v1'
SESSION_GAP = 45 * 60
MESSAGE_LIMIT = 48
CHARACTER_BUDGET = 18000
_COMMON = set(cm.tokens('用户说的这个那个什么怎么可以不能没有已经还是现在今天一下一些一个事情问题感觉知道可能因为所以我们你们他们还有就是这样时候方面需要进行'))
_BACKREF = re.compile(r'刚才|上次|之前|昨天|接着|继续|你发的|你说的|那篇|那道|还记得')
_FEEDBACK = re.compile(r'(?:别|不要|不用|不想|希望|喜欢).{0,20}(?:催|督促|说教|分析我|分析我的|说话|回复|称呼|语气)|(?:说话|回复|称呼|语气).{0,16}(?:别|不要|不用|希望|喜欢)|别老拿.{0,20}套我')


def terms(text):
    text=re.sub(r'用户|我在哪个|我在哪|哪个|还记得|你知道|请问', '', text)
    return cm.tokens(text) - _COMMON


def relevance(query, content):
    """Conservative lexical eligibility, not a semantic-confidence claim."""
    q, d = terms(query), terms(content)
    hit = q & d
    if not q or not hit:
        return 0.0
    # A complete two-character subject is useful; one accidental bigram in a
    # long sentence is not (and Chinese fragments alone are not topic labels).
    compact = re.sub(r'\W', '', query)
    short_exact = (2 <= len(compact) <= 8 and compact in content) or len(q)==1
    if not short_exact and (len(hit) < 2 or len(hit)/len(q) < .25):
        return 0.0
    return len(hit)/len(q) + len(hit)/max(1,len(d))


def channel_of(row):
    return 'weixin' if row.get('kind','').startswith('weixin') else 'desktop'


def select_rows(rows, query='', channel='desktop', current_id=None):
    """Current same-channel episode; explicit references can bridge a time gap.

    Only the immediate desktop proactive message may seed a response. Unrelated
    reports never join an existing conversation just because their times match.
    """
    anchor = next((i for i,r in enumerate(rows) if current_id is not None and r.get('id')==current_id), len(rows)-1)
    rows = rows[:anchor+1]
    spoken = [r for r in rows if r.get('role') in ('user','assistant')
              and r.get('kind','chat') in cm.CHAT_KINDS and channel_of(r)==channel]
    if not spoken:
        return []
    users = [r for r in spoken if r['role']=='user']
    if not users:
        return []
    start = users[0]
    for previous, current in zip(users, users[1:]):
        a,b = previous.get('created'),current.get('created')
        if a and b and b-a > SESSION_GAP:
            start=current
    start_index=spoken.index(start)
    if start.get('id')==current_id and _BACKREF.search(query):
        start_index=max(0,start_index-6)
        while start_index and spoken[start_index].get('role')!='user':
            start_index-=1
    selected=spoken[start_index:]
    if channel=='weixin':
        first_index=next((i for i,r in enumerate(rows) if r is start),0)
        previous=next((r for r in reversed(rows[:first_index]) if channel_of(r)=='weixin' and r.get('role') in ('user','assistant')),None)
        if previous and previous.get('kind')=='weixin_proactive':selected=[previous]+selected
        # Include later proactive messages inside this same episode in their original order.
        ids={r.get('id') for r in selected}
        selected=[r for r in rows if r.get('id') in ids or (r.get('kind')=='weixin_proactive' and r.get('created',0)>=start.get('created',0))]
    # Preserve a genuinely referred-to assistant-led exchange, not a report feed.
    if channel=='desktop':
        first_index=next((i for i,r in enumerate(rows) if r is start),0)
        previous=next((r for r in reversed(rows[:first_index]) if r.get('role') in ('user','assistant')),None)
        if previous and previous.get('kind') not in cm.CHAT_KINDS and previous.get('kind')!=cm.SUMMARY_KIND:
            delta=(start.get('created') or 0)-(previous.get('created') or 0)
            if 0<=delta<=600 and (_BACKREF.search(start.get('text','')) or relevance(start.get('text',''),previous.get('text',''))):
                selected=[previous]+selected
    return selected


def feedback_context(rows, included_ids=()):
    """Exact user feedback, ordered oldest→newest so corrections can supersede.

    No assistant responses and no inferred personality facts are carried over.
    """
    selected=[];seen=set();included=set(included_ids)
    for row in reversed(cm.eligible(rows)):
        text=row['text'].strip()
        if row['role']!='user' or row.get('id') in included or text in seen:
            continue
        if len(text)<=240 and _FEEDBACK.search(text):
            selected.append({'原话':text,'记录时间':row.get('created')})
            seen.add(text)
            if len(selected)>=4:break
    if not selected:return ''
    return ('【用户此前明确的交流偏好】按时间排列；只用于理解其交流要求，后来的更正优先，不要复述或主动追问。\n'
            +json.dumps(list(reversed(selected)),ensure_ascii=False,separators=(',',':')))


def memory_block(items, excerpts):
    if not items and not excerpts:return ''
    from memory_contract import CONTEXT_INSTRUCTION
    facts=[{k:r[k] for k in ('id','content','source_time','created') if k in r} for r in items]
    return CONTEXT_INSTRUCTION+'\n'+json.dumps({'相关用户记忆':facts,'相关历史原话':excerpts},ensure_ascii=False,separators=(',',':'))
