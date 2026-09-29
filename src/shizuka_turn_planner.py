"""7A shadow planner built from the existing local decision sources.

Nothing returned here is used to compose prompts in 7A-1.  The adapter makes
the old classifiers observable through one contract before they are replaced.
"""
import hashlib
import json
import os
import random
import re
import time

from dialogue_turn import CharacterFrame, ShadowTurn, TurnPolicy, TurnUnderstanding
from conversation_state import detect_intent, is_empty_contact
from response_mode import TASK_VERBS, hits_boundary, is_life_report
from shizuka_turn_context import communication_limits
from shizuka_turn_context import has_followup_request


_REQUIRED_KINDS = frozenset(("question", "task", "ask_help"))
_LOW_INFORMATION = frozenset(("empty_call", "empty_filler"))
_SOCIAL_QUESTION_RE = re.compile(
    r"(?:你|静香).{0,14}(?:喜欢|讨厌|想不想|愿不愿意|怎么看|觉得|在意|害怕|开心|难过|"
    r"什么意思|怎么想|怎么演)"
)
_RELATIONSHIP_FEEDBACK_RE = re.compile(
    r"(?:你说话|你的回复|你聊天|你回应).{0,16}(?:像|不像|僵硬|机械|客服|真人感|AI|ai)|"
    r"(?:没有|没什么|缺少).{0,8}真人感|"
    r"你(?:刚才|刚刚)?.{0,8}(?:说话|那句|回复).{0,10}(?:让我|使我).{0,6}(?:不舒服|难受|生气)|"
    r"(?:你|静香).{0,10}(?:根本|一点也)?不在乎(?:我|这件事|这个)?|"
    r"你(?:别|不要).{0,8}(?:解释规则|讲规则).{0,12}(?:怎么想|什么意思)|"
    r"你怎么.{0,6}(?:凶我|冲我|不理我)"
)
_CORRECTION_RE = re.compile(r"(?:不对|错了|不是这样|我说的是|我的意思是|更正一下|其实不是)")
_REPORT_FRAME_RE = re.compile(r"^(?:我|我们)?(?:正在|在|刚在)?.{0,6}(?:讨论|聊|研究|说的是)")
_INFORMATION_QUESTION_RE = re.compile(
    r"^(?:为什么|为啥|怎么回事|谁|多少|哪个|哪种|如何).+|"
    r"(?:天气|情况|结果).{0,12}(?:怎么样|如何)|"
    r"(?:是什么|什么意思|有什么区别|有何区别|"
    r"从哪(?:来|来的)|做什么的|干什么的|如何.{0,12}(?:做|算|处理|解释)|"
    r"是不是|是否|能不能|可不可以|还记得吗|记得吗|意思[吗码]|"
    r"(?:解释清楚|说明白|讲清楚)了吗|是你吗)(?:[？?]|$)|.+吗(?:[？?]|$)"
)
_REQUEST_RE = re.compile(
    r"(?:请|帮我|给我|替我|讲一下|讲讲|查一下|记住|记一下)|"
    r"^如果.{1,30}就(?:直说|告诉我|说明|别|不要)"
)
_COMMUNICATION_BOUNDARY_RE = re.compile(
    r"(?:别|不要|不用).{0,8}(?:解释规则|讲规则|上课|说教)"
)
_GREETING_RE = re.compile(r"^(?:ciallo|hello|hi|嗨|你好|早上好|中午好|晚上好)[!！~～。]*$", re.I)
_TEASE_RE = re.compile(r"(?:大蠢鱼|笨鱼|笨蛋|傻瓜|逗你|开玩笑)")
_WEATHER_DOMAIN_RE = re.compile(
    r"天气|气温|温度|降雨|降雪|下雨|下雪|雨(?:势|量)?|雪(?:势|量)?|"
    r"多少度|几度|冷不冷|热不热|带伞|穿什么|穿衣|"
    r"(?:今天|外面|现在).{0,3}(?:真|好|很|太)?[冷热]"
)
_WEATHER_LOOKUP_RE = re.compile(
    r"(?:帮我|替我|给我|请你|麻烦你)?.{0,8}(?:查|查一下|查询|搜|看一下|看看|告诉我|报一下).{0,16}"
    r"(?:天气|气温|温度|降雨|降雪|下雨|下雪|多少度|几度)|"
    r"(?:天气|气温|温度|降雨|降雪).{0,12}(?:怎么样|如何|多少|几度)|"
    r"(?:多少度|几度)|"
    r"(?:会不会|有没有|是不是|是否).{0,10}(?:下雨|下雪|降雨|降雪)|"
    r"(?:下雨|下雪|降雨|降雪).{0,4}(?:吗|么|嘛)|"
    r"(?:要不要|需不需要|该不该).{0,6}带伞|(?:冷不冷|热不热)(?:[？?]|$)"
)
_NON_LOOKUP_FRAME_RE = re.compile(
    r"^(?:如果|假如|假设|听说)|(?:喜欢|讨厌|希望|庆幸|幸好).{0,8}(?:下雨|下雪|天气)|"
    r"(?:下雨|下雪|天气).{0,8}(?:怎么办|怎么做|意味着什么)"
)

