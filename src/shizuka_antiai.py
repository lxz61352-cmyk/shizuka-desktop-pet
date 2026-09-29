"""反 AI 检查层（确定性规则）：只删除不自然的东西，不负责添加「角色味」。

高优先级：复述用户 / 结构化总结腔 / 无请求建议 / AI 元话语 / 过度完整。
返回 (清理后文本, 删除记录)；结果为空时保留原文（宁可少删，不空回复）。
"""
import re
import time

ADVICE_KINDS = ("task", "ask_help", "question")
ADVICE_RE = re.compile(r"不如|建议|记得|别忘了|最好|应该先|先别|要不|试试看|可以试试|试着|"
                       r"适当|早点休息|早点睡|注意休息|多喝水|多休息|带把伞")
SUMMARIZE_LEAD_RE = re.compile(r"^\s*(?:首先|其次|再次|另外|最后|总之|总的来说|综上所述|让我来(?:总结|概括))")
META_RE = re.compile(r"作为(?:一个)?AI|作为AI助手|按照(?:角色)?设定|角色规则|系统设定|我的设定|根据设定")
PARAPHRASE_LEAD_RE = re.compile(r"^\s*(?:听起来|感觉你|看来你|看上去你)(?:好像|确实|真的)?")
SENT_SPLIT_RE = re.compile(r"[^。！？!?…]+[。！？!?…]*")
POLAR_QUESTION_RE = re.compile(r'吗[？?]?\s*$|是不是|是否|有没有|能不能|可不可以')


def _bigrams(text):
    text = re.sub(r"\s+", "", text or "")
    if len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _overlap(a, b):
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


def _longest_common(a, b):
    a, b = re.sub(r"\s+", "", a or ""), re.sub(r"\s+", "", b or "")
    if not a or not b:
        return ""
    best = ""
    for i in range(len(a)):
        for j in range(len(b)):
            length = 0
            while i + length < len(a) and j + length < len(b) and a[i + length] == b[j + length]:
                length += 1
            if length > len(best):
                best = a[i:i + length]
    return best


def anti_ai_clean(reply, user_text, situation, log=None):
    if not reply or not reply.strip():
        return reply, []
    kind = (situation or {}).get("kind") or "general"
    sentences = [part.strip() for part in SENT_SPLIT_RE.findall(reply) if part.strip()]
    if not sentences:
        return reply, []
    removals = []
    kept = []
    for index, sentence in enumerate(sentences):
        drop = None
        direct_short_answer = bool(len(sentence) <= 12 and POLAR_QUESTION_RE.search(user_text or ""))
        if (index == 0 and user_text and not direct_short_answer and 5 <= len(sentence) <= 30
                and (len(_longest_common(sentence, user_text)) >= 5
                     or _overlap(sentence, user_text) >= 0.55
                     or PARAPHRASE_LEAD_RE.match(sentence))):
            drop = "restate"
        if SUMMARIZE_LEAD_RE.match(sentence) or META_RE.search(sentence):
            drop = "meta"
        if kind not in ADVICE_KINDS and ADVICE_RE.search(sentence) and len(sentence) <= 24:
            drop = "advice"
        if drop:
            removals.append((drop, sentence))
            continue
        kept.append(sentence)
    if kind not in ADVICE_KINDS and len(kept) >= 4:
        removals.append(("overlong", kept[-1]))
        kept = kept[:-1]
    if not removals:
        # Nothing judged removable: keep the original string, including any
        # leading pause the sentence splitter would otherwise drop.
        return reply, []
    text = "".join(kept)
    if not text.strip():
        return reply, removals
    if removals and log:
        try:
            with open(log, "a", encoding="utf-8") as handle:
                for drop, sentence in removals:
                    handle.write("%s [anti_ai:%s] user=%r drop=%r\n"
                                 % (time.strftime("%H:%M:%S"), drop, (user_text or "")[:40], sentence[:60]))
        except Exception:
            pass
    return text, removals
