"""Isolated v2 request adapter; v1 deletion validation remains unchanged.

Only offer units that v1 can delete individually. This is structural filtering,
not a judgement that a unit lacks evidence, and does not guarantee a batch of
individually valid deletions will be safe. The caller must still use ``apply``
and keep the original draft on failure.

Like v1, this experiment has no attachment, memory or tool evidence. It cannot
be used in production without the same complete sources used for generation.
No model calls, state changes, delivery or production hooks live here.
"""
import json

if __package__:
    from . import reply_evidence_prune as _v1
else:
    import reply_evidence_prune as _v1


REVISION = 'reply-evidence-prune-v2'
REASONS = _v1.REASONS
apply = _v1.apply
SYSTEM = _v1.SYSTEM + '''
deletion_units已排除单独删除就会被程序拒绝的单元，但列出不表示它没有事实依据，也不保证多个单元一起删除安全。
同一处明确无依据内容若既可由一个完整句删去，也被包含在更大的段落里，选择能完整去掉该内容的最小完整单元，保留相邻且独立的情绪反应。仍须保留有依据的内容和必要答案；不能为缩短回复而删，也不能自行截取未列出的片段。'''


def review_messages(persona_facts, history, user, draft):
    """Use v1 sources and boundaries; filter choices via its actual validator."""
    messages = _v1.review_messages(persona_facts, history, user, draft)
    payload = json.loads(messages[1]['content'])
    usable = []
    for unit in payload['deletion_units']:
        # The reason is only a valid protocol placeholder for structural checks;
        # evidence and the actual reason remain the reviewer's responsibility.
        single = {'deletions': [{'quote': unit['text'], 'reason': REASONS[0]}]}
        try:
            apply(json.dumps(single, ensure_ascii=False), draft)
        except ValueError:
            continue
        usable.append(unit)
    payload['deletion_units'] = usable
    messages[0]['content'] = SYSTEM
    messages[1]['content'] = json.dumps(payload, ensure_ascii=False)
    return messages
