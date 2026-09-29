"""Narrow-scope local guard (Phase 3): fixed replies for two unstable inputs.

Enabled only together with ``tone_priority_v2``. The reply is chosen from the
turn posture before any API request/client is created, then delivered through
the normal final-reply channel.
"""
SWITCH_KEY = "tone_local_guard_v1"

WHIMPER_EVIDENCE = frozenset((
    "whimper_pure",
    "whimper_with_context",
    "whimper_after_posture",
    "whimper_short_complaint",
))

WHIMPER_REPLY = "……怎么了？"
REPAIR_WITH_HISTORY_REPLY = "……刚才那句是有点冲。我说重了。"
REPAIR_NO_HISTORY_REPLY = "哪句？你说，我听着。"

# 日语语音的冻结对应句（本地固定，零请求；不调用 _translate_for_voice）
WHIMPER_REPLY_JA = "……どうしたの？"
REPAIR_WITH_HISTORY_REPLY_JA = "……さっきのは、ちょっときつかった。言い過ぎた。"
REPAIR_NO_HISTORY_REPLY_JA = "どの言葉？話して、聞いてるから。"

_JA_MAP = {
    WHIMPER_REPLY: WHIMPER_REPLY_JA,
    REPAIR_WITH_HISTORY_REPLY: REPAIR_WITH_HISTORY_REPLY_JA,
    REPAIR_NO_HISTORY_REPLY: REPAIR_NO_HISTORY_REPLY_JA,
}


def japanese_for(reply):
    """Frozen Japanese counterpart for a fixed local reply, else None."""
    return _JA_MAP.get(reply)


def resolve_guard(v1_enabled, v2_enabled, guard_enabled):
    """Return whether the local guard is active; invalid mixes fail fast."""
    if guard_enabled and v1_enabled:
        raise ValueError("tone_local_guard_v1 excludes tone_priority_v1")
    if guard_enabled and not v2_enabled:
        raise ValueError("tone_local_guard_v1 requires tone_priority_v2")
    return bool(guard_enabled)


def local_reply_for(posture, evidence, has_assistant):
    """Fixed reply for the two narrow scopes; None keeps the normal path.

    boundary always wins and is never intercepted; other care/neutral/tease/
    opposition/kokona turns keep the original (v2) path.
    """
    if posture == "boundary":
        return None
    if posture == "care":
        if WHIMPER_EVIDENCE.intersection(evidence or ()):
            return WHIMPER_REPLY
        return None
    if posture == "repair":
        return REPAIR_WITH_HISTORY_REPLY if has_assistant else REPAIR_NO_HISTORY_REPLY
    return None
