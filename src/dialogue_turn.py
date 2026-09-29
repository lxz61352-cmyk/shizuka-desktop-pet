"""Unified, prompt-independent records for one dialogue turn.

7A-1 introduces these records as shadow data only.  They deliberately contain
no rendered prompt text, UI objects, or model-client state.
"""
from dataclasses import asdict, dataclass, field
from typing import Dict, Literal, Optional, Tuple


@dataclass(frozen=True)
class TurnUnderstanding:
    speech_act: str
    answer_obligation: str
    topic: Optional[str]
    topic_shift: bool
    user_emotion: Optional[str]
    emotion_confidence: float
    requires_grounding: bool
    communication_limit: Optional[str]
    prior_reference: Optional[str]
    explicit_facts: Tuple[str, ...] = ()
    uncertain_inferences: Tuple[str, ...] = ()
    unsupported_claim_risks: Tuple[str, ...] = ()
    route_action: Optional[str] = None


@dataclass(frozen=True)
class CharacterFrame:
    emotion: Optional[str]
    emotion_intensity: float
    emotion_source_turn: Optional[int]
    emotion_hold_turns: int
    attention_topic: Optional[str]
    open_threads: Tuple[str, ...]
    willingness: float
    patience: float
    initiative_budget: float
    relationship_distance: float


@dataclass(frozen=True)
class TurnPolicy:
    act: str
    focus: Tuple[str, ...]
    answer_depth: str
    max_speech_units: int
    followup: str
    self_expression: str
    utterance_shape: str
    emotion_expression: str
    allow_silence: bool
    must_preserve_facts: bool
    reason_codes: Tuple[str, ...]


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source: Literal["user_current", "user_visible", "assistant_visible",
                    "memory", "tool", "system"]
    text: str
    certainty: Literal["asserted", "quoted", "inferred"]
    scope: Literal["user_utterance", "assistant_utterance", "user_reality",
                   "external_fact", "shared_history", "assistant_stance",
                   "tool_result", "time_context"]
    turn_index: Optional[int]
    truncated: bool = False


@dataclass(frozen=True)
class FactLedger:
    items: Tuple[EvidenceItem, ...]
    unsupported_risks: Tuple[str, ...]
    omitted_count: int = 0


@dataclass(frozen=True)
class ShadowTurn:
    understanding: TurnUnderstanding
    character_frame: CharacterFrame
    policy: TurnPolicy
    legacy_behavior: str
    legacy_projection: Dict[str, object] = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)
