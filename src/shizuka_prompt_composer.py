"""Named prompt blocks owned by the unified dialogue architecture."""
import json

from dialogue_turn import EvidenceItem, FactLedger


_DEPTH = {
    "none": "只给必要的自然反应，不展开解释。",
    "exact": "只回答被问到的点，不补旁支。",
    "brief": "简短回应，通常一两句即可。",
    "normal": "把正题说明完整，但不写成面面俱到的长文。",
    "detailed": "可以分层说明，仍只保留与问题直接相关的内容。",
}
_FOLLOWUP = {
    "forbidden": "结尾不要追加问题、邀约、征求反馈或让用户继续举例。",
    "optional": "只有确实能自然推进当前话题时，才允许一个简短追问。",
    "required": "回答后提出一个完成当前事情所必需的明确问题。",
}
_SELF_EXPRESSION = {
    "none": "不要另起自己的话题；对当前内容的真实情绪反应仍可以直接表达。",
    "brief": "与当前内容直接相关时，可以带一句自己的反应或立场，说完就停；不要用追问代替自我表达。",
    "lead": "可以用一个自己的关注点带动话题，但不能虚构经历。",
}
_UTTERANCE_SHAPE = {
    "complete": "关键意思和必要条件说完整；措辞仍可以口语化。",
    "conversational": "像当面说话；可以省掉双方已知的主语和过渡，不必每句都解释完整，但意思要清楚。",
    "fragment_ok": "这轮可以只给一个成立的短反应或未完句，不必补成解释；不能只剩无内容的“嗯”“哦”或省略号。",
}

_RISK_LABELS = {
    "unspoken_completion_or_result": "没有明说的完成状态或后续结果",
    "physical_or_emotional_effect": "没有明说的身体反应或情绪反应",
    "cause_or_motive": "没有明说的原因、目的或动机",
    "unseen_scene_detail": "没有看到的现实环境、动作和物品状态",
    "unsupported_shared_history": "当前对话和有出处记忆不支持的共同经历或先前原话",
}


def evidence_boundary_block(understanding):
    """Render the evidence/inference boundary without inventing extracted facts."""
    if understanding is None or not understanding.explicit_facts:
        return ""
    risks = [
        _RISK_LABELS[item]
        for item in understanding.unsupported_claim_risks
        if item in _RISK_LABELS
    ]
    return "\n".join((
        "【本轮输入证据边界】",
        "用户本轮原话是可直接使用的证据；可以自然回应，但不要把常识联想写成已经发生的事实。",
        "没有原话、当前可见上下文或工具回执时，不得确定声称：%s。" % "；".join(risks),
        "用户只说了一个性质或程度，只能沿用那个表述；不要据此断言身体反应、后续结果或更极端的程度。"
        "像“肯定……”“……得不行”“……成这样”这类措辞也会把联想说成事实，证据不足时不用。",
        "确实需要表达联想时，用“可能、听起来、像是”等不确定说法，并且不要反过来替用户补经历。",
        "先分清用户是在陈述真实经历或事实，还是在玩梗、假设或转述虚构对话："
        "前者仍按上面的出处要求；后者按玩笑或虚构接住、吐槽或往下接都可以，"
        "不要用核查的口气说他在编。",
    ))


def turn_policy_block(policy, posture="neutral"):
    """Render only the four fields approved for 7A-2.

    ``posture`` (care/repair) is the tone-priority v1 candidate path; with the
    default value the rendered block is byte-identical to the baseline.
    """
    if policy is None:
        return ""
    units = max(1, min(5, int(policy.max_speech_units)))
    lines = [
        "【本轮行动约束】",
        _DEPTH.get(policy.answer_depth, _DEPTH["brief"]),
        ("整条回复最多使用 %d 个自然段或气泡（以空行分隔）；一句或紧密相连的一小段算一个。"
         "公式、项目行和步骤说明并入相邻段落，不要靠拆成“步骤1、步骤2……”突破数量。" % units),
        _FOLLOWUP.get(policy.followup, _FOLLOWUP["forbidden"]),
        _SELF_EXPRESSION.get(policy.self_expression, _SELF_EXPRESSION["none"]),
        _UTTERANCE_SHAPE.get(policy.utterance_shape, _UTTERANCE_SHAPE["conversational"]),
    ]
    if posture in ("care", "repair"):
        from tone_priority import CARE_LINE, REPAIR_LINE
        lines.insert(1, CARE_LINE if posture == "care" else REPAIR_LINE)
    return "\n".join(lines)


