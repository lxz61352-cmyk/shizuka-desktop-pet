"""Conservative local acceptance and provenance de-duplication for review.

These checks are a backstop, not a claim to understand arbitrary entailment.
The archive remains intact when a long-term candidate is rejected.
"""
import re
from collections import Counter

def normalized(text):
    return re.sub(r'[\W_]+','',text or '').lower()

def claim_issue(fact,quote):
    if re.match(r'用户(?:未告知|没告诉|没有告诉|未透露)',fact):return 'conversation_meta'
    if '否认' in fact and re.search(r'没告诉|没说过|没提过|猜的',quote) and not re.search(r'我(?:不是|没有|没在|不住|不在|并不|从未|没养|不会|不喜欢)',quote):
        return 'denial_inferred'
    # Relative countdowns decay even when a model incorrectly labels them stable.
    if re.search(r'(?:还有|还剩|距.{0,12}约?|再过)\s*[0-9一二三四五六七八九十百]+\s*(?:天|小时|分钟)',fact):
        return 'relative_countdown'
    groups=(('最近','近期','这段时间'),('可能','也许','或许'),('如果','假如','要是','若'),
            ('暂时','目前','现在','现阶段','正在'),('这次','这一回'))
    for group in groups:
        if any(w in quote for w in group) and not any(w in fact for w in group):
            return 'qualifier_lost'
    if re.search(r'用户(?:自己)?(?:养狗|养了一?只狗|有一?只狗|的狗)',fact) and not re.search(r'我(?:家|自己)?(?:养|的狗)|我家.{0,5}狗',quote):
        return 'ownership_inferred'
    if re.match(r'用户(?:知道|了解|熟悉).{0,80}(?:是|指|叫|梗|玩家|选手)',fact):
        return 'encyclopedic_not_profile'
    return None

def duplicate_fact(fact,items):
    content=normalized(fact['content']);quote=normalized(fact['quote'])
    for row in items:
        if normalized(row.get('content'))==content:return True
        old_quote=normalized(row.get('source_quote') or (row.get('source') or {}).get('quote'))
        # Different messages may repeat the same story verbatim. Do not refresh
        # its source date or resurrect a manually archived fact.
        if old_quote and old_quote==quote:return True
    return False

def reviewed_ids(previous,batch):
    # An evicting "last N" cache is not a processing ledger.
    return list(dict.fromkeys([*previous,*(r['id'] for r in batch)]))

def known_for_batch(items,batch,limit=200):
    """All normal-sized stores; source-related and lexical matches first if huge."""
    from conversation_memory import tokens
    query=tokens(' '.join(r['text'] for r in batch if r.get('role')=='user'))
    sources={r['id'] for r in batch}
    ordered=sorted(items,key=lambda r:(r.get('source_id') in sources,
                    len(query & tokens(r.get('content',''))),r.get('created',0)),reverse=True)
    return [{'id':r['id'],'content':r['content'][:160],'status':r.get('status','active')}
            for r in ordered[:limit]]

def accepted_facts(facts,items,known_ids=()):
    result=[];counts=Counter();seen=list(items);allowed=set(known_ids)
    for f in facts:
        if duplicate_fact(f,seen) or counts[f['source_id']]>=3:continue
        f=dict(f,replaces=[i for i in f['replaces'] if i in allowed])
        result.append(f);counts[f['source_id']]+=1
        seen.append(dict(content=f['content'],source_quote=f['quote']))
        if len(result)>=4:break
    return result
