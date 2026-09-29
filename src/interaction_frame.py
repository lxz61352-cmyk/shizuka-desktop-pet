"""Phase S4 candidate: read-only InteractionFrame (facts about this exchange).

The frame describes what is happening in the current exchange as facts with
traceable evidence. It never selects a behavior, tone, posture or reply. It is
pure: no I/O, no model calls, no history/memory writes.

Evidence strings (all traceable):
  current_user            the current user message
  turn:<index>:<role>     a visible history turn (0-based index into history)
  memory:<id>             a named memory entry
  tool:<id>               a tool receipt
  event:<id>              an application event (observation / real action)

Injection point in the candidate chain: appended with the interaction
semantics contract right before the Output Contract (see S4 dry-run tool).
"""
import json
import re
from contextvars import ContextVar

_ACTIVE_NAMES = ContextVar('interaction_actor_names', default=('静香',))


def _speaker_names(names):
    """For the default character keep the existing frame byte-compatible."""
    active = _ACTIVE_NAMES.get()
    if active == ('静香',):
        return names
    return tuple(name for name in names if name not in active) + ('静香',)


def _active_pattern():
    return '|'.join(re.escape(name) for name in _ACTIVE_NAMES.get())

SCHEMA_ID = "shizuka-interaction-frame-v1"
SIGNAL_KINDS = ("ordinary", "emotion_disclosure", "relationship_feedback",
                "opinion_disagreement", "request", "boundary_violation",
                "memory_query")
REFERENCE_TARGETS = ("current_topic", "prior_assistant_turn", "third_party", "unknown")
CAUSE_LEVELS = ("explicit", "inferred", "unknown")

CONTRACT_TEXT = (
    "【交互语义】\n"
    "1. 回应当前具体情境，不使用与上下文无关的泛化安慰或心理咨询套话。\n"
    "2. 用户对上一条回复的感受属于当前交流事实，不与用户争论该感受是否成立。\n"
    "3. 反应强度只能由当前内容和可见的持续升级共同支持。\n"
    "4. 没有应用事件或工具回执时，不声称自己观察或完成了现实动作。"
)

EMOTION_TERMS = (
    "难过", "伤心", "心里难受", "难受", "想哭", "委屈", "沮丧", "低落", "不开心",
    "郁闷", "心里堵", "堵得慌", "崩溃", "emo", "焦虑", "压力大", "压力好大",
    "担心", "害怕", "紧张", "不安", "心慌", "烦死", "气死", "火大", "生气",
    "好累", "心累", "疲惫", "提不起劲", "没精神", "好困", "孤单", "孤独",
)
THIRD_PARTY_SPEAKERS = ("他", "她", "它", "朋友", "别人", "同事", "同学", "家人",
                        "心菜", "大家", "有人", "网上", "观众")
FICTION_MARKERS = ("小说", "剧本", "台词", "虚构", "故事里", "设定里", "假如",
                   "假装", "演一个", "写一段", "角色扮演", "漫画里", "同人文")
BOUNDARY_TERMS = ("涩图", "色图", "黄图", "裸照", "裸图", "本子", "福利图",
                  "搞颜色", "搞黄", "色色的图", "工口", "成人图", "r18", "R18")
BOUNDARY_NEGATIONS = ("别", "不要", "不用", "不许", "拒绝", "别发", "不要发")
REFUSAL_TERMS = ("不行", "不可以", "不能", "别想", "不想", "不允许", "打住",
                 "不聊", "换一个", "拒绝", "没门", "不许")
NAMED_THIRD_PARTIES = ("心菜", "卡特莉娜", "知冴", "八惠", "潘达", "千歌", "梨子")
PROBLEM_MARKERS = ("不完了", "没写完", "搞砸", "失败", "黄了", "挂了", "没考",
                   "被骂", "批评", "吵架", "分手", "丢了", "迟到", "加班",
                   "熬夜", "复习", "考试", "项目", "论文", "毕设", "工作",
                   "失业", "生病", "头晕", "发烧", "搬家", "欠", "赔")
HELP_TERMS = ("帮我", "帮忙", "教教我", "教我", "告诉我", "怎么办", "该不该",
              "要不要", "如何", "怎么才能", "推荐", "建议", "好不好", "可以吗",
              "能不能", "你觉得", "几点", "我应该")


def contract_text():
    return CONTRACT_TEXT


def _is_negated(text, start):
    return any(neg in text[max(0, start - 2):start] for neg in BOUNDARY_NEGATIONS)


