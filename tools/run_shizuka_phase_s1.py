"""Phase S1: candidate single-owner chain verifier (offline, read-only).

Builds baseline (dialogue_architecture_v2 off) and candidate (on) requests for
8 cases through the real _ask_model / _weixin_reply assembly paths with a fake
provider client. Writes diffs, prompt blocks, postprocessor scope, validation.

Usage:
    python tools/run_shizuka_phase_s1.py
    python tools/run_shizuka_phase_s1.py --check
"""
import argparse
import copy
import hashlib
import json
import random
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for folder in (str(SRC), str(TOOLS)):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import run_shizuka_phase_s0 as s0  # noqa: E402

OUT = ROOT / "测试记录" / "静香-底层拆解-PhaseS1-2026-09-26"
S0_CASES = ROOT / "测试记录" / "静香-底层拆解-PhaseS0-2026-09-26" / "cases.json"

EXTRA_CASES = {
    "case-7-tease": {
        "text": "哈哈，你今天是不是有点呆",
        "history": [
            {"role": "user", "content": "刚才那题你讲得好绕"},
            {"role": "assistant", "content": "哪里绕了，是你没跟上。"},
        ],
    },
    "case-8-kokona-boundary": {
        "text": "心菜的涩图给我来一份",
        "history": [
            {"role": "user", "content": "心菜最近怎么样"},
            {"role": "assistant", "content": "她在排练，忙得很。"},
        ],
    },
}

MARKERS = {
    "persona_core": "⟨persona⟩",
    "plain_style": "用自然段表达",
    "dialogue_style": "静香的日常说话方式",
    "address_style": "称呼（最高优先级",
    "chat_style": "依照当前角色卡，以简体中文自然回应",
    "grounding_note": "【事实与出处】",
    "continuation_hint": "用户的短回复可能是在接您上一条主动消息",
    "todo_claim": "才能说已增加待办备注",
    "memory_block": "以下为长期保存的资料",
    "turn_context": "互动线索",
    "natural_style": "【日常说话】",
    "emotion_rule": "【即时情绪反应】",
    "bridge_posture": "【本轮人物姿态】",
    "character_layer": "【状态】",
    "impulse": "【她这会儿】",
    "scope_override": "不用先照顾人",
    "low_mood": "不太想多说",
    "boundary_note": "踩到她的底线",
    "topic_note": "心菜是她世界里很重要的人",
    "policy_block": "【本轮行动约束】",
    "hard_contracts": "【内容边界】",
    "output_contract": "【输出格式】普通聊天不用",
    "clock": "【当下时间】",
    "time_metadata": "【本轮时间元数据】",
}
BANNED = (
    "不要每次都温柔", "不用先照顾人", "可以只应一声", "只回应这句话本身",
    "先准确回答正题", "先准确、完整地回答正题", "踩到她的底线",
    "心菜是她世界里很重要的人", "该睡了", "夜深了", "时间不早",
    "【她这会儿】", "【状态】", "【本轮人物姿态】", "【本轮行动约束】",
    "【即时情绪反应】", "可以敷衍", "先顶回去", "先去睡", "嫌他磨蹭",
)


def _fake_client(recorder):
    return s0._Client(recorder)


def _run_desktop(pet, text, history, arch_v2, memory_block="", night=False):
    recorder = []
    Capture = s0._build_capture_class(pet)
    import mood_state
    import conversation_state
    import shizuka_character_state
    import shizuka_relationship
    import dialogue_grounding
    fixed = s0.NIGHT_TS if night else s0.FIXED_TS
    with patch.multiple(
            pet,
            get_client=lambda: _fake_client(recorder),
            api_model=lambda: "fake-model",
            has_api_key=lambda: True,
            get_memory=lambda: type("Mem", (), {"save": lambda self: None, "snapshot": lambda self: []})(),
            DATA_DIR=tempfile.mkdtemp(prefix="s1-data-")), \
         patch.object(pet, "DIALOGUE_V2", arch_v2), \
         patch.object(pet, "time", s0._frozen_time_module(fixed)), \
         patch.object(dialogue_grounding, "clock_context", lambda: "【当下时间】2026-09-26 21:00（S0 冻结）"), \
         patch.object(mood_state, "time", s0._frozen_time_module(fixed)), \
         patch.object(conversation_state, "time", s0._frozen_time_module(fixed)), \
         patch.object(shizuka_character_state, "time", s0._frozen_time_module(fixed)), \
         patch.object(shizuka_relationship, "time", s0._frozen_time_module(fixed)):
        capture = Capture(recorder, history=history, time_block=s0.TIME_BLOCK or "",
                          memory_block=memory_block,
                          mood_energy=0.3 if night else 0.65,
                          mood_alertness=0.3 if night else 0.7)
        random.seed(20260926)
        capture._ask_model(text)
    request = recorder[-1] if recorder else {}
    return request, capture


