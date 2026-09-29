"""Small, source-grounded context shared by desktop and Weixin chat.

Repeated wording is evidence of familiarity, not a stored user motive or a
script for the next reply. Only prior user chat messages can supply evidence.
"""
from datetime import datetime
from collections import Counter
import re
import time


CHAT_KINDS = {"chat", "user", "weixin"}
SHORT_NUMBER = re.compile(r"[0-9０-９]{1,4}\Z")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
NO_ADVICE = re.compile(r"(?:不需要|不必|无需|不用|不要|别)(?:再)?(?:你)?(?:给(?:我)?|向我)?(?:任何|什么)?建议")
NO_ANALYSIS = re.compile(r"(?:不需要|不必|无需|不用|不要|别)(?:再)?(?:你)?分析(?:我|原因|为什么)?")
NO_QUESTIONS = re.compile(r"(?:不需要|不必|无需|不用|不要|别)(?:再)?(?:你)?(?:追问|问我)")
POSITIVE_REQUEST_AFTER = re.compile(r"(?:但|不过|然后|现在).{0,10}(?:帮我|告诉我|解释|给我讲)")
COMMON_CUES = {
    "今天", "昨天", "现在", "什么", "怎么", "觉得", "我们", "你们", "那个", "这个",
    "可以", "一下", "帮我", "给我", "还有", "然后", "就是", "一个", "已经",
    "最近", "真的", "没有", "还是", "不是", "知道", "是谁", "来了", "马上",
    "自己", "时候", "东西", "的话", "这里", "那里", "这么", "这样", "那样",
    "一条", "一件", "一种", "一次", "一点", "一位", "一个",
}
COMMON_HEADS = ("今天", "昨天", "我觉得", "你觉得", "是什么", "为什么", "有没有")
CUE_MIN_CHARS = 2
CUE_MAX_CHARS = 12
FILLER_TAIL = re.compile(
    r"(?:是|的|有|在|和|与|把|被|对|跟|从|给|为|就|都|也|还|又|很|太|不|没|别|让|使)\Z")
QUESTION_OR_REQUEST = re.compile(
    r"(?:为什么|为啥|什么|怎么|如何|多少|哪|是不是|有没有|能不能|可不可以|"
    r"帮我|给我|替我|陪我|告诉我|讲一下|讲下|说一下|说下|解释|请教|请问|"
    r"查一下|查查|想个办法|出个主意|推荐)|(?:吗|呢)\Z")


def communication_limits(text):
    """Return only limits that the user explicitly stated in this turn."""
    text = (text or "").strip()
    limits = []
    for name, pattern in (("no_advice", NO_ADVICE), ("no_analysis", NO_ANALYSIS),
                          ("no_questions", NO_QUESTIONS)):
        if pattern.search(text):
            limits.append(name)
    return tuple(limits)


def has_followup_request(text):
    """A later explicit request should keep task routing, not erase prior limits."""
    return bool(POSITIVE_REQUEST_AFTER.search(text or ""))


def format_communication_limits(limits):
    labels = {"no_advice": "不需要建议", "no_analysis": "不需要分析其原因或心理",
              "no_questions": "不需要追问"}
    selected = [labels[name] for name in limits if name in labels]
    return "【用户本轮明确限定】" + "；".join(selected) + "。" if selected else ""


def _normalize(text):
    return re.sub(r"[^0-9０-９a-zA-Z\u4e00-\u9fff]", "", (text or "").lower())


def _user_rows(rows, current_id=None):
    return [row for row in rows if row.get("role") == "user"
            and row.get("kind", "chat") in CHAT_KINDS
            and row.get("id") != current_id and isinstance(row.get("text"), str)
            and 0 < len(_normalize(row["text"])) <= 64][-2000:]