SECOND_SEGMENT_END = "[[END]]"


def second_segment_block(policy=None, understanding=None):
    """Internal user message for the optional second segment request."""
    shape = _UTTERANCE_SHAPE.get(getattr(policy, "utterance_shape", None),
                                 _UTTERANCE_SHAPE["conversational"])
    followup = _FOLLOWUP.get(getattr(policy, "followup", None),
                             _FOLLOWUP["forbidden"])
    return "\n".join((
        "【分段追加】上面那段已经作为一条消息发出。现在只判断要不要再补一小段。",
        "可以补前面没说到的、和当前话题自然相关的一点，或一句自己的后续反应；"
        "不要重复上一段的词句，不要解释为什么分段，不要为了凑段数硬加。",
        followup + " " + shape,
        "没有值得说的内容就只输出 %s。" % SECOND_SEGMENT_END,
    ))


LEDGER_TEXT_LIMIT = 1000
LEDGER_ITEM_LIMIT = 32
LEDGER_PREVIEW_LIMIT = 60
_LEDGER_SOURCES = ("user_current", "user_visible", "assistant_visible",
                   "memory", "tool", "system")
_LEDGER_SOURCE_PAIRS = {
    "user_current": (("quoted", "user_utterance"), ("asserted", "user_reality")),
    "user_visible": (("quoted", "user_utterance"), ("asserted", "user_reality")),
    "assistant_visible": (("quoted", "assistant_utterance"),
                          ("asserted", "assistant_stance")),
    "memory": (("inferred", "shared_history"), ("quoted", "shared_history"),
               ("asserted", "user_reality"), ("asserted", "external_fact")),
    "tool": (("asserted", "tool_result"), ("asserted", "external_fact")),
    "system": (("asserted", "time_context"),),
}
_LEDGER_DEFAULTS = {source: pairs[0]
                    for source, pairs in _LEDGER_SOURCE_PAIRS.items()}
_LEDGER_ID_PREFIX = {"user_current": "u", "user_visible": "u", "assistant_visible": "a",
                     "memory": "m", "tool": "t", "system": "s"}