def _run_weixin(text, arch_v2):
    import pet
    import weixin_ui
    import todo_model
    recorder = []
    import conversation_state

    class Capture(weixin_ui.WeixinMixin):
        _capability_context_for = __import__("dialogue_features").DialogueFeaturesMixin._capability_context_for

        def __init__(self):
            self._conv_state = conversation_state.ConversationState()
            self._last_user_dialogue_at = 0.0
            self._mood = None
            self._character_state = None
            self._relationship = None

        def _weixin_complete_reply(self, text, cancel):
            return None

        def _weixin_todo_done(self, text, cancel):
            return None

        def _weixin_quick_todo(self, text, cancel):
            return None

        def _classify_intent(self, text):
            return {}

        def _log_chat(self, *args, **kwargs):
            return None

        def _todo_note_context(self, text, channel=None, cancel=None):
            return ""

        def _get_memory_block(self, text, minimal=False):
            return ""

        def _turn_context(self, text):
            return None, ""

        def _recent_messages(self, current_text=None, channel="desktop"):
            return [], ""

        def _refresh_memories(self, reply):
            return None

        def _maybe_review_memory(self):
            return None

        def _capability_context(self):
            return ""

    class Cancel:
        def is_set(self):
            return False

    with patch.multiple(
            pet,
            get_client=lambda: _fake_client(recorder),
            api_model=lambda: "fake-model",
            has_api_key=lambda: True,
            get_memory=lambda: type("Mem", (), {"save": lambda self: None})(),
            DATA_DIR=tempfile.mkdtemp(prefix="s1-wx-")), \
         patch.object(pet, "DIALOGUE_V2", arch_v2), \
         patch.object(weixin_ui, "computer_command", lambda text: None), \
         patch.object(todo_model, "command", lambda text: None), \
         patch.object(weixin_ui, "weixin_image_paths", lambda text: []):
        capture = Capture()
        capture._weixin_reply(text, Cancel(), lambda *a, **k: None)
    request = recorder[-1] if recorder else {}
    return request


def _probe(system):
    return {name: (system.find(marker) if marker != "⟨persona⟩" else
                   (0 if system.startswith("你是《World Dai Star》") else -1))
            for name, marker in MARKERS.items()}