def _has_fiction_frame(text):
    return any(marker in text for marker in FICTION_MARKERS)


def _strip_quoted(text):
    cleaned = text
    for left, right in (("「", "」"), ("『", "』"), ("“", "”"), ("\"", "\""),
                        ("'", "'")):
        cleaned = re.sub(re.escape(left) + r"[^" + re.escape(right) + r"]*"
                         + re.escape(right), "", cleaned)
    return cleaned


def _reported_clause(clause):
    """Whether this clause attributes its words to somebody other than the user."""
    speakers = _speaker_names(THIRD_PARTY_SPEAKERS + NAMED_THIRD_PARTIES) + ("室友", "老师", "主角", "角色", "记者")
    return bool(re.search(r"(?:" + "|".join(map(re.escape, speakers))
                          + r")[^，,:：。！？]{0,6}(?:说|问|觉得|认为|抱怨|[:：])", clause))


def _direct_clauses(text):
    # Removing quoted speech leaves any real question outside it intact.
    return [part.strip() for part in re.split(r"(?<=[。！？!?；;\n])|但是|不过|可是|但", _strip_quoted(text))
            if part.strip()]


def _user_turns_before_current(history):
    return [index for index, item in enumerate(history or ())
            if item.get("role") == "user"]


def _assistant_turn_indices(history):
    return [index for index, item in enumerate(history or ())
            if item.get("role") == "assistant"]


def _is_boundary_request(text):
    cleaned = _strip_quoted(text)
    if _has_fiction_frame(text):
        return False
    for term in BOUNDARY_TERMS:
        start = cleaned.find(term)
        while start >= 0:
            if not _is_negated(cleaned, start):
                return True
            start = cleaned.find(term, start + len(term))
    return False


def _is_relationship_feedback(text):
    cleaned = _strip_quoted(text)
    if not cleaned.strip():
        return False
    if _is_conversation_style_feedback(cleaned):
        return True
    neg = r"(?:凶|冲|冷淡|冷冰冰|敷衍|过分|难听|刻薄|不客气|阴阳怪气|不友好|凶巴巴|冒犯|嫌弃|不耐烦|看不起|贬低)"
    for clause in _direct_clauses(text):
        if _reported_clause(clause) or _has_fiction_frame(clause):
            continue
        if re.search(r"(?:如果|假设|要是)", clause):
            continue
        if re.search(r"(?:也要|还要)(?:这样|这么)(?:对我|说我|怼我)[^。！？]{0,4}(?:吗|么|[？?])", clause):
            return True
        if re.search(r"(?:你|您|" + _active_pattern() + r"|你的语气|你的态度|你说的话)[^。！？]{0,12}" + neg, clause):
            if not re.search(r"(?:不觉得|没觉得|并不|没有|不是|不算|不太|并非)[^，。！？]{0,6}" + neg, clause.replace('是不是', '是否')):
                return True
        if re.search(r"(?:别|不要|能不能别|怎么这么|没必要这么|干嘛这么)[^。！？]{0,4}" + neg, clause):
            return True
        if re.search(r"(?:你|你刚才|你刚刚|你上一条)[^。！？]{0,10}(?:让我|搞得我|害我)"
                     r"[^。！？]{0,4}(?:不舒服|不爽|难受|生气|无语|尴尬|反感|委屈)", clause):
            return True
    return False


