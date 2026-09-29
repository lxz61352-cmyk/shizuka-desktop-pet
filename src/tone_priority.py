"""Tone priority v1 (candidate, default off).

Pure posture detection for the dialogue path: when the caller enables
``tone_priority_v1`` the planner marks care/repair turns so the final request
keeps warmth priorities over night/fatigue/impulse randomness.  With the switch
off nothing here runs and the baseline request is unchanged.
"""
import re

SWITCH_KEY = "tone_priority_v1"
SWITCH_KEY_V2 = "tone_priority_v2"

HISTORY_NOTE = ("历史回复只表示当时说过什么，不决定本轮态度；"
                "本轮语气服从当前情境、策略和角色示例。")

CARE_LINE = ("先接住他这轮表达的情绪；可以短；不训斥、不逼他解决问题，也不给建议清单。")

REPAIR_LINE = ("先接住他在说你的语气让他不舒服，停止调侃和顶嘴，不要先否认；"
               "当前可见历史里有对应回复就直接回应，没有时才问具体是哪句。")

CARE_POST_HISTORY = (
    "用户本轮是在表达难受或撑不住。这里只接住眼前感受，暂不纠正、分析、安排任务或催他行动；"
    "可以很短，也可以自然问一句，但不要把情绪立刻转成学习、明天或下一步计划。")

REPAIR_POST_HISTORY_WITH_HISTORY = (
    "用户在反馈你刚才的语气太凶。可见历史里已有对应回复；先承认刚才措辞太冲，"
    "再用更平和的方式重说原意。不要反问哪句、不要否认、不要解释“本意是为你好”，"
    "也不要把责任推回用户。")

REPAIR_POST_HISTORY_NO_HISTORY = (
    "用户在反馈你的语气太凶，但当前看不到对应回复。可以简短问具体是哪句；"
    "不要先否认或反推责任。")


def resolve_switch(v1_enabled, v2_enabled):
    """Return 0/1/2 for the active tone mode; both on is a hard conflict."""
    if v1_enabled and v2_enabled:
        raise ValueError("tone_priority_v1 and tone_priority_v2 cannot both be enabled")
    if v2_enabled:
        return 2
    if v1_enabled:
        return 1
    return 0


def post_history_block(posture, has_assistant):
    """The single per-turn stance system block for tone_priority_v2."""
    if posture == "care":
        return CARE_POST_HISTORY
    if posture == "repair":
        return (REPAIR_POST_HISTORY_WITH_HISTORY if has_assistant
                else REPAIR_POST_HISTORY_NO_HISTORY)
    return None

HIGH_PRECISION = re.compile(
    r"好难过|难过|想哭|心里难受|过意不去|委屈|撑不住|顶不住|崩溃|压力大|压力好大|郁闷")

TIRED_WORDS = re.compile(r"好累|累死|心累|劳累|熬不住|状态很差|状态不太好")

RESOLVED_OUTCOME = re.compile(
    r"总算|终于|好歹|不过|但是|但|然而|搞定了|打完了|写完了|做完了|弄完了|解决了|完成了")

STUDY_WORDS = re.compile(r"学|复习|背|考研|考试|初试|题|作业|论文|毕设|图书馆|课|书")

CONDITIONAL_WORDS = re.compile(r"看不完|看不下去|学不完|背不完|复习不完|考不完")

STUDY_STRESS = re.compile(r"来不及|压力|焦虑|赶不上|没时间|时间不够")

WHIMPER_PURE = re.compile(r"^(?:呜+|嘤+|唔+|QAQ|qaq|T_T|T﹏T)[。！？~～…\s]*$")
WHIMPER_LEAD = re.compile(r"^(?:呜+|嘤+|唔+|QAQ|qaq|T_T|T﹏T)[，,、。！？~～…\s]*.{1,10}$")

THIRD_PARTY = re.compile(
    r"他|她|它|角色|这人|那个人|某人|别人|对方|演员|心菜|卡特莉娜|八惠|知冴|望有|纱茂")