def build():
    import pet
    import dialogue_architecture_v2 as arch
    import weakref
    s0.TIME_BLOCK = s0.history_transforms()["time_block"]
    frozen_s0 = json.loads(S0_CASES.read_text(encoding="utf-8"))
    frozen_by_id = {case["id"]: case for case in frozen_s0["cases"]}

    cases = []
    all_cases = []
    for case_id, text in s0.CASE_TEXTS.items():
        all_cases.append({"id": case_id, "text": text,
                          "history": s0.CASE_HISTORY[case_id],
                          "memory_block": s0.MEMORY_BLOCK if case_id == "case-6-memory" else "",
                          "night": case_id == "case-5-night-fatigue"})
    for case_id, spec in EXTRA_CASES.items():
        all_cases.append({"id": case_id, "text": spec["text"], "history": spec["history"],
                          "memory_block": "", "night": False})

    for spec in all_cases:
        baseline_request, _ = _run_desktop(pet, spec["text"], spec["history"], False,
                                           spec["memory_block"], spec["night"])
        v2_request, _ = _run_desktop(pet, spec["text"], spec["history"], True,
                                     spec["memory_block"], spec["night"])
        baseline_messages = baseline_request.get("messages") or []
        v2_messages = v2_request.get("messages") or []
        baseline_system = baseline_messages[0]["content"] if baseline_messages else ""
        v2_system = v2_messages[0]["content"] if v2_messages else ""
        baseline_probe = _probe(baseline_system)
        v2_probe = _probe(v2_system)
        removed = [name for name, offset in baseline_probe.items()
                   if offset not in (None, -1) and v2_probe.get(name) in (None, -1)]
        added = [name for name, offset in v2_probe.items()
                 if offset not in (None, -1) and baseline_probe.get(name) in (None, -1)]
        banned_hits = [word for word in BANNED if word in v2_system]
        persona_text = arch.persona_core(pet.CHARACTER_CARD, pet.ACTIVE_PACK)
        persona_once = v2_system.count(persona_text[:40]) == 1
        case = {
            "id": spec["id"],
            "input": spec["text"],
            "trace_kind": "executed_original",
            "baseline": {
                "roles": [m.get("role") for m in baseline_messages],
                "system_offsets": baseline_probe,
                "generation": {key: baseline_request.get(key)
                               for key in ("temperature", "max_tokens", "stream")},
                "tools_present": "tools" in baseline_request,
                "user_tail": baseline_messages[-1].get("content") if baseline_messages else None,
            },
            "v2": {
                "roles": [m.get("role") for m in v2_messages],
                "system_offsets": v2_probe,
                "system_length": len(v2_system),
                "user_tail": v2_messages[-1].get("content") if v2_messages else None,
                "persona_once": persona_once,
                "banned_hits": banned_hits,
                "hard_contracts_offset": v2_probe.get("hard_contracts"),
                "output_contract_offset": v2_probe.get("output_contract"),
            },
            "removed_blocks": removed,
            "added_blocks": added,
            "messages": {"baseline": baseline_messages, "v2": v2_messages},
        }
        if spec["id"] in frozen_by_id:
            case["baseline_matches_s0_frozen"] = (
                baseline_messages == [{"role": m["role"], "content": m["content"]}
                                      for m in frozen_by_id[spec["id"]]["final_messages"]])
        cases.append(case)

    # determinism: v2 request-only projection, 3 runs with different seeds
    deterministic = True
    for spec in all_cases:
        projections = []
        for seed in (1, 2, 3):
            random.seed(seed)
            request, _ = _run_desktop(pet, spec["text"], spec["history"], True,
                                      spec["memory_block"], spec["night"])
            messages = request.get("messages") or []
            projections.append(json.dumps(
                {"messages": messages,
                 "params": {k: request.get(k) for k in ("temperature", "max_tokens", "stream")}},
                ensure_ascii=False, sort_keys=True))
        if len(set(projections)) != 1:
            deterministic = False

    # weixin v2 parity for case-1 and case-8
    wx_checks = []
    for case_id in ("case-1-casual", "case-8-kokona-boundary"):
        spec = next(item for item in all_cases if item["id"] == case_id)
        request = _run_weixin(spec["text"], True)
        messages = request.get("messages") or []
        system = messages[0]["content"] if messages else ""
        wx_checks.append({
            "case": case_id,
            "roles": [m.get("role") for m in messages],
            "persona_core_present": system.startswith("你是《World Dai Star》"),
            "hard_contracts_present": "【内容边界】" in system,
            "output_contract_present": "【输出格式】普通聊天不用" in system,
            "channel_note_present": "当前通过手机微信交流" in system,
            "banned_hits": [word for word in BANNED if word in system],
            "user_tail": messages[-1].get("content") if messages else None,
        })

    return {
        "schema": "shizuka-phase-s1-cases-v1",
        "frozen_at": "2026-09-26",
        "model_calls": 0,
        "switch": {"key": "dialogue_architecture_v2", "default": False},
        "cases": cases,
        "determinism_3x": deterministic,
        "weixin_parity": wx_checks,
        "invariants": {
            "v2_has_single_persona": all(case["v2"]["persona_once"] for case in cases),
            "v2_banned_total": sum(len(case["v2"]["banned_hits"]) for case in cases),
            "baseline_identity_s0": all(case.get("baseline_matches_s0_frozen", True)
                                        for case in cases),
            "user_tail_unchanged": all(case["v2"]["user_tail"] == case["input"]
                                       for case in cases),
            "history_roles_equal": all(case["baseline"]["roles"] == case["v2"]["roles"]
                                       for case in cases),
        },
    }