# 7B owns the legacy-compatible local inputs while callers migrate to the
# unified TurnUnderstanding/TurnPolicy contract.  These are intentionally kept
# in this module so situation/affordance/authority/decision have one owner.
_PRAISE_RE = re.compile(
    r'(?:你|静香)[^。！？!?]{0,6}(?:可爱|好懂|厉害|真好|温柔|靠谱)|你怎么这么(?:懂|好)|多亏了你|有你真好|谢谢静香')
_SITUATION_TEASE_RE = re.compile(r'你好笨|真笨|太笨|这么笨|傻瓜|笨蛋|憨|笑你|逗你玩|开你玩笑')
_CHALLENGE_RE = re.compile(r'敢不敢|试试就试试|不信|不服|就这|你能行吗|不会是不敢吧|怂了')
_ASK_HELP_RE = re.compile(r'怎么办|咋办|帮我|帮忙|不会弄|不知道怎么做|教教我|救救|卡住了|搞不定|救一下')
_ACHIEVE_RE = re.compile(r'终于.{0,6}(?:做完|写完|弄完|搞定|完成|交了)|搞定了|弄好了|做完了|写完了|完成了')
_NEGATIVE_RE = re.compile(r'好累|累死|心累|难受|好烦|烦死|委屈|想哭|撑不住|难过|崩溃|压力大|郁闷|想死|状态不太好|状态很差')
_KOKONA_RE = re.compile(r'心菜')
_STAGE_RE = re.compile(r'表演|演技|舞台|角色|剧本|演员|公演|试镜|台词|剧团')
_NEW_TOPIC_RE = re.compile(r'^(?:对了|话说|另外|说起来|还有|顺带|突然想到|哦对|诶对)')
_HELP_HINT_RE = re.compile(r'怎么办|帮我|你觉得|该不该|要不要|帮我选|行不行')
_INVITES_OPINION_RE = re.compile(r'你觉得呢|你怎么看|你的看法|你的意见|讲讲你|说说你|你想说|要不要讲|想聊什么')

BEHAVIORS = ("普通观察", "即时吐槽", "玩笑·玩心", "关心", "认真", "冲突与反击", "犹豫·脆弱",
             "反应性发言", "主动话题", "收尾", "沉默或少说", "被夸奖时的反应", "自我表达")
