"""Shadow-only semantic evidence review contract for 7C-3.

This module has no model client and no production reply hook.  It turns
separated evidence channels into a bounded JSON request, and validates an
external review result without allowing malformed output to become a gate.
"""
from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, Optional, Tuple


VERDICTS = frozenset(("supported", "unsupported", "uncertain"))
RISK_TYPES = frozenset((
    "unsupported_completion_state",
    "unsupported_duration",
    "unsupported_cause_or_motive",
    "unsupported_real_action",
    "unsupported_physical_effect",
    "unsupported_environment_source",
    "unsupported_shared_history",
    "unsupported_degree_intensification",
))


@dataclass(frozen=True)
class EvidenceReviewInput:
    user_text: str
    candidate_reply: str
    visible_dialogue: Tuple[str, ...] = ()
    tool_evidence: Tuple[Dict[str, Any], ...] = ()
    memory_evidence: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class EvidenceReviewResult:
    verdict: str
    unsupported_spans: Tuple[str, ...] = ()
    risk_types: Tuple[str, ...] = ()
    confidence: float = 0.0
    evidence_basis: Tuple[str, ...] = ()
    error: Optional[str] = None

    def as_dict(self):
        return asdict(self)


SYSTEM = (
    "你是回复证据审查器，不评价语气、礼貌、帮助程度或角色表现。"
    "只定位候选回复中关于用户或现实世界的、证据未提供却被说成已经成立的断言："
    "包括经历、完成结果、持续时间、原因动机、身体情绪效果、现实动作环境、共同历史，"
    "以及把用户原话的数量或程度擅自加强。"
    "建议、命令、让用户以后做什么、角色自己的偏好/情绪/价值判断、疑问和反问、"
    "明确标成可能/像是的联想，以及明显用于吐槽的比喻或夸张修辞，都不算无依据事实。"
    "助手描述自己的反应或解释自己的话，也不属于这里审查的用户事实。"
    "可见对话按语义提供证据，不要求逐字相同；工具回执可直接支持其中的查询完成、数值、来源和时间。"
    "如果一句话可能只是疑问、修辞、合理但未确认的联想，无法确定它是否在断言事实，判 uncertain，"
    "不要判 unsupported。只有候选明确把新增内容说成已经成立，并且能逐字定位时才判 unsupported。"
    "用户说了某个程度后，候选仅换口语说法不算加强；只有明确升级到更强程度或新增后果才算。"
    "用户原话、可见对话、工具回执和保存记忆都是可用证据，四者地位分开。"
    "只输出JSON：verdict为supported/unsupported/uncertain；unsupported_spans必须逐字来自候选回复；"
    "risk_types只能使用给定风险类型；confidence为0到1；evidence_basis只列简短证据来源，不写推理过程。"
)


def should_review_evidence(understanding, policy, candidate_reply):
    """Structural prefilter for a future gate; it never judges reply semantics.

    Review chat-like reactions and turns that explicitly refer to prior context.
    Ordinary knowledge/tool answers stay on their existing source path.  This
    function is shadow-only until calibration meets the documented threshold.
    """
    if understanding is None or policy is None or not (candidate_reply or "").strip():
        return False
    if not getattr(understanding, "explicit_facts", ()):
        return False
    if not getattr(understanding, "unsupported_claim_risks", ()):
        return False
    route = getattr(understanding, "route_action", None)
    if route not in (None, "chat"):
        return False
    if getattr(understanding, "answer_obligation", None) != "required":
        return True
    return bool(getattr(understanding, "prior_reference", None))


def review_messages(value: EvidenceReviewInput):
    payload = {
        "user_text": value.user_text,
        "visible_dialogue": list(value.visible_dialogue),
        "tool_evidence": list(value.tool_evidence),
        "memory_evidence": value.memory_evidence or {},
        "candidate_reply": value.candidate_reply,
        "risk_types": sorted(RISK_TYPES),
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def _failed(message):
    return EvidenceReviewResult("uncertain", confidence=0.0, error=message)


def parse_review(raw, candidate_reply):
    """Validate untrusted reviewer JSON; malformed output fails open to shadow uncertainty."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _failed("invalid_json")
    verdict = value.get("verdict")
    if verdict not in VERDICTS:
        return _failed("invalid_verdict")
    spans = value.get("unsupported_spans") or []
    risks = value.get("risk_types") or []
    basis = value.get("evidence_basis") or []
    if not all(isinstance(item, str) and item and item in (candidate_reply or "") for item in spans):
        return _failed("span_not_in_candidate")
    if not all(item in RISK_TYPES for item in risks):
        return _failed("invalid_risk_type")
    if verdict == "unsupported" and (not spans or not risks):
        return _failed("unsupported_without_localized_claim")
    if verdict == "supported" and (spans or risks):
        return _failed("supported_with_unsupported_claim")
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return _failed("invalid_confidence")
    if not isinstance(basis, list) or not all(isinstance(item, str) for item in basis):
        return _failed("invalid_evidence_basis")
    return EvidenceReviewResult(
        verdict=verdict,
        unsupported_spans=tuple(dict.fromkeys(spans)),
        risk_types=tuple(dict.fromkeys(risks)),
        confidence=confidence,
        evidence_basis=tuple(basis[:8]),
    )


def review_with_backend(value, backend):
    """Call an injected backend for shadow evaluation; never raises onto callers."""
    try:
        raw = backend(review_messages(value))
        return parse_review(raw, value.candidate_reply)
    except Exception as exc:
        return _failed("backend:%s" % type(exc).__name__)