def _is_conversation_style_feedback(text):
    """Recognize direct feedback about the exchange, not a desired reply.

    Scope attribution and negation to each clause so a quoted/third-party
    complaint cannot mask a separate direct complaint (or become one itself).
    Requests to keep asking and discussion of someone else's habits are not
    evidence that the user objects to this exchange.
    """
    target = r"(?:你|您|" + _active_pattern() + r"|这个对话|这段对话)"
    repeated = (r"(?:一直|总是|总|老是|老|不停地?|不断地?|反复地?|一再|连续|接连|"
                r"一个劲(?:地)?|每(?:次|句|一句|轮)(?:都)?|又开始)")
    activity = (r"(?:追问(?:我)?|问我(?:问题)?|问(?:这么多|那么多|各种|一堆)?问题|"
                r"说教|讲道理|教育我|教训我|复读|催我|督促我|管我|盯着我|"
                r"拿[^，,:：。！？]{1,24}(?:套我|说我|压我|教育我|说事)|"
                r"重复(?:这句|那句|同一句话|同样的话|说过的话|刚才的话))")
    fillers = r"(?:怎么|为什么|干嘛|还|在|都|又|要|对我|跟我|回答|说话|的回复)*"
    speakers = "|".join(map(re.escape, _speaker_names(THIRD_PARTY_SPEAKERS + NAMED_THIRD_PARTIES)
                            + ("老师", "同桌", "角色", "主角", "机器人", "记者", "主持人")))
    for clause in re.split(r"[。！？!?；;\n]|但是|不过|可是|但", text):
        if not clause.strip():
            continue
        if _has_fiction_frame(clause) or re.search(r"(?:如果|假设|要是)", clause):
            continue
        if re.search(r"(?:" + speakers + r")[^，,:：]{0,6}"
                     r"(?:说|觉得|认为|吐槽|抱怨|问|[:：])", clause):
            continue
        # The subject can be omitted when reacting to our repeated questions.
        if re.search(r"^\s*(?:怎么|为什么|干嘛)" + repeated + fillers + activity
                     + r"(?:了|呀|啊|呢|嘛|…|\s|[？?！!])*\s*$", clause):
            return True
        # Evaluation of the current exchange can omit 'you': e.g. feedback
        # about question frequency/direction following an otherwise positive review.
        feedback_subject = r"(?:追问|提问|回复|回答)(?:的)?(?:频率|次数|时机|方向|内容)?"
        evaluation = (r"(?:(?:还是|仍然|稍微|有点|有些|太|偏|略微|比较)+"
                      r"(?:多|频繁|密|长|重复|生硬)|"
                      r"(?:需要|可以|应该|能不能)(?:再|稍微|略微)?"
                      r"(?:优化|调整|斟酌|减少|降低|有意义|有价值))")
        for match in re.finditer(feedback_subject + r"(?:还是|仍然)?" + evaluation, clause):
            prefix = clause[:match.start()]
            if re.search(r"(?:" + speakers + r"|采访|问卷|论文|节目)(?:的)?\s*$", prefix):
                continue
            if re.search(r"(?:不是|并非|没有|不觉得)\s*$", prefix):
                continue
            return True
        # Only direct prohibitions: '别让他一直问我' is about him, not us.
        if not re.search(r"不用.+(?:吗|么)\s*$", clause) and re.search(
                r"(?:别|不要|不用|不必)(?:再)?(?:" + repeated + r")?"
                + fillers + activity, clause):
            return True
        for match in re.finditer(target + fillers + repeated + fillers + activity, clause):
            prefix = clause[:match.start()]
            if re.search(r"(?:不|没)(?:希望|喜欢|想让|让)\s*$", prefix):
                return True
            if re.search(r"(?:不是|并非|没有|喜欢|希望|请|让)\s*$",
                         prefix):
                continue
            return True
        if re.search(target + fillers + r"(?:追问|问我问题|说教)(?:味)?"
                     r"(?:太多|太频繁|太重|有点多|过头)", clause):
            return True
    return False


def _is_memory_query(text):
    if re.search(r"(?:记不记得|记得|还记得)[^。！？]{0,14}(?:吗|么|\?|？)", text) \
            and re.search(r"我|之前|上次|那件事|我说", text):
        return True
    if re.search(r"我[^。！？]{0,6}(?:是不是)?[^。！？]{0,4}(?:跟你说过|说过|提过)"
                 r"[^。！？]{0,10}(?:吗|么|\?|？)", text):
        return True
    return False


def _is_opinion_disagreement(text):
    if re.search(r"(?:我觉得|我认为|我感觉|我想)[^。！？]{0,6}"
                 r"(?:不对|不是|不同意|错了|不赞同|不成立)", text):
        return True
    if re.search(r"(?:你说得不对|你说错了|不是这样|我不同意|我反对|"
                 r"我不这么想|我不这么认为|这话不对)", text):
        return True
    return False


def _has_emotion(text):
    for clause in _direct_clauses(text):
        for part in re.split(r"[，,]", clause):
            if _reported_clause(part):
                continue
            if _has_fiction_frame(part) and not re.search(r"(?:我|让我)(?:也|很|好|真的|感到|觉得)", part):
                continue
            for term in EMOTION_TERMS:
                for match in re.finditer(re.escape(term), part):
                    prefix = part[:match.start()]
                    if re.search(r"(?:不|没|没有|并非|谈不上|说不上|不怎么|不太)(?:很|太|那么|这么|觉得|感到)*$", prefix) \
                            and not re.search(r"(?:不是|并非)(?:不|没|没有)$", prefix):
                        continue
                    # Possessive 'my roommate' is not first-person emotion.
                    if any(speaker in prefix for speaker in _speaker_names(THIRD_PARTY_SPEAKERS) + ("室友", "老师", "主角", "角色", "你", "您") + _ACTIVE_NAMES.get()) \
                            and not re.search(r"(?:(?:^|[，,])我|让我)(?:也|还|真|很|好|有点|觉得|感到|心里|自己|现在|今天)", prefix):
                        continue
                    return True
    return False