PLAIN = "普通回应"
BASE_WEIGHTS = {
    "share_casual": {PLAIN: 25, "普通观察": 10, "即时吐槽": 14, "玩笑·玩心": 10, "关心": 4,
                     "反应性发言": 18, "主动话题": 5, "收尾": 6, "自我表达": 8},
    "share_achievement": {PLAIN: 20, "普通观察": 8, "即时吐槽": 7, "玩笑·玩心": 6, "关心": 8,
                          "反应性发言": 20, "主动话题": 4, "收尾": 9, "自我表达": 18},
    "share_negative": {PLAIN: 20, "普通观察": 3, "即时吐槽": 7, "玩笑·玩心": 3, "关心": 25, "认真": 4,
                       "反应性发言": 20, "收尾": 8, "自我表达": 10},
    "praise": {PLAIN: 18, "普通观察": 3, "玩笑·玩心": 8, "关心": 3, "反应性发言": 16,
               "收尾": 4, "被夸奖时的反应": 38, "自我表达": 10},
    "tease": {PLAIN: 15, "普通观察": 4, "即时吐槽": 8, "玩笑·玩心": 26, "冲突与反击": 8,
              "反应性发言": 20, "收尾": 5, "沉默或少说": 4, "自我表达": 10},
    "challenge": {PLAIN: 10, "即时吐槽": 8, "玩笑·玩心": 8, "认真": 5, "冲突与反击": 36,
                  "反应性发言": 18, "收尾": 5, "沉默或少说": 5, "自我表达": 5},
    "question": {"即时吐槽": 5, "玩笑·玩心": 5, "认真": 80, "反应性发言": 5, "收尾": 5},
    "task": {"认真": 80, "反应性发言": 10, "收尾": 10},
    "ask_help": {"关心": 10, "认真": 80, "反应性发言": 5, "收尾": 5},
    "greeting": {PLAIN: 30, "普通观察": 6, "玩笑·玩心": 3, "关心": 7, "反应性发言": 36,
                 "主动话题": 4, "收尾": 7, "沉默或少说": 5, "自我表达": 2},
    "goodbye": {"反应性发言": 20, "收尾": 80},
    "boundary": {"冲突与反击": 80, "反应性发言": 20},
    "empty_call": {"反应性发言": 70, "收尾": 20, "沉默或少说": 10},
    "empty_filler": {"反应性发言": 40, "收尾": 30, "沉默或少说": 30},
    "general": {PLAIN: 30, "普通观察": 13, "即时吐槽": 10, "玩笑·玩心": 7, "关心": 3, "认真": 3,
                "反应性发言": 20, "主动话题": 4, "收尾": 4, "沉默或少说": 6},
}
TOPIC_MOD = {"心菜": {"自我表达": 10}, "表演": {"自我表达": 10}}
TASK_KINDS = ("task", "ask_help", "question")
COOL_DOWN = 0.4
JITTER = 0.1
LOG_MAX_LINES = 512


def classify_situation(text, state=None):
    text = (text or "").strip()
    situation = {"kind": "general", "topic": "无", "is_task": False, "is_boundary": False}
    if _KOKONA_RE.search(text):
        situation["topic"] = "心菜"
    elif _STAGE_RE.search(text):
        situation["topic"] = "表演"
    if hits_boundary(text):
        situation.update(kind="boundary", is_boundary=True)
        return situation
    if communication_limits(text) and not has_followup_request(text):
        situation["kind"] = "communication_preference"
        return situation
    if (state is not None and getattr(state, "current_interaction", None)
            and state.current_interaction.get("current_text") == text and is_empty_contact(text)):
        situation["kind"] = "share_casual"
        return situation
    intent = detect_intent(text)
    if intent == "request" or any(word in text for word in TASK_VERBS):
        situation.update(kind="task", is_task=True)
    elif _ASK_HELP_RE.search(text):
        situation["kind"] = "ask_help"
    elif is_empty_contact(text) == "call":
        situation["kind"] = "empty_call"
    elif is_empty_contact(text) == "filler":
        situation["kind"] = "empty_filler"
    elif intent == "question" or intent == "advice":
        situation["kind"] = "question"
    elif intent == "goodbye":
        situation["kind"] = "goodbye"
    elif intent == "greeting":
        situation["kind"] = "greeting"
    elif _CHALLENGE_RE.search(text):
        situation["kind"] = "challenge"
    elif _PRAISE_RE.search(text):
        situation["kind"] = "praise"
    elif _SITUATION_TEASE_RE.search(text):
        situation["kind"] = "tease"
    elif _ACHIEVE_RE.search(text):
        situation["kind"] = "share_achievement"
    elif _NEGATIVE_RE.search(text) or intent == "emotion":
        situation["kind"] = "share_negative"
    elif intent == "sharing" or is_life_report(text):
        situation["kind"] = "share_casual"
    return situation


