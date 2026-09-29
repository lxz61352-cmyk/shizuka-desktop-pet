"""第 5 步离线验收：微信与桌面的最终消息结构（不调模型、不走网络）。

用假客户端真跑 `_weixin_reply` / `_ask_model`，捕获最终发给模型的 messages：
只验证结构（注入了什么、没注入什么），不把提示词存在当成模型效果。
"""
from pathlib import Path
import copy
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SHIZUKA_DATA_DIR", tempfile.mkdtemp(prefix="shizuka-prompt-"))

import pet  # noqa: E402
import todo_model  # noqa: E402
import weixin_ui  # noqa: E402
from conversation_state import ConversationState  # noqa: E402
from dialogue_features import DialogueFeaturesMixin  # noqa: E402
from shizuka_character_state import CharacterState  # noqa: E402
from shizuka_context_compiler import minimal_character_note  # noqa: E402
from shizuka_relationship import RelationshipState  # noqa: E402
from shizuka_turn_planner import classify_situation, interaction_signals, response_authority  # noqa: E402

REPLY = "测试回复。"


class _Chunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]


class _Completion:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]


class _Stream:
    def __init__(self, content):
        self._items = [_Chunk(content)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._items)


class _Completions:
    def __init__(self, recorder):
        self.recorder = recorder

    def create(self, **kwargs):
        self.recorder.append(copy.deepcopy(kwargs.get("messages")))
        return _Stream(REPLY) if kwargs.get("stream") else _Completion(REPLY)


class _Client:
    def __init__(self, recorder):
        self.chat = type("Chat", (), {"completions": _Completions(recorder)})()


class _Cancel:
    def is_set(self):
        return False


def _expected_note(text):
    state = ConversationState()
    situation = classify_situation(text, state)
    signals = interaction_signals(situation, text, state)
    return minimal_character_note(text, signals, situation, response_authority(signals, situation))


def _user_row(text, index):
    return {"id": "u%d" % index, "role": "user", "kind": "chat",
            "created": time.time(), "text": text}


def _assistant_row(text, index):
    return {"id": "a%d" % index, "role": "assistant", "kind": "chat",
            "created": time.time(), "text": text}


class _DesktopCapture(pet.DeskPet):
    _capability_context_for = DialogueFeaturesMixin._capability_context_for

    def __init__(self, recorder):
        self._recorder = recorder
        self._chat_lock = threading.RLock()
        self._chat_log = []
        self._conv_state = ConversationState()
        self._conv_id = 1
        self._last_rel_line = None
        self._pending_attachments = []
        self._voice_on = False
        self._tts_lang = "zh"
        self._mood = pet.mood_state.MoodState(now=time.time())
        self._character_state = CharacterState()
        self._relationship = RelationshipState(tempfile.mkdtemp(prefix="shizuka-rel-"))
        self._capability_marker = "CAPABILITY-MARKER"
        self._admission_used = False
        self._plan_seen_by_memory = None
        self.said = []

    def say(self, text, *args, **kwargs):
        self.said.append(text)

    def _should_sound(self, *args):
        return False

    def _ui(self, fn):
        return None

    def _clear_topic_cooldown(self, text):
        return None

    def _voice_lang_hint(self):
        return ""

    def _weather_followup_fact(self, text, my_conv):
        return ""

    def _get_memory_block(self, text, minimal=False):
        self._plan_seen_by_memory = getattr(self._conv_state, "last_shadow_turn", None)
        return ""

    def _todo_note_context(self, text, cancel=None):
        return ""

    def _web_evidence(self, text, my_conv):
        return ""

    def _capability_context(self):
        return self._capability_marker

    def _post_memory(self, text, reply):
        return None

    def _scene(self, key, **kwargs):
        return "SCENE:%s" % key


class _WeixinCapture(weixin_ui.WeixinMixin):
    _capability_context_for = DialogueFeaturesMixin._capability_context_for

    def _weixin_quick_todo(self, text, cancel):
        return None

    def __init__(self, recorder):
        self._recorder = recorder
        self._conv_state = ConversationState()
        self._last_user_dialogue_at = 0.0
        self._capability_marker = "CAPABILITY-MARKER"
        self._plan_seen_by_memory = None

    def _weixin_complete_reply(self, text, cancel):
        return None

    def _weixin_todo_done(self, text, cancel):
        return None

    def _classify_intent(self, text):
        return {}

    def _log_chat(self, *args, **kwargs):
        return None

    def _todo_note_context(self, text, channel=None, cancel=None):
        return ""

    def _get_memory_block(self, text, minimal=False):
        self._plan_seen_by_memory = getattr(self._conv_state, "last_shadow_turn", None)
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
        return self._capability_marker


