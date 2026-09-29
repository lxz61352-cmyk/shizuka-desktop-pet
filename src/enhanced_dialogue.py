# -*- coding: utf-8 -*-
"""enhanced_v2 candidate assembly (P4.1, offline implementation).

Frozen candidate = D stack minus the model-visible missing_prior_context block:
S1 v2 assembly + S2 candidate persona + Hard Contract v2 + Interaction Frame +
four semantics contracts + timestamp sanitization + named memory/tool receipts
+ Output Contract. No legacy behavior blocks; the visibility diagnostic goes to
internal diagnostics only; the switch defaults off and off keeps production
byte-identical.
"""
import hashlib
import json
import os
from pathlib import Path

SWITCH_KEY = "enhanced_dialogue_v2"
ROOT = Path(__file__).resolve().parents[1]
ENHANCED_CARD = ROOT / "characters" / "shizuka-side-motion" / "persona.enhanced.json"
HARD_CONTRACT_FILE = Path(__file__).resolve().parent / "enhanced_hard_contract_v2.txt"


class EnhancedSwitchError(ValueError):
    """enhanced_dialogue_v2 combined with an eliminated switch."""


def resolve_enhanced_switch(tone_v1, tone_v2, guard, arch_v2, enhanced):
    if enhanced and (tone_v1 or tone_v2 or guard or arch_v2):
        raise EnhancedSwitchError(
            "enhanced_dialogue_v2 cannot be combined with tone_priority_v1/v2, "
            "tone_local_guard_v1 or dialogue_architecture_v2")
    return bool(enhanced)


def channel_mode(engine, channel):
    """Enhanced mode per channel; session-only desktop gray runs keep weixin old."""
    enabled = bool(getattr(engine, "ENHANCED_MODE", False))
    if channel == "weixin" and bool(getattr(engine, "ENHANCED_DESKTOP_ONLY", False)):
        return False
    return enabled


def hard_contracts():
    return HARD_CONTRACT_FILE.read_text(encoding="utf-8").strip()


def persona_core(pack=None):
    from dialogue_architecture_v2 import persona_core as base_persona_core
    return base_persona_core(str(ENHANCED_CARD), pack)


def output_blocks(text, history, *, natural_chat=False, actor_names=('静香',), outer_variant='baseline'):
    """Frame + four contracts + Output Contract, in frozen order."""
    import interaction_frame
    from dialogue_architecture_v2 import output_contract
    frame = interaction_frame.build_interaction_frame(text, history=history, actor_names=actor_names)
    if natural_chat is True:
        from dialogue_mode import reply_frame
        frame = reply_frame(frame, natural_chat=True)
    frame_text = interaction_frame.render_interaction_frame(frame)
    contract = interaction_frame.contract_text()
    from outer_dialogue_trial import render_blocks
    return render_blocks(frame_text, contract, output_contract(), outer_variant), frame


def compose_messages(persona, text, history, *, capabilities='', context_blocks=(), timeline='',
                     natural_chat=True, actor_names=('静香',), outer_variant='no_frame', sensitive_topics=False):
    """Same ordering for the selected production profile and text experiments.

    Channels provide only their actual capabilities/receipts and selected data;
    they do not supply another speaking-style layer.
    """
    from copy import deepcopy
    output,_=output_blocks(text,history,natural_chat=natural_chat,actor_names=actor_names,outer_variant=outer_variant)
    from sensitive_topics import policy
    blocks=[persona,hard_contracts(),capabilities,*context_blocks,policy(sensitive_topics),output,timeline]
    return [{'role':'system','content':'\n\n'.join(block for block in blocks if block)}]+deepcopy(history)+[{'role':'user','content':text}]


def diagnostics(text, history):
    """Model-invisible diagnostics (missing_prior_context moved here)."""
    import shizuka_fact_grounding
    note = shizuka_fact_grounding.missing_prior_context_note(text, history)
    from interaction_frame import contract_text
    return {
        "missing_prior_context_present": bool(note),
        "missing_prior_context_chars": len(note or ""),
        "contract_sha256": hashlib.sha256(contract_text().encode("utf-8")).hexdigest(),
    }


def log_diagnostics(record, path=None):
    try:
        target = Path(path) if path else _default_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except Exception:
        return False


def _default_log_path():
    data_dir = os.environ.get("SHIZUKA_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "enhanced_diagnostics.jsonl"
    return ROOT / "data" / "enhanced_diagnostics.jsonl"