def interaction_signals(situation, text, state=None):
    kind = situation.get("kind") or "general"
    text = (text or "").strip()
    signals = {
        "speech_type": "statement", "openness": "closed", "emotional_bid": False,
        "explicit_help": False, "playful_bid": False,
        "topic_shift": bool(_NEW_TOPIC_RE.match(text)),
        "invites_opinion": bool(_INVITES_OPINION_RE.search(text)),
    }
    if kind in ("boundary", "communication_preference"):
        signals["speech_type"] = "boundary"
    elif kind in ("task", "ask_help") or (kind != "question" and _HELP_HINT_RE.search(text)):
        signals.update(explicit_help=True, speech_type="question", openness="open")
    elif kind == "question":
        signals.update(speech_type="question", openness="open")
    elif kind in ("empty_call", "empty_filler"):
        signals["speech_type"] = "phatic"
    elif kind == "greeting":
        signals["speech_type"] = "phatic"
    elif kind == "share_achievement":
        signals["openness"] = "open"
    elif kind == "share_negative":
        signals.update(emotional_bid=True, openness="open")
    elif kind in ("praise", "tease", "challenge"):
        signals.update(playful_bid=True, openness="open")
    elif kind != "goodbye":
        signals["openness"] = "closed" if len(text) <= 10 and not re.search(r'[？?]', text) else "open"
        if re.search(r'[？?]', text):
            signals["speech_type"] = "question"
    return signals


def response_authority(signals, situation=None):
    speech = signals.get("speech_type")
    if signals.get("explicit_help") or speech == "question":
        if signals.get("invites_opinion"):
            return {"answer_scope": "full", "continuation": "high", "evaluation": "free", "management": "free"}
        return {"answer_scope": "full", "continuation": "low", "evaluation": "free", "management": "free"}
    if speech == "boundary":
        return {"answer_scope": "brief", "continuation": "near_zero", "evaluation": "free", "management": "none"}
    if speech == "phatic":
        return {"answer_scope": "brief", "continuation": "near_zero", "evaluation": "none", "management": "none"}
    if signals.get("topic_shift"):
        return {"answer_scope": "direct", "continuation": "low", "evaluation": "observation", "management": "none"}
    if signals.get("emotional_bid"):
        return {"answer_scope": "direct", "continuation": "low", "evaluation": "none", "management": "none"}
    if signals.get("playful_bid"):
        return {"answer_scope": "direct", "continuation": "low", "evaluation": "tease", "management": "none"}
    if situation is not None and situation.get("kind") == "share_achievement":
        return {"answer_scope": "direct", "continuation": "very_low", "evaluation": "observation", "management": "none"}
    if signals.get("openness") == "open":
        return {"answer_scope": "direct", "continuation": "low", "evaluation": "observation", "management": "none"}
    return {"answer_scope": "direct", "continuation": "very_low", "evaluation": "none", "management": "none"}


def weights_for(situation, char_state, relationship, mood):
    kind = situation.get("kind") or "general"
    weights = {b: float(BASE_WEIGHTS.get(kind, BASE_WEIGHTS["general"]).get(b, 0)) for b in BEHAVIORS}
    weights[PLAIN] = float(BASE_WEIGHTS.get(kind, BASE_WEIGHTS["general"]).get(PLAIN, 0))
    for behavior, add in TOPIC_MOD.get(situation.get("topic") or "", {}).items():
        weights[behavior] = weights.get(behavior, 0) + add
    cs = char_state.values if char_state else {}
    rel = relationship.values if relationship else {}
    willingness = getattr(mood, "willingness", 0.7) if mood else 0.7
    weights["玩笑·玩心"] *= 1 + 0.8 * max(0.0, cs.get("playfulness", 0.40) - 0.40)
    weights["反应性发言"] *= 1 + 0.8 * max(0.0, cs.get("embarrassment", 0.10) - 0.20)
    weights["认真"] *= 1 + 0.8 * max(0.0, cs.get("seriousness", 0.35) - 0.45)
    weights["自我表达"] *= 1 + 0.8 * max(0.0, cs.get("seriousness", 0.35) - 0.45)
    weights["收尾"] *= 1 + 0.8 * max(0.0, 0.55 - cs.get("social_openness", 0.60))
    weights["沉默或少说"] *= 1 + 0.8 * max(0.0, 0.55 - cs.get("social_openness", 0.60))
    weights["关心"] *= 1 - 0.6 * max(0.0, 0.45 - rel.get("familiarity", 0.35))
    weights["玩笑·玩心"] *= 1 - 0.6 * max(0.0, 0.45 - rel.get("familiarity", 0.35))
    weights["收尾"] *= 1 + 0.8 * max(0.0, 0.50 - willingness)
    weights["沉默或少说"] *= 1 + 0.8 * max(0.0, 0.50 - willingness)
    weights["玩笑·玩心"] *= 1 + 0.6 * max(0.0, rel.get("playfulness", 0.35) - 0.45)
    return {b: max(0.0, value) for b, value in weights.items()}