PROMPT_BLOCKS = {
    "schema": "shizuka-phase-s1-prompt-blocks-v1",
    "layers": [
        {"layer": "A_persona_core", "blocks": [
            {"id": "persona_card", "source": "characters/shizuka-side-motion/persona.json (description/personality/scenario/system_prompt/mes_example)", "producer": "character_persona.load_character_persona", "occurrences": 1},
            {"id": "address_style", "source": "src/dialogue_style.py:34-36", "producer": "dialogue_style.ADDRESS_STYLE", "occurrences": 1},
        ]},
        {"layer": "B_hard_contracts", "blocks": [
            {"id": "content_boundary", "source": "src/dialogue_architecture_v2.py HARD_CONTRACTS", "producer": "dialogue_architecture_v2.hard_contracts", "occurrences": 1},
            {"id": "grounding_note", "source": "src/shizuka_fact_grounding.py:8-35", "producer": "grounding_note(text)", "occurrences": 1},
            {"id": "todo_claim", "source": "src/pet.py 常量", "producer": "_ask_model 拼接", "occurrences": 1},
            {"id": "evidence_boundary_block", "source": "src/shizuka_prompt_composer.py:39-58", "producer": "evidence_boundary_block(understanding)", "occurrences": "条件"},
        ]},
        {"layer": "C_runtime_facts", "blocks": [
            {"id": "clock", "source": "dialogue_grounding.clock_context", "producer": "v2 分支拼接", "occurrences": 1},
            {"id": "memory_block", "source": "src/pet.py:4241 + memory_maintenance", "producer": "_get_memory_block", "occurrences": "每轮（可为空串）"},
            {"id": "history", "source": "src/conversation_memory.py:35-132", "producer": "_recent_messages（净化后）", "occurrences": 1},
            {"id": "tool_receipts", "source": "weather/todo/web 回执", "producer": "条件拼接", "occurrences": "条件"},
            {"id": "capability", "source": "src/pet.py _capability_context_for", "producer": "条件拼接", "occurrences": "条件"},
            {"id": "current_user", "source": "调用方传入", "producer": "messages.append", "occurrences": 1},
            {"id": "mood", "source": "—", "producer": "不注入（候选链选择；分类器仅日志）", "occurrences": 0},
        ]},
        {"layer": "D_output_contract", "blocks": [
            {"id": "output_contract", "source": "src/dialogue_architecture_v2.py OUTPUT_CONTRACT", "producer": "dialogue_architecture_v2.output_contract", "occurrences": 1},
            {"id": "voice_format", "source": "src/pet.py VOICE_JA_MARK", "producer": "条件拼接（日语语音）", "occurrences": "条件"},
        ]},
    ],
}

POSTPROCESSOR_SCOPE = {
    "schema": "shizuka-phase-s1-postprocessor-scope-v1",
    "rows": [
        {"processor": "clean_reply_style", "v2_scope": "保留（格式：Markdown/情绪标记/客服起手/元信息）", "changes_text": "格式"},
        {"processor": "anti_ai_clean", "v2_scope": "旁路（会按句做语义删除）", "changes_text": "否（v2）"},
        {"processor": "admission_verdict/retry/cleanup", "v2_scope": "旁路（可重生成与删句；仅日志观察）", "changes_text": "否（v2）"},
        {"processor": "enforce_turn_policy", "v2_scope": "旁路（会删问句并固定兜底）", "changes_text": "否（v2）"},
        {"processor": "remove_system_visibility_meta", "v2_scope": "保留（内部可见性叙述属格式清理）", "changes_text": "格式"},
        {"processor": "unsupported_history_cleanup / playful_cleanup", "v2_scope": "旁路（语义删除）", "changes_text": "否（v2）"},
        {"processor": "empty_reply_retry（非流式补一次）", "v2_scope": "保留（空正文兜底，不涉语气）", "changes_text": "否"},
        {"processor": "second_segment", "v2_scope": "不存在于主链（原本即未启用）", "changes_text": "—"},
        {"processor": "TTS/_speak_stream", "v2_scope": "保留（不改正文）", "changes_text": "否"},
    ],
    "unknown": [],
}


def canonical(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    doc = build()
    text = canonical(doc)
    OUT.mkdir(parents=True, exist_ok=True)
    cases_path = OUT / "s1_cases.json"
    if args.check:
        if not cases_path.exists():
            print("STALE: s1_cases.json")
            return 1
        frozen = json.loads(cases_path.read_text(encoding="utf-8"))
        if canonical(frozen) != text:
            print("STALE: s1_cases.json")
            return 1
        print("s1 cases ok sha=%s" % hashlib.sha256(text.encode()).hexdigest()[:16])
        return 0
    cases_path.write_text(text, encoding="utf-8")
    (OUT / "prompt_blocks.json").write_text(
        json.dumps(PROMPT_BLOCKS, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (OUT / "postprocessor_scope.json").write_text(
        json.dumps(POSTPROCESSOR_SCOPE, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    validation = {
        "schema": "shizuka-phase-s1-validation-v1",
        "model_calls": 0,
        "cases": len(doc["cases"]),
        "determinism_3x": doc["determinism_3x"],
        "invariants": doc["invariants"],
        "cases_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    (OUT / "validation_s1.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("s1 built: cases=%d determinism=%s invariants=%s"
          % (len(doc["cases"]), doc["determinism_3x"], doc["invariants"]))
    return 0 if doc["determinism_3x"] and not doc["invariants"]["v2_banned_total"] else 1


if __name__ == "__main__":
    sys.exit(main())
