"""Grounding text must be correct and wired into both chat channels."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shizuka_fact_grounding import grounding_note  # noqa: E402


class FactGroundingTests(unittest.TestCase):
    def test_history_and_user_correction_are_source_bounded(self):
        note = grounding_note("我上次说讨厌甜食，其实只是那天不想吃")
        self.assertIn("以新说明为准", note)
        self.assertIn("有出处的用户记忆", note)
        self.assertIn("不编造原话", note)

    def test_user_meme_is_not_verified_etymology(self):
        note = grounding_note("哈基米本来是什么意思")
        self.assertIn("你刚才说的用法", note)
        self.assertIn("没有可靠依据", note)
        self.assertNotIn("哈基米是猫", note)

    def test_tuple_condition_is_only_on_relevant_question(self):
        note = grounding_note("Python 列表和元组有什么区别")
        self.assertIn("每个元素都可哈希", note)
        self.assertNotIn("每个元素都可哈希", grounding_note("我刚吃完拉面"))

    def test_explicit_correction_gets_stronger_boundary(self):
        note = grounding_note("我上次说讨厌甜食，其实只是那天不想吃")
        self.assertIn("禁止称为‘改口’", note)
        self.assertIn("未知的新信息仍回答不知道", note)

    def test_both_chat_channels_include_grounding_note(self):
        pet = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        weixin = (ROOT / "src" / "weixin_ui.py").read_text(encoding="utf-8")
        self.assertIn("grounding_note(text)", pet)
        self.assertIn("grounding_note(visible)", weixin)

    def test_assistant_guesses_do_not_become_later_facts(self):
        note = grounding_note("陪我吐槽一句就行")
        self.assertIn("助手当时说过", note)
        self.assertIn("后续仍是推测", note)
        self.assertIn("不能升级成已发生事实", note)

    def test_unrelated_turn_does_not_repeat_old_weather_or_history_counts(self):
        note = grounding_note("谢谢，晚安")
        self.assertIn("当前不是在问天气时", note)
        self.assertIn("不要主动复述、改写或更新旧天气", note)
        self.assertIn("不要主动报告", note)
        self.assertIn("今天问过", note)

    def test_visible_self_stance_is_kept_consistent(self):
        note = grounding_note("对了，你喜欢猫还是狗")
        self.assertIn("自己的偏好、判断或立场", note)
        self.assertIn("不要为了换一种说法而给出相反答案", note)

    def test_recent_correction_stays_authoritative_for_followups(self):
        from conversation_state import ConversationState
        state = ConversationState()
        state.observe_user("我上次说讨厌甜食，其实只是那天不想吃")
        state.observe_user("那现在你觉得我喜欢什么")
        note = state.correction_followup_note()
        self.assertIn("不要从更正动作推断", note)
        self.assertIn("未明确说明的事实仍未知", note)
        self.assertIn("其实只是那天不想吃", note)

    def test_missing_prior_context_is_explicitly_bounded(self):
        from shizuka_fact_grounding import missing_prior_context_note
        note = missing_prior_context_note("你刚才说话让我不舒服", [])
        self.assertIn("没有可见的助手上一句", note)
        self.assertIn("不得猜自己说过什么", note)
        self.assertEqual(missing_prior_context_note(
            "你刚才说话让我不舒服", [{"role": "assistant", "content": "上一句"}]), "")

    def test_unresolved_reference_boundary_survives_followups(self):
        from conversation_state import ConversationState
        state = ConversationState()
        state.observe_user("你这句听起来有点暧昧")
        state.unresolved_prior_reference_turn = state.turn
        state.observe_user("我是在开玩笑")
        state.observe_user("那你刚刚到底什么意思")
        self.assertIn("原始前文仍不可见", state.unresolved_prior_reference_note())


if __name__ == "__main__":
    unittest.main()