def decide(situation, conv_state, char_state, relationship, mood, rng=None):
    picker = rng or random
    kind = situation.get("kind") or "general"
    weights = weights_for(situation, char_state, relationship, mood)
    last = getattr(conv_state, "last_behavior", None)
    if last in weights and last != PLAIN and kind not in TASK_KINDS:
        weights[last] *= COOL_DOWN
    jittered = {b: value * picker.uniform(1 - JITTER, 1 + JITTER) for b, value in weights.items()}
    total = sum(jittered.values())
    if total <= 0:
        return PLAIN, weights
    point, upto, chosen = picker.random() * total, 0.0, PLAIN
    for behavior, value in jittered.items():
        upto += value
        if point <= upto:
            chosen = behavior
            break
    return chosen, weights


def log_turn(path, user_text, situation, relationship, char_state, behavior, weights):
    if not path:
        return
    try:
        entry = {
            "t": time.strftime("%m-%d %H:%M:%S"), "user": (user_text or "")[:60],
            "kind": situation.get("kind"), "topic": situation.get("topic"),
            "emotion": situation.get("emotion"), "behavior": behavior,
            "rel": {d: round(v, 2) for d, v in relationship.snapshot().items()},
            "state": {d: round(v, 2) for d, v in char_state.snapshot().items()},
            "weights": {b: round(v, 1) for b, v in weights.items() if v > 0},
        }
        lines = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[-LOG_MAX_LINES:]))
    except Exception:
        pass


def _stable_rng(text):
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _speech_act(text, situation, signals):
    kind = situation.get("kind") or "general"
    text = (text or "").strip()
    if _RELATIONSHIP_FEEDBACK_RE.search(text or ""):
        return "relationship_feedback"
    if _CORRECTION_RE.search(text or ""):
        return "correction"
    if _COMMUNICATION_BOUNDARY_RE.search(text):
        return "boundary"
    if _REPORT_FRAME_RE.search(text):
        return "casual_share"
    if _GREETING_RE.search(text):
        return "greeting"
    if _REQUEST_RE.search(text):
        return "request"
    if _SOCIAL_QUESTION_RE.search(text):
        return "social_question"
    if _INFORMATION_QUESTION_RE.search(text):
        return "information_question"
    if kind == "question":
        if signals.get("invites_opinion"):
            return "social_question"
        # A bare sentence-final particle is not enough to turn a report into a
        # factual question. Explicit punctuation remains a useful fallback.
        if not re.search(r"[？?]", text):
            return "casual_share"
        return "information_question"
    if _TEASE_RE.search(text):
        return "tease"
    if kind in ("task", "ask_help"):
        return "request"
    if kind in _LOW_INFORMATION:
        return "low_information"
    if kind in ("praise", "challenge"):
        return "playful_probe"
    if kind == "tease":
        return "tease"
    if kind in ("boundary", "communication_preference"):
        return "boundary"
    if kind == "greeting":
        return "greeting"
    if kind == "goodbye":
        return "goodbye"
    if signals.get("emotional_bid"):
        return "casual_share"
    return "casual_share"