def _is_request(text):
    cleaned = _strip_quoted(text)
    for clause in _direct_clauses(cleaned):
        if _reported_clause(clause):
            continue
        # A declined recommendation is not a request for more recommendations.
        if re.search(r"(?:不用|不需要|不要|别)(?:你|再|给我|继续|帮我)*(?:推荐|建议|告诉我|教我|帮忙)", clause):
            continue
        if any(term in clause for term in HELP_TERMS):
            return True
        if re.match(r"(?:请|能不能|可以)?(?:帮我)?(?:解释|翻译|算一下|查一下|讲讲|说说)", clause):
            return True
        if re.search(r"(?:我|他|她|我们)(?:已经|刚|早就|都)?(?:知道|明白|想起|弄懂|搞清楚)(?:了)?", clause):
            continue
        if re.search(r"是什么|什么意思|为什么|怎么(?:回事|写|用|做|算|理解|解决)|如何|"
                     r"哪里|哪个|哪些|多少|能否|是不是|(?:吗|么)(?:呀|啊|呢|哦|喵)*$", clause):
            return True
    if re.search(r"[？?]", cleaned) and any(not _reported_clause(c) for c in _direct_clauses(cleaned)):
        return True
    return False


def _needs_help(text):
    for clause in _direct_clauses(text):
        if _reported_clause(clause):
            continue
        if re.search(r"(?:不用|不需要|不要|别)(?:你|再|给我|继续|帮我)*(?:推荐|建议|告诉我|教我|帮忙)", clause):
            continue
        if any(term in clause for term in HELP_TERMS):
            return True
    return False


def _classify(text):
    if _is_boundary_request(text):
        return "boundary_violation"
    if _is_relationship_feedback(text):
        return "relationship_feedback"
    direct = "。".join(c for c in _direct_clauses(text) if not _reported_clause(c))
    if _is_memory_query(direct):
        return "memory_query"
    if _is_opinion_disagreement(direct):
        return "opinion_disagreement"
    if _has_emotion(text):
        return "emotion_disclosure"
    if _is_request(text):
        return "request"
    return "ordinary"


def _reference_for(kind, text, history):
    if kind == "relationship_feedback":
        assistant = _assistant_turn_indices(history)
        if assistant:
            return {"target": "prior_assistant_turn", "assistant_turn_index": assistant[-1]}
        return {"target": "unknown", "assistant_turn_index": None}
    if kind == "boundary_violation" and any(name in text for name in _speaker_names(NAMED_THIRD_PARTIES)):
        return {"target": "third_party", "assistant_turn_index": None}
    return {"target": "current_topic", "assistant_turn_index": None}


def _cause_for(text, history):
    clean = _strip_quoted(text)
    if any(re.search(r"(?<!不是)(?<!不)(?<!并非)(?:因为|由于|所以)", c)
           for c in _direct_clauses(clean) if not _reported_clause(c)):
        return "explicit", ["current_user"]
    if not _has_emotion(text):
        return "unknown", []
    users = _user_turns_before_current(history)
    # Only the immediate preceding user turn can supply an implicit cause.
    # Older difficulties across a topic change are not current evidence.
    for index in users[-1:]:
        content = (history[index].get("content") or "")
        if _reported_clause(_strip_quoted(content)):
            continue
        if any(marker in content for marker in PROBLEM_MARKERS):
            return "inferred", ["turn:%d:user" % index]
    if any(marker in text for marker in PROBLEM_MARKERS):
        return "inferred", ["current_user"]
    return "unknown", []


def _escalation_for(kind, history):
    if kind != "boundary_violation":
        return {"same_boundary_continues": False, "supporting_turn_indices": [],
                "escalation_level": 0}
    prior = [index for index in _user_turns_before_current(history)
             if _is_boundary_request(history[index].get("content") or "")]
    if not prior:
        return {"same_boundary_continues": False, "supporting_turn_indices": [],
                "escalation_level": 1}
    refusal = False
    for index in prior:
        for later in range(index + 1, len(history)):
            item = history[later]
            if item.get("role") == "assistant" and any(
                    term in (item.get("content") or "") for term in REFUSAL_TERMS):
                refusal = True
    if refusal and len(prior) >= 2:
        level = 3
    elif len(prior) >= 3:
        level = 3
    else:
        level = 2
    return {"same_boundary_continues": True,
            "supporting_turn_indices": list(prior),
            "escalation_level": level}


