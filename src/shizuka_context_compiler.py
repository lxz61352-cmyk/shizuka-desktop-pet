"""Context Compiler：按 Response Authority 组稀疏上下文。

权限由 authority 决定（允许给什么），本模块决定具体注入什么内容。
核心原则：「存在的数据」不等于「这一轮都要注入」。

P2c-8：角色 grounding（reaction anchor）与 continuation 完全分开——
锚点只提供「她会从什么角度看」，不提供「要不要继续」。
"""
import re

from shizuka_inject import relationship_line, state_lines

TOPIC_SHIFT_NOTE = "他刚把话题换到了新事情上。上一件事不必再提，除非他自己说回来——她只接新话题。"
ANCHOR_RULE = "仅作角色反应参考，不要求复述。"
REPAIR_RE = re.compile(r'不舒服|说重了|别解释.{0,10}(?:怎么想|想法)')
VAGUE_DISCOMFORT_RE = re.compile(r'(?:刚才|刚刚)?.{0,8}(?:让我|听着|感觉).{0,6}不舒服')
PLAYFUL_META_RE = re.compile(r'暧昧|开玩笑|别突然上课')


def minimal_character_note(text, signals, situation, authority):
    """One short bridge for task paths and otherwise-empty closed turns.

    It keeps voice continuity without copying the full casual relationship/state
    layer into factual answers. It never supplies facts or invented history.
    """
    signals = signals or {}
    situation = situation or {}
    authority = authority or {}
    speech = signals.get("speech_type")
    if speech in ("boundary", "phatic"):
        return ""
    if REPAIR_RE.search(text or ""):
        if VAGUE_DISCOMFORT_RE.search(text or ""):
            return ("【本轮人物姿态】他只说刚才有些不舒服。直接问是哪句或哪个部分就够了；"
                    "不要解释你能不能看到前文，不要先道歉、辩解、发表整改声明，"
                    "也不要分析自己的沟通模式。")
        return ("【本轮人物姿态】这是已经说出具体要求的关系反馈，不是让你复盘沟通策略。"
                "直接按他这句话回应并在当前说法里体现改变；不要再让他举例，不要改问泛泛的近况或想聊什么，"
                "不要把这一次反应概括成固定人格。")
    if PLAYFUL_META_RE.search(text or ""):
        return ("【本轮人物姿态】这是轻松玩笑，不是边界争论。可以否认、嘴硬或反逗一句，但先接住玩笑；"
                "不要上课、责怪用户怎么理解，也不要编造自己先前说过的具体内容。")
    if signals.get("explicit_help") or speech == "question":
        return ("【本轮人物姿态】先准确、完整地回答正题，必要条件与来源不能省。"
                "仍用静香直接、具体、有判断的口吻，不切成客服腔；本轮昵称、称呼或玩笑要在开头轻接一句，但不抢正题，"
                "不靠训斥、猜动机或追加追问制造角色感。")
    if authority.get("continuation") in ("near_zero", "very_low"):
        return ("【本轮人物姿态】只回应这句话本身，短而自然；保留她自己的反应，"
                "不靠冷淡、训斥、猜动机或追问制造角色感。")
    return ""


def compile_character_context(text, signals, situation, authority, char_state, relationship,
                              anchor_fn=None):
    """返回 (rel_line, state_text, anchor_text)；任务/问题/底线/空信息返回空。"""
    if signals.get("explicit_help") or signals.get("speech_type") in ("question", "boundary", "phatic"):
        return None, "", ""
    cont = (authority or {}).get("continuation", "very_low")
    if cont in ("near_zero", "very_low"):
        rel_line, states = None, []
    else:
        rel_line = relationship_line(relationship)
        states = state_lines(char_state)
    state_text = "【状态】" + "；".join(states) + "。" if states else ""
    if signals.get("topic_shift"):
        state_text = (state_text + TOPIC_SHIFT_NOTE) if state_text else ("【状态】" + TOPIC_SHIFT_NOTE)
    anchor_text = ""
    if anchor_fn:
        anchor = anchor_fn(text, situation.get("topic") or "")
        if anchor:
            anchor_text = "【Character reference】\n原作中类似场景的反应：\n「%s」\n%s" % (anchor, ANCHOR_RULE)
    return rel_line, state_text, anchor_text