def route_action(text, speech_act=None):
    """Return a hard route only when the turn itself supplies enough evidence.

    Weather words in a report are not a request to inspect external reality.
    Unknown domains remain ``None`` so the existing non-weather router can
    continue handling todos, files, research and news during 7C migration.
    """
    text = (text or "").strip()
    if not text or not _WEATHER_DOMAIN_RE.search(text):
        return None
    if _NON_LOOKUP_FRAME_RE.search(text):
        return "chat"
    if _WEATHER_LOOKUP_RE.search(text):
        return "weather"
    if speech_act in ("information_question", "request") and re.search(r"[？?吗么嘛]$", text):
        return "weather"
    return "chat"


def _understanding(text, situation, signals):
    kind = situation.get("kind") or "general"
    speech_act = _speech_act(text, situation, signals)
    required = speech_act in ("information_question", "request")
    if required:
        obligation = "required"
    elif kind in _LOW_INFORMATION or kind == "goodbye":
        obligation = "none"
    else:
        obligation = "optional"
    topic = situation.get("topic")
    if not topic or topic == "无":
        topic = None
    limits = list(communication_limits(text))
    if _COMMUNICATION_BOUNDARY_RE.search(text or ""):
        limits.append("no_lecture")
    prior_reference = None
    if re.search(r"(?:刚才|刚刚|之前|上次|还记得|这事|这件事|那件事|你说的)", text or ""):
        prior_reference = "recent_conversation"
    explicit = ((text or "").strip(),) if (text or "").strip() else ()
    return TurnUnderstanding(
        speech_act=speech_act,
        answer_obligation=obligation,
        topic=topic,
        topic_shift=bool(signals.get("topic_shift")),
        user_emotion=situation.get("emotion"),
        emotion_confidence=1.0 if situation.get("emotion") else 0.0,
        requires_grounding=required,
        communication_limit=",".join(dict.fromkeys(limits)) if limits else None,
        prior_reference=prior_reference,
        explicit_facts=explicit,
        uncertain_inferences=(),
        unsupported_claim_risks=(
            "unspoken_completion_or_result",
            "physical_or_emotional_effect",
            "cause_or_motive",
            "unseen_scene_detail",
            "unsupported_shared_history",
        ),
        route_action=route_action(text, speech_act),
    )


def understand_turn(text, state=None):
    """Build the shared, prompt-independent understanding used by routing and planning."""
    situation = classify_situation(text, state)
    signals = interaction_signals(situation, text, state)
    return _understanding(text, situation, signals)


def _character_frame(conv_state, char_state, relationship, mood, situation):
    rel_values = getattr(relationship, "values", {}) or {}
    familiarity = float(rel_values.get("familiarity", 0.35))
    willingness = float(getattr(mood, "willingness", 0.7))
    patience = float(getattr(mood, "patience", 0.7))
    attention = situation.get("topic")
    if not attention or attention == "无":
        attention = getattr(conv_state, "last_topic", None)
    if attention == "无":
        attention = None
    open_threads = getattr(conv_state, "open_threads", ()) or ()
    if isinstance(open_threads, dict):
        open_threads = tuple(str(key) for key in open_threads)
    else:
        open_threads = tuple(str(item) for item in open_threads)
    return CharacterFrame(
        emotion=situation.get("emotion") or getattr(conv_state, "last_emotion", None),
        emotion_intensity=float(situation.get("emotion_intensity") or 0.0),
        emotion_source_turn=None,
        emotion_hold_turns=0,
        attention_topic=attention,
        open_threads=open_threads,
        willingness=willingness,
        patience=patience,
        initiative_budget=max(0.0, min(1.0, (willingness + patience) / 2.0)),
        relationship_distance=max(0.0, min(1.0, 1.0 - familiarity)),
    )


