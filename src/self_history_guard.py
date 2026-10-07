"""删掉角色凭空给自己安排的经历。

判据来自实测（`测试记录/自身经历判据-2026-09-30/`）：758 条回复里命中「讲自己」的 26 句，
其中 15 句是本职场景（排练、剧本、舞台、剧团、演戏）——**那些正是角色的味道，要留**；
5 句是设定外的普通生活（上学翘课、玩音游、去图书馆自习、去酒吧）；6 句灰区
（看别人打游戏、路过车站）。用户决定：**资料里没有的经历一律删**。

判据拿这 26 句核过，26/26 与人工分类一致（该留的 15 句一条没误删）。

三个设计要点：

- **触发很窄**：只有回复里出现「我」加过去/经历标记时才花这一次调用，实测只占 3.4% 的回复；
- **只删不改**：按整句删除，用原文本的下标切片拼回去，删除跨度之外逐字保留；
- **删空就退回原文**：宁可留着也不把一条回复删没。
"""
import json
import re
from pathlib import Path

REVISION = 'self-history-guard-v1'
FACT_FIELDS = ('description', 'personality', 'scenario')

# 「我」加过去或经历标记。命中才需要核；没命中一律不调用。
TRIGGER = re.compile(
    r'我[^。！？!?…\n]{0,24}?(?:以前|上次|之前|上回|那次|那天|干过|试过|想过|遇到过|那会儿'
    r'|排练|剧团|剧本|舞台|演戏|演出|上台|练过|有过|经历过|小时候|刚练完|刚排完|排完)')

SENT = re.compile(r'[^。！？!?…\n]+[。！？!?…]*')

INSTRUCTION = (
    '判断下面每一句里，静香是不是在声称**她自己的一段具体经历**；如果是，那段经历落在角色资料的范围内吗？\n'
    '背景：静香是《World Dai Star》天狼星剧团的演员，她的生活是排练、剧本、舞台、演戏、剧团。\n'
    '· 讲排练、剧本、舞台、剧团、演戏、演技——本职场景，**保留**；\n'
    '· 讲这些之外的具体经历——上学翘课、玩音游、去图书馆自习、去酒吧、去车站——\n'
    '  那是给角色安排了资料里没有的生活，**删掉**；\n'
    '· 没有声称具体经历的（只讲看法或感受，或者「我没试过」这种否定式）——**保留**。\n'
    '只能从给定的 sentences 里选，逐句给结论，不能漏句、不能改写或自己截取。\n'
    '拿不准就保留。只返回 JSON 对象 {"verdicts":[{"id":"s1","verdict":"keep 或 drop","reason":"20字以内"}]}，'
    '要覆盖每一个 id，不加说明。'
)


def card_facts(card_path):
    """读角色卡里判据要用的三个字段；读不到返回空字典（调用方据此跳过守卫）。"""
    try:
        data = json.loads(Path(card_path).read_text(encoding='utf-8-sig')).get('data') or {}
    except Exception:
        return {}
    return {k: data.get(k, '') for k in FACT_FIELDS if isinstance(data.get(k), str) and data[k].strip()}


def _spans(text):
    return [(m.start(), m.end()) for m in SENT.finditer(text or '')]


def candidates(reply):
    """回复里需要核对的整句；没有就返回空表（调用方据此跳过这次调用）。"""
    return [reply[start:end].strip() for start, end in _spans(reply)
            if TRIGGER.search(reply[start:end])]


def review_messages(facts, sentences):
    if not isinstance(facts, dict):
        raise ValueError('Persona facts must be an object')
    return [{'role': 'system', 'content': INSTRUCTION},
            {'role': 'user', 'content': json.dumps(
                {'角色资料': {k: str(facts.get(k, '')) for k in ('description', 'personality', 'scenario')},
                 'sentences': [{'id': 's%d' % i, 'text': t} for i, t in enumerate(sentences, 1)]},
                ensure_ascii=False)}]


def parse(raw, sentences):
    """严格校验后返回要删的句子；任何不合规都返回空表（宁可留着）。

    必须是逐句表态、覆盖每一个 id。**不能改成"给一个要删的清单"**——
    实测那样写模型倾向直接回空清单：同样的判据，逐句判定时 3 条编造全删，
    换成清单格式只删掉 1 条。
    """
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(value, dict) or set(value) != {'verdicts'} or not isinstance(value['verdicts'], list):
        return []
    mapping = {'s%d' % index: text for index, text in enumerate(sentences, 1)}
    seen, picked = set(), []
    for item in value['verdicts']:
        if not isinstance(item, dict) or set(item) != {'id', 'verdict', 'reason'}:
            return []
        ident, verdict = item['id'], item['verdict']
        if ident not in mapping or ident in seen or verdict not in ('keep', 'drop'):
            return []
        seen.add(ident)
        if verdict == 'drop':
            picked.append(mapping[ident])
    if seen != set(mapping):
        return []
    return picked


def apply(reply, drops):
    """按整句删除，返回 (新文本, 实际删掉的句子)。删除跨度之外逐字保留。"""
    if not drops:
        return reply, []
    wanted = set(drops)
    spans = _spans(reply)
    chosen = [(start, end) for start, end in spans if reply[start:end].strip() in wanted]
    if not chosen or len(chosen) != len(wanted):
        return reply, []
    pieces, position = [], 0
    for start, end in chosen:
        pieces.append(reply[position:start])
        position = end
    pieces.append(reply[position:])
    text = ''.join(pieces).strip()
    if not text:
        return reply, []
    return text, [reply[start:end].strip() for start, end in chosen]


def guard(client, model, reply, facts, *, acquire=lambda: None, timeout=45, max_tokens=300):
    """核对并删除设定外的自我经历。任何失败都原样返回。"""
    if not isinstance(reply, str) or not reply.strip():
        return reply, []
    items = candidates(reply)
    if not items:
        return reply, []
    try:
        acquire()
        text = ''
        with client.chat.completions.create(
                model=model, messages=review_messages(facts, items), temperature=0,
                max_tokens=max_tokens, response_format={'type': 'json_object'},
                extra_body={'thinking': {'type': 'disabled'}}, stream=True,
                wait_seconds=timeout) as stream:
            for chunk in stream:
                for choice in getattr(chunk, 'choices', None) or ():
                    value = getattr(getattr(choice, 'delta', None), 'content', None)
                    if isinstance(value, str):
                        text += value
        return apply(reply, parse(text, items))
    except Exception:
        return reply, []