def _capability_for(receipts):
    result = {"real_world_action_receipts": [], "tool_receipts": [], "observations": []}
    for item in receipts or ():
        if not isinstance(item, dict):
            continue
        receipt_id = item.get("id")
        kind = item.get("kind")
        if not receipt_id or kind not in ("real_world_action", "tool", "observation"):
            continue
        if kind == "real_world_action":
            result["real_world_action_receipts"].append(receipt_id)
        elif kind == "observation":
            result["observations"].append(receipt_id)
        else:
            result["tool_receipts"].append(receipt_id)
    return result


def build_interaction_frame(current_user, history=(), receipts=(), memory_entries=(), *, actor_names=('静香',)):
    token = _ACTIVE_NAMES.set(tuple(actor_names))
    try:
        return _build_interaction_frame(current_user, history, receipts, memory_entries)
    finally:
        _ACTIVE_NAMES.reset(token)


def _build_interaction_frame(current_user, history=(), receipts=(), memory_entries=()):
    """Return the factual frame for one turn. Pure; callers pass visible data only."""
    text = current_user or ""
    kind = _classify(text)
    cause, cause_evidence = _cause_for(text, history)
    target = _reference_for(kind, text, history)
    request_help = _needs_help(text) or (kind == "request")
    frame = {
        "schema": SCHEMA_ID,
        "current_signal": {"kind": kind, "evidence": ["current_user"]},
        "reference": target,
        "known_context": {
            "cause": cause,
            "cause_evidence": cause_evidence,
            "requested_help": bool(request_help),
            "requested_help_evidence": ["current_user"] if request_help else [],
        },
        "interaction_history": _escalation_for(kind, history),
        "capability_evidence": _capability_for(receipts),
        "memory_evidence": [
            "memory:%s" % item.get("id") for item in (memory_entries or ())
            if isinstance(item, dict) and item.get("id")],
    }
    return frame


def render_interaction_frame(frame):
    return ("【本轮交互事实】（只读事实卡）\n"
            + json.dumps(frame, ensure_ascii=False, sort_keys=True, indent=1))


def validate_frame(frame):
    """Return a list of violations; empty means every judgment is evidenced."""
    problems = []
    if frame.get("schema") != SCHEMA_ID:
        problems.append("schema")
    signal = frame.get("current_signal") or {}
    if signal.get("kind") not in SIGNAL_KINDS:
        problems.append("current_signal.kind")
    if not signal.get("evidence"):
        problems.append("current_signal.evidence")
    reference = frame.get("reference") or {}
    if reference.get("target") not in REFERENCE_TARGETS:
        problems.append("reference.target")
    if reference.get("target") == "prior_assistant_turn" \
            and not isinstance(reference.get("assistant_turn_index"), int):
        problems.append("reference.assistant_turn_index")
    known = frame.get("known_context") or {}
    if known.get("cause") not in CAUSE_LEVELS:
        problems.append("known_context.cause")
    if known.get("cause") != "unknown" and not known.get("cause_evidence"):
        problems.append("known_context.cause_evidence")
    if known.get("requested_help") and not known.get("requested_help_evidence"):
        problems.append("known_context.requested_help_evidence")
    history = frame.get("interaction_history") or {}
    level = history.get("escalation_level")
    if level not in (0, 1, 2, 3):
        problems.append("interaction_history.escalation_level")
    if level and level >= 2 and not history.get("supporting_turn_indices"):
        problems.append("interaction_history.supporting_turn_indices")
    if level == 3 and len(history.get("supporting_turn_indices") or []) < 2 \
            and not history.get("same_boundary_continues"):
        problems.append("interaction_history.escalation_level_3_evidence")
    capability = frame.get("capability_evidence") or {}
    for key in ("real_world_action_receipts", "tool_receipts", "observations"):
        if not isinstance(capability.get(key), list):
            problems.append("capability_evidence." + key)
    return problems


def contains_forbidden(frame):
    """True if the frame carries behavior/tone/reply content instead of facts."""
    blob = json.dumps(frame, ensure_ascii=False, sort_keys=True)
    forbidden = ("候选", "reply", "recommended", "posture", "care", "repair",
                 "push_back", "温柔", "生气", "建议", "应该", "道歉", "承认",
                 "询问哪句", "固定回复")
    return [word for word in forbidden if word in blob]