def _policy(understanding, authority, behavior, posture="neutral", care_followup_optional=False):
    if posture == "care":
        return TurnPolicy(
            act="soothe",
            focus=("current_input",),
            answer_depth="brief",
            max_speech_units=2,
            followup="optional" if care_followup_optional else "forbidden",
            self_expression="none",
            utterance_shape="conversational",
            emotion_expression="visible",
            allow_silence=False,
            must_preserve_facts=False,
            reason_codes=("posture:care",),
        )
    if posture == "repair":
        return TurnPolicy(
            act="repair",
            focus=("current_input",),
            answer_depth="brief",
            max_speech_units=2,
            followup="optional",
            self_expression="none",
            utterance_shape="conversational",
            emotion_expression="visible",
            allow_silence=False,
            must_preserve_facts=False,
            reason_codes=("posture:repair",),
        )
    obligation = understanding.answer_obligation
    continuation = authority.get("continuation") or "low"
    if obligation == "required":
        act, depth, units, silence = "answer", "normal", 3, False
    elif understanding.speech_act == "relationship_feedback":
        act, depth, units, silence = "repair", "normal", 2, False
    elif understanding.speech_act == "correction":
        act, depth, units, silence = "repair", "brief", 2, False
    elif understanding.speech_act == "boundary":
        act, depth, units, silence = "acknowledge", "brief", 1, False
    elif understanding.speech_act == "goodbye":
        act, depth, units, silence = "close", "brief", 1, False
    elif understanding.speech_act in ("tease", "playful_probe"):
        act, depth, units, silence = "tease", "brief", 2, False
    elif obligation == "none":
        act, depth, units, silence = "react", "brief", 1, True
    else:
        act, depth, units, silence = "react", "brief", 2, False
    followup = "optional" if continuation in ("medium", "high") else "forbidden"
    if (understanding.speech_act == "relationship_feedback"
            and understanding.prior_reference == "recent_conversation"):
        # When the referenced line is not visible, one natural clarification is
        # more human than a generic apology or an invented self-diagnosis.
        followup = "optional"
    elif understanding.user_emotion == "concerned":
        # One clarification about the present problem is allowed; this is not
        # an invitation to keep chatting or an assumption of another request.
        followup = "optional"
    if understanding.speech_act in ("social_question", "relationship_feedback"):
        self_expression = "brief"
    elif behavior in ("自我表达", "主动话题"):
        self_expression = "brief"
    else:
        self_expression = "none"
    if obligation == "required":
        utterance_shape = "complete"
    elif act in ("tease", "close"):
        utterance_shape = "fragment_ok"
    elif (act == "react" and understanding.user_emotion in
          ("surprised", "embarrassed", "amused", "relieved", "annoyed", "touched")):
        utterance_shape = "fragment_ok"
    else:
        utterance_shape = "conversational"
    emotion_expression = "visible" if behavior in ("关心", "冲突与反击", "犹豫·脆弱") else "subtle"
    focus = ("answer",) if obligation == "required" else ("current_input",)
    return TurnPolicy(
        act=act,
        focus=focus,
        answer_depth=depth,
        max_speech_units=units,
        followup=followup,
        self_expression=self_expression,
        utterance_shape=utterance_shape,
        emotion_expression=emotion_expression,
        allow_silence=silence and obligation != "required",
        must_preserve_facts=obligation == "required",
        reason_codes=("legacy:%s" % behavior, "authority:%s" % continuation),
    )