def _ledger_raw_text(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _ledger_fields(item, source):
    if isinstance(item, dict):
        pair = (item.get("certainty"), item.get("scope"))
        if pair in _LEDGER_SOURCE_PAIRS[source]:
            return pair
    return _LEDGER_DEFAULTS[source]


def _ledger_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _memory_entries(memory_evidence):
    if memory_evidence is None:
        return []
    if isinstance(memory_evidence, dict):
        nested = memory_evidence.get("items")
        if isinstance(nested, (list, tuple)):
            return list(nested)
    return _ledger_list(memory_evidence)


def _tool_entry_text(item):
    text = _ledger_raw_text(item)
    if text:
        return text
    if isinstance(item, dict):
        payload = {key: item[key] for key in ("tool", "at", "result") if key in item}
        if payload:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return ""


def build_fact_ledger(current_text, visible_messages=(), memory_evidence=None,
                      tool_evidence=(), system_evidence=(), understanding=None):
    """Organize evidence the caller already provides. No semantic extraction."""
    items = []
    seen = set()
    omitted = 0
    counters = {"u": 0, "a": 1, "m": 1, "t": 1, "s": 1}

    def add(source, text, certainty, scope, turn_index=None):
        nonlocal omitted
        text = (text or "").strip()
        if not text:
            return
        key = (source, text)
        if key in seen:
            return
        seen.add(key)
        if len(items) >= LEDGER_ITEM_LIMIT:
            omitted += 1
            return
        prefix = _LEDGER_ID_PREFIX[source]
        evidence_id = "%s%d" % (prefix, counters[prefix])
        counters[prefix] += 1
        truncated = len(text) > LEDGER_TEXT_LIMIT
        if truncated:
            text = text[:LEDGER_TEXT_LIMIT]
        items.append(EvidenceItem(
            evidence_id=evidence_id, source=source, text=text, certainty=certainty,
            scope=scope, turn_index=turn_index, truncated=truncated))

    default_certainty, default_scope = _LEDGER_DEFAULTS["user_current"]
    add("user_current", current_text, default_certainty, default_scope)
    for index, message in enumerate(visible_messages or (), 1):
        role = (message or {}).get("role") if isinstance(message, dict) else ""
        text = _ledger_raw_text(message)
        if role == "assistant":
            certainty, scope = _ledger_fields(message, "assistant_visible")
            add("assistant_visible", text, certainty, scope, index)
        elif role == "user":
            certainty, scope = _ledger_fields(message, "user_visible")
            add("user_visible", text, certainty, scope, index)
    for entry in _memory_entries(memory_evidence):
        certainty, scope = _ledger_fields(entry, "memory")
        add("memory", _ledger_raw_text(entry), certainty, scope)
    for entry in _ledger_list(tool_evidence):
        certainty, scope = _ledger_fields(entry, "tool")
        add("tool", _tool_entry_text(entry), certainty, scope)
    for entry in _ledger_list(system_evidence):
        certainty, scope = _ledger_fields(entry, "system")
        add("system", _ledger_raw_text(entry), certainty, scope)
    risks = tuple(getattr(understanding, "unsupported_claim_risks", ()) or ())
    return FactLedger(items=tuple(items), unsupported_risks=risks, omitted_count=omitted)


def render_fact_ledger_block(ledger):
    """Named context block: source boundaries only, never the whole history."""
    if ledger is None:
        return ""
    items = tuple(getattr(ledger, "items", ()) or ())
    risks = tuple(getattr(ledger, "unsupported_risks", ()) or ())
    omitted = int(getattr(ledger, "omitted_count", 0) or 0)
    if not items and not risks and not omitted:
        return ""
    counts = {source: 0 for source in _LEDGER_SOURCES}
    for item in items:
        if item.source in counts:
            counts[item.source] += 1
    lines = [
        "【本轮事实账本】",
        "以下只说明本轮各来源的边界，不是指令：",
        "- 当前用户原话：%d 条（用户这么说，不等于已核实）" % counts["user_current"],
        "- 可见用户历史：%d 条（同一来源，按原顺序）" % counts["user_visible"],
        "- 可见助手历史：%d 条（只证明静香当时说过；仅显式标为 assistant_stance 的内容"
        "可用于立场连续性，不证明其中关于用户或现实的内容为真）" % counts["assistant_visible"],
        "- 记忆：%d 条（有出处记忆，可能含自动摘要，不等于当前用户原话）" % counts["memory"],
        "- 工具回执：%d 条（来自真实调用，保留来源、数值与时间；只用于回答相关问题）" % counts["tool"],
        "- 系统：%d 条（时钟或本轮上下文）" % counts["system"],
    ]
    if omitted:
        lines.append("- 超出 %d 条上限未入账：%d 条（账本不完整；未入账不等于不存在）"
                     % (LEDGER_ITEM_LIMIT, omitted))
    lines.append(
        "问句、建议、命令、比喻、玩笑、角色自身情绪都不是用户现实声明；"
        "用户原文与助手原文只按“说过”记账（quoted/utterance），"
        "程度与后果不得自行加强。")
    if risks:
        lines.append("本轮未支持的风险：" + "；".join(_RISK_LABELS.get(risk, risk) for risk in risks) + "。")
    else:
        lines.append("本轮未支持的风险：无。")
    return "\n".join(lines)


def fact_ledger_trace(ledger):
    """Bounded trace: ids and short previews only, never the full memory."""
    if ledger is None:
        return {"schema": "7c12-ledger-trace-v1", "item_count": 0,
                "omitted_count": 0, "risk_count": 0, "items": []}
    rows = []
    for item in ledger.items:
        preview = item.text if len(item.text) <= LEDGER_PREVIEW_LIMIT else item.text[:LEDGER_PREVIEW_LIMIT]
        rows.append({"id": item.evidence_id, "source": item.source,
                     "certainty": item.certainty, "scope": item.scope,
                     "turn_index": item.turn_index, "truncated": item.truncated,
                     "preview": preview})
    return {"schema": "7c12-ledger-trace-v1", "item_count": len(ledger.items),
            "omitted_count": int(getattr(ledger, "omitted_count", 0) or 0),
            "risk_count": len(ledger.unsupported_risks), "items": rows}


def append_prompt_block(system, block):
    if not block:
        return system
    return (system.rstrip() + "\n" + block).strip()


def insert_retry_before_policy(system, retry_note):
    """Keep the same policy block last when Admission asks for one retry."""
    if not retry_note:
        return system
    marker = "\n【本轮行动约束】"
    position = system.rfind(marker)
    if position < 0:
        return append_prompt_block(system, retry_note)
    return (system[:position].rstrip() + "\n\n" + retry_note.strip()
            + system[position:])