class SharedBridgeCaptureTests(unittest.TestCase):
    CASES = {
        "T04": ["讲一下二元积分换元时雅可比行列式为什么取绝对值",
                "所以大蠢鱼解释清楚了吗"],
        "T08": ["你刚才说话让我有点不舒服",
                "你别解释规则，直接说你自己怎么想"],
        "T12": ["你这句听起来有点暧昧啊",
                "我是在开玩笑，别突然上课",
                "那你刚刚到底什么意思"],
        "T15": ["台词都对了，观众不就懂了吗",
                "那你会怎么演这一句“我没事”"],
    }

    def setUp(self):
        self.desktop_log = []
        self.weixin_log = []
        self.desktop = _DesktopCapture(self.desktop_log)
        self.weixin = _WeixinCapture(self.weixin_log)
        self.tmp = tempfile.TemporaryDirectory(prefix="shizuka-prompt-data-")
        self.addCleanup(self.tmp.cleanup)
        self.patcher = patch.multiple(
            pet,
            get_client=lambda: _Client(self.desktop_log),
            api_model=lambda: "fake-model",
            load_persona=lambda: "PERSONA-MARKER",
            character_option=lambda key, default: "STYLE-MARKER",
            has_api_key=lambda: True,
            get_memory=lambda: type("Mem", (), {"save": lambda self: None})(),
            DATA_DIR=self.tmp.name)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.weixin_patches = [
            patch.object(weixin_ui, "computer_command", lambda text: None),
            patch.object(todo_model, "command", lambda text: None),
            patch.object(weixin_ui, "weixin_image_paths", lambda text: []),
        ]
        for item in self.weixin_patches:
            item.start()
            self.addCleanup(item.stop)

    def _capture_turn(self, text, index):
        self.desktop._chat_log.append(_user_row(text, index))
        self.desktop._ask_model(text)
        self.desktop._chat_log.append(_assistant_row(REPLY, index))
        with patch.object(pet, "get_client", lambda: _Client(self.weixin_log)):
            self.weixin._weixin_reply(text, _Cancel(), lambda *a, **k: None)
        expected = _expected_note(text)
        desktop_system = next(m["content"] for m in self.desktop_log[-1]
                              if m.get("role") == "system")
        weixin_system = next(m["content"] for m in self.weixin_log[-1]
                             if m.get("role") == "system")
        return expected, desktop_system, weixin_system

    def test_shared_bridge_appears_in_both_channels(self):
        index = 0
        for case, turns in self.CASES.items():
            for text in turns:
                index += 1
                expected, desktop_system, weixin_system = self._capture_turn(text, index)
                self.assertTrue(expected, (case, text))
                self.assertIn(expected, desktop_system, (case, text))
                self.assertIn(expected, weixin_system, (case, text))

    def test_weixin_keeps_shortness_and_drops_desktop_only_layers(self):
        expected, _, weixin_system = self._capture_turn("讲一下雅可比行列式", 91)
        self.assertIn("屏幕小、打字慢", weixin_system)
        for marker in ("当前状态倾向", "【状态】", "【Character reference】",
                       "CPC", "Shared History"):
            self.assertNotIn(marker, weixin_system, marker)

    def test_utterance_shape_sentence_is_shared_by_both_channels(self):
        samples = (
            ("今天外卖又迟到了", "像当面说话"),
            ("Python 元组都能哈希吗", "关键意思和必要条件说完整"),
            ("算了，先这样吧", "短反应或未完句"),
        )
        index = 200
        for text, sentence in samples:
            index += 1
            _, desktop_system, weixin_system = self._capture_turn(text, index)
            self.assertIn(sentence, desktop_system, text)
            self.assertIn(sentence, weixin_system, text)

    def test_second_segment_helper_reuses_prior_reply_but_main_chain_stays_single_request(self):
        first_text = "今天那家店确实慢，我在门口等了四十分钟。"
        second_text = "下次干脆换一家。"

        class SeqCompletions:
            def __init__(self, recorder):
                self.recorder = recorder
                self.calls = 0

            def create(self, **kwargs):
                self.recorder.append(copy.deepcopy(kwargs.get("messages")))
                text = first_text if self.calls == 0 else second_text
                self.calls += 1
                return _Stream(text) if kwargs.get("stream") else _Completion(text)

        class SeqClient:
            def __init__(self, recorder):
                self.chat = type("Chat", (), {"completions": SeqCompletions(recorder)})()

        seq_client = SeqClient(self.desktop_log)
        with patch.object(pet, "get_client", lambda: seq_client), \
             patch("shizuka_turn_planner.should_append_second_segment", return_value=True):
            self.desktop._chat_log.append(_user_row("今天外卖又迟到了", 301))
            self.desktop._ask_model("今天外卖又迟到了")
            self.assertEqual(len(self.desktop_log), 1)
            self.assertEqual(self.desktop.said, [])
            shadow = self.desktop._conv_state.last_shadow_turn
            self.desktop._maybe_second_segment(
                self.desktop_log[0], first_text, self.desktop._conv_id,
                shadow.policy, shadow.understanding)
        self.assertEqual(len(self.desktop_log), 2)
        second = self.desktop_log[-1]
        self.assertEqual([m.get("role") for m in second[-2:]], ["assistant", "user"])
        self.assertEqual(second[-2]["content"], first_text)
        self.assertIn("【分段追加】", second[-1]["content"])
        self.assertEqual(self.desktop.said, [second_text])

    def test_main_chain_does_not_auto_append_even_if_probability_says_yes(self):
        before = len(self.desktop_log)
        with patch("shizuka_turn_planner.should_append_second_segment", return_value=True):
            self.desktop._chat_log.append(_user_row("今天外卖又迟到了", 303))
            self.desktop._ask_model("今天外卖又迟到了")
        self.assertEqual(len(self.desktop_log) - before, 1)
        self.assertEqual(self.desktop.said, [])

    def test_second_segment_helper_drops_end_marker(self):
        first_text = "今天那家店确实慢，我在门口等了四十分钟。"
        with patch("shizuka_turn_planner.should_append_second_segment", return_value=False):
            self.desktop._chat_log.append(_user_row("今天外卖又迟到了", 304))
            self.desktop._ask_model("今天外卖又迟到了")

        class EndCompletions:
            def __init__(self, recorder):
                self.recorder = recorder

            def create(self, **kwargs):
                self.recorder.append(copy.deepcopy(kwargs.get("messages")))
                return _Completion("[[END]]") if not kwargs.get("stream") else _Stream("[[END]]")

        class EndClient:
            def __init__(self, recorder):
                self.chat = type("Chat", (), {"completions": EndCompletions(recorder)})()

        shadow = self.desktop._conv_state.last_shadow_turn
        with patch.object(pet, "get_client", lambda: EndClient(self.desktop_log)), \
             patch("shizuka_turn_planner.should_append_second_segment", return_value=True):
            self.desktop._maybe_second_segment(
                self.desktop_log[0], first_text, self.desktop._conv_id,
                shadow.policy, shadow.understanding)
        self.assertEqual(self.desktop.said, [])

    def test_grounding_boundaries_reach_both_final_systems(self):
        _, desktop_system, weixin_system = self._capture_turn("谢谢，晚安喵", 305)
        for system in (desktop_system, weixin_system):
            self.assertIn("【事实与出处】", system)
            self.assertIn("不能升级成已发生事实", system)
            self.assertIn("不要主动复述、改写或更新旧天气", system)
            self.assertIn("不要主动报告", system)

    def test_second_segment_hard_zero_keeps_one_request(self):
        before = len(self.desktop_log)
        with patch("shizuka_turn_planner.should_append_second_segment", return_value=False):
            self.desktop._chat_log.append(_user_row("今天外卖又迟到了", 302))
            self.desktop._ask_model("今天外卖又迟到了")
        self.assertEqual(len(self.desktop_log) - before, 1)
        self.assertEqual(self.desktop.said, [])

    def test_file_executor_status_only_on_file_turns(self):
        marker = "CAPABILITY-MARKER"
        _, desktop_weather, weixin_weather = self._capture_turn("帮我查一下明天本市的天气", 94)
        _, desktop_chat, weixin_chat = self._capture_turn("我刚吃了一碗拉面", 95)
        _, desktop_file, weixin_file = self._capture_turn("帮我修改这个文件夹里的报告", 96)
        for system in (desktop_weather, weixin_weather, desktop_chat, weixin_chat):
            self.assertNotIn(marker, system)
            self.assertNotIn("FileNotFoundError", system)
        self.assertIn(marker, desktop_file)
        self.assertIn(marker, weixin_file)

    def test_shared_turn_policy_block_appears_in_both_channels(self):
        _, desktop_system, weixin_system = self._capture_turn(
            "我觉得你说话很像客服", 97)
        marker = "【本轮行动约束】"
        self.assertEqual(desktop_system.count(marker), 1)
        self.assertEqual(weixin_system.count(marker), 1)
        for system in (desktop_system, weixin_system):
            self.assertIn("最多使用 2 个自然段或气泡", system)
            self.assertIn("不要追加问题", system)
            self.assertIn("一句自己的反应或立场", system)

    def test_each_channel_plans_once_before_memory_selection(self):
        self._capture_turn("我刚吃了一碗很咸的拉面", 98)
        for capture in (self.desktop, self.weixin):
            planned = capture._plan_seen_by_memory
            self.assertIsNotNone(planned)
            self.assertIs(planned, capture._conv_state.last_shadow_turn)


if __name__ == "__main__":
    unittest.main()