REPAIR_BARE = re.compile(
    r"^(?:好凶|好冲|好冷)(?:呜呜|呜|啊|呀|吧)?[。！？~～…\s]*$|"
    r"^(?:怎么|干嘛|为什么)(?:这么|那么)?(?:凶|冲)[^。！？!?]{0,4}[呀啊吧呜…!！。]*$")

REPAIR_SELF_TONE = re.compile(
    r"(?:你怎么|你)(?:这么|那么|太|有点|好)[^。！？!?]{0,2}(?:凶|冲|冷)|"
    r"你怎么凶我|你凶我|你冲我")

REPAIR_SPEECH_TONE = re.compile(
    r"(?:你|静香)(?:刚才|刚刚)?[^。！？!?]{0,6}(?:说话|语气|态度)[^。！？!?]{0,6}(?:凶|冲|冷|冷淡|冷冰冰)")

REPAIR_TOPIC_TONE = re.compile(
    r"(?:你|静香)(?:一提|一提到|一说|一说起|提到|说起)?[^。！？!?]{0,4}"
    r"(?:心菜|他|她)[^。！？!?]{0,8}(?:凶|冲|冷|冷淡)")

REPAIR_IMPERATIVE = re.compile(
    r"(?:别|不要)[^。！？!?]{0,4}(?:这么|那么)(?:凶|冲|冷)")


def _has_third_party(text):
    return bool(THIRD_PARTY.search(text or ""))


def repair_evidence(text):
    """Return a reason label when the line is relationship feedback, else None."""
    text = (text or "").strip()
    if not text:
        return None
    if REPAIR_SELF_TONE.search(text):
        return "repair_self_tone"
    if REPAIR_SPEECH_TONE.search(text):
        return "repair_speech_tone"
    if REPAIR_TOPIC_TONE.search(text):
        return "repair_topic_tone"
    if REPAIR_BARE.match(text) and not _has_third_party(text):
        return "repair_bare"
    if REPAIR_IMPERATIVE.search(text) and not _has_third_party(text):
        return "repair_imperative"
    return None


def _recent_fragile(state, window=3):
    last = getattr(state, "last_fragile_turn", None)
    turn = getattr(state, "turn", 0)
    return isinstance(last, int) and 0 <= turn - last <= window


def care_evidence(text, situation, signals, state=None):
    """Return a reason label when the line is a fragility bid, else None."""
    text = (text or "").strip()
    resolved = bool(RESOLVED_OUTCOME.search(text))
    high = bool(HIGH_PRECISION.search(text))
    emotional = bool(signals.get("emotional_bid")) \
        or (situation or {}).get("kind") == "share_negative"
    if emotional:
        if resolved and not high:
            return None
        return "emotional_bid"
    if high:
        return "high_precision_words"
    if TIRED_WORDS.search(text) and not resolved:
        return "tired_words"
    if STUDY_STRESS.search(text) and STUDY_WORDS.search(text):
        return "study_stress"
    if CONDITIONAL_WORDS.search(text):
        if _recent_fragile(state):
            return "conditional_with_context"
        last_user = getattr(state, "last_user_text", "") or ""
        if STUDY_WORDS.search(text) or STUDY_WORDS.search(last_user):
            return "conditional_with_study_context"
        return None
    if WHIMPER_PURE.match(text):
        if _recent_fragile(state):
            return "whimper_with_context"
        if getattr(state, "last_posture", None) in ("care", "repair"):
            return "whimper_after_posture"
        return None
    if WHIMPER_LEAD.match(text) and len(text) <= 14:
        return "whimper_short_complaint"
    return None


def posture_for(text, situation, signals, state=None, boundary=False):
    """Return (posture, evidence). posture: boundary / repair / care / neutral."""
    if boundary or (situation or {}).get("is_boundary") \
            or (situation or {}).get("kind") == "boundary":
        return "boundary", ["boundary"]
    reason = repair_evidence(text)
    if reason:
        return "repair", [reason]
    reason = care_evidence(text, situation or {}, signals or {}, state)
    if reason:
        return "care", [reason]
    return "neutral", []