def _day(timestamp):
    try:
        return datetime.fromtimestamp(float(timestamp)).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _cues(text):
    """Complete user clauses, never arbitrary character n-grams.

    A clause must be a distinguishable expression: question/request setups,
    dangling function-word fragments and generic wording are not evidence.
    Fragments like “是一”“为什”“讲一下”“什么意思” must fail here.
    """
    cues = set()
    for chunk in CHINESE_RUN.findall(text or ""):
        cue = _normalize(chunk)
        if not CUE_MIN_CHARS <= len(cue) <= CUE_MAX_CHARS:
            continue
        if cue in COMMON_CUES or cue.startswith(COMMON_HEADS):
            continue
        if cue[0] in "我你他她这那":
            continue
        if QUESTION_OR_REQUEST.search(cue) or FILLER_TAIL.search(cue):
            continue
        cues.add(cue)
    return sorted(cues, key=lambda cue: (-len(cue), cue))


def _fresh_within(row, current_at, seconds=900):
    try:
        return 0 <= current_at - float(row.get("created")) <= seconds
    except (TypeError, ValueError):
        return False


def interaction_evidence(text, rows, current_id=None, now=None):
    """Find one repeated, short user expression relevant to the current turn.

    Numeric pings may become familiar within a session (a second number in the
    same quarter hour is already a pattern). Other phrases require two earlier
    messages and evidence spanning separate dates, including now.
    Returns None when the evidence is too thin or the input is a long task.
    """
    current = _normalize(text)
    if not current or len(current) > 30:
        return None
    prior = _user_rows(rows, current_id)
    current_at = time.time() if now is None else now
    if SHORT_NUMBER.fullmatch(current):
        numbers = [row for row in prior if SHORT_NUMBER.fullmatch(_normalize(row["text"]))]
        exact = [row for row in numbers if _normalize(row["text"]) == current]
        if len(exact) >= 2:
            return {"kind": "short_number", "cue": current, "count": len(exact),
                    "current_text": text}
        if any(_fresh_within(row, current_at) for row in exact):
            return {"kind": "short_number", "cue": current, "count": len(exact),
                    "current_text": text}
        recent = [row for row in prior[-8:] if SHORT_NUMBER.fullmatch(_normalize(row["text"]))]
        counts = Counter(_normalize(row["text"]) for row in recent)
        last_at = recent[-1].get("created") if recent else None
        try:
            fresh = 0 <= current_at - float(last_at) <= 900
        except (TypeError, ValueError):
            fresh = False
        if fresh and counts and max(counts.values()) >= 2:
            cue = counts.most_common(1)[0][0]
            return {"kind": "short_number_variant", "cue": cue,
                    "count": sum(counts.values()), "current_text": text}
        return None
    if len(prior) < 2:
        return None
    current_day = _day(current_at)
    best = None
    for cue in _cues(text):
        matches = [row for row in prior if cue in _normalize(row["text"])]
        if len(matches) < 2:
            continue
        days = {_day(row.get("created")) for row in matches}
        days.discard(None)
        if current_day is not None:
            days.add(current_day)
        if len(days) < 2:
            continue
        # Prefer a distinctive long phrase over a frequent generic bigram.
        score = (len(cue), -len(matches))
        if best is None or score > best[0]:
            best = (score, cue, len(matches), len(days))
    if best is None:
        return None
    _, cue, count, day_count = best
    return {"kind": "phrase", "cue": cue, "count": count,
            "days": day_count, "current_text": text}


def format_interaction_evidence(evidence):
    """Supply a short observation, never raw historical instructions."""
    if not evidence:
        return ""
    cue = evidence["cue"]
    count = evidence["count"]
    if evidence["kind"] == "short_number_variant":
        return (f"【有出处的相处线索】用户最近多次发过短数字（例如“{cue}”，"
                f"共 {count} 条）；本轮换了数字。这里只能确认重复与变化，不能推断用意。")
    if evidence["kind"] == "short_number":
        return (f"【有出处的相处线索】用户此前已 {count} 次发过“{cue}”这个短数字；"
                "本轮再次出现。这里只能确认重复，不能推断用意。")
    return (f"【有出处的熟悉背景】用户过去确实使用过“{cue}”这一说法。"
            "这只用于理解熟悉感：正常回应本轮内容，不要主动告诉用户他说过几次、哪天说过，"
            "也不要用‘又来了／今天问过／已经说过’替代当前回应；只有用户正在确认记忆或重复本身就是话题时才提。")