def plan_shadow_turn(text, conv_state, char_state, relationship, mood,
                     situation=None, signals=None, authority=None,
                     emotion=None, emotion_intensity=0.0, tone_priority=False,
                     tone_priority_v2=False):
    """Return one stable shadow plan without mutating any supplied state."""
    if tone_priority and tone_priority_v2:
        raise ValueError("tone_priority_v1 and tone_priority_v2 cannot both be enabled")
    situation = dict(situation or classify_situation(text, conv_state))
    situation["emotion"] = emotion if emotion is not None else situation.get(
        "emotion", getattr(conv_state, "last_emotion", None))
    situation["emotion_intensity"] = float(emotion_intensity or 0.0)
    signals = dict(signals or interaction_signals(situation, text, conv_state))
    authority = dict(authority or response_authority(signals, situation))
    posture = "neutral"
    tone_on = bool(tone_priority or tone_priority_v2)
    if tone_on:
        from tone_priority import posture_for
        posture, evidence = posture_for(text, situation, signals,
                                        state=conv_state, boundary=hits_boundary(text))
        if posture != "neutral":
            signals["posture"] = posture
            signals["posture_evidence"] = list(evidence)
    if tone_on and posture in ("care", "repair"):
        behavior = {"care": "关心", "repair": "认真"}[posture]
        weights = weights_for(situation, char_state, relationship, mood)
    else:
        behavior, weights = decide(situation, conv_state, char_state, relationship, mood,
                                   rng=_stable_rng(text))
    understanding = _understanding(text, situation, signals)
    return ShadowTurn(
        understanding=understanding,
        character_frame=_character_frame(conv_state, char_state, relationship, mood, situation),
        policy=_policy(understanding, authority, behavior,
                       posture=posture if tone_on else "neutral",
                       care_followup_optional=tone_priority_v2),
        legacy_behavior=behavior,
        legacy_projection={
            "situation": situation,
            "signals": signals,
            "authority": authority,
            "weights": weights,
        },
    )


def append_turn_trace(path, channel, text, shadow_turn):
    """Append a bounded JSONL trace. Failure must never block a reply."""
    if not path:
        return False
    try:
        entry = {
            "schema": "7a1-shadow-v1",
            "t": time.strftime("%Y-%m-%d %H:%M:%S"),
            "channel": channel,
            "user_preview": (text or "")[:120],
            **shadow_turn.as_dict(),
        }
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        lines = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[-512:]))
        return True
    except Exception:
        return False


def observe_shadow_turn(path, channel, text, conv_state, char_state, relationship, mood,
                        situation=None, signals=None, authority=None,
                        emotion=None, emotion_intensity=0.0, tone_priority=False,
                        tone_priority_v2=False):
    """Plan and trace without allowing shadow failures onto the reply path."""
    try:
        turn = plan_shadow_turn(
            text, conv_state, char_state, relationship, mood,
            situation=situation, signals=signals, authority=authority,
            emotion=emotion, emotion_intensity=emotion_intensity,
            tone_priority=tone_priority, tone_priority_v2=tone_priority_v2)
        append_turn_trace(path, channel, text, turn)
        return turn
    except Exception:
        return None


_SECOND_SEGMENT_SIMPLE_RE = re.compile(
    r"^(?:嗯+|哦+|噢+|好(?:的)?|行(?:吧)?|可以|知道了|收到|算了|没事|"
    r"……+|\.{2,}|…+|[？?！!。…~～\s]+)$")


def _segment_roll(text):
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def second_segment_probability(understanding, policy, first_reply):
    """Content-related probability (0..0.60) for appending one more segment."""
    text = (first_reply or "").strip()
    if understanding is None or policy is None or not text:
        return 0.0
    if getattr(understanding, "answer_obligation", None) == "required":
        return 0.0
    if getattr(policy, "must_preserve_facts", False):
        return 0.0
    try:
        units = int(getattr(policy, "max_speech_units", 1) or 1)
    except (TypeError, ValueError):
        units = 1
    if units < 2:
        return 0.0
    if len(text) <= 12 or _SECOND_SEGMENT_SIMPLE_RE.fullmatch(text):
        return 0.0
    depth = getattr(policy, "answer_depth", "brief")
    base = {"brief": 0.15, "normal": 0.30, "detailed": 0.50}.get(depth, 0.0)
    if base <= 0:
        return 0.0
    probability = base
    if getattr(policy, "self_expression", "none") != "none":
        probability += 0.10
    if len(text) >= 40:
        probability += 0.10
    if len([part for part in re.split(r"[。！？!?…]+", text) if part.strip()]) >= 2:
        probability += 0.10
    return min(0.60, probability)


def should_append_second_segment(understanding, policy, first_reply, roll=None):
    """Pure decision; stable by default via a SHA-256 roll over first_reply."""
    probability = second_segment_probability(understanding, policy, first_reply)
    if probability <= 0:
        return False
    if roll is None:
        draw = _segment_roll(first_reply)
    else:
        try:
            draw = float(roll)
        except (TypeError, ValueError):
            return False
    return draw < probability
