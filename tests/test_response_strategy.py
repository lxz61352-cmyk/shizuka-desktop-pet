"""回复形状：意图规则、连续提问惩罚、策略提示词，以及角色卡示例不再全以问句收尾。"""
from pathlib import Path
import json
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conversation_state import ConversationState, detect_intent  # noqa: E402
import response_strategy as rs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class IntentTests(unittest.TestCase):
    def test_question(self):
        for text in ("番茄钟25分钟以后是不是要休息？", "这个怎么用", "今天几点了"):
            self.assertEqual(detect_intent(text), "question", text)

    def test_subjective_advice_is_not_treated_as_a_functional_question(self):
        for text in ("你觉得我这个方案怎么样？", "我今晚是继续改报告，还是先睡？", "要不要跟他说一声"):
            self.assertEqual(detect_intent(text), "advice", text)

    def test_bare_question_word_is_not_a_question(self):
        self.assertEqual(detect_intent("感觉什么都不想干"), "emotion")

    def test_emotion(self):
        for text in ("今天好累", "最近有点烦", "心里好难受", "感觉什么都不想干", "我真是个废物"):
            self.assertEqual(detect_intent(text), "emotion", text)

    def test_request(self):
        self.assertEqual(detect_intent("帮我查一下这个报错"), "request")
        self.assertEqual(detect_intent("帮我查一下 requests 装不上是什么原因"), "request")

    def test_sharing(self):
        self.assertEqual(detect_intent("今天终于把报告写完了"), "sharing")

    def test_greeting_and_goodbye(self):
        self.assertEqual(detect_intent("早上好"), "greeting")
        self.assertEqual(detect_intent("我去洗澡了"), "goodbye")

    def test_general(self):
        self.assertEqual(detect_intent("嗯"), "general")

    def test_attitude_stays_interpersonal_not_question(self):
        for text in ("你好懂啊", "你怎么这么笨", "你怎么这么懂"):
            self.assertEqual(detect_intent(text), "sharing", text)
        self.assertEqual(detect_intent("1+1等于几"), "question")


class QuestionPenaltyTests(unittest.TestCase):
    def test_first_followup_question_cools_down(self):
        state = ConversationState()
        state.consecutive_questions = 1
        self.assertLess(rs.weights_for(state, "general")["question"], rs.BASE_WEIGHTS["question"])

    def test_two_in_a_row_ban_question(self):
        state = ConversationState()
        state.consecutive_questions = 2
        self.assertEqual(rs.weights_for(state, "general")["question"], 0)

    def test_question_intent_still_answers_first(self):
        weights = rs.weights_for(ConversationState(), "question")
        self.assertGreater(weights["direct"], weights["question"])

    def test_never_picks_question_after_two(self):
        state = ConversationState()
        state.consecutive_questions = 2
        for seed in range(50):
            state.last_strategy = None
            self.assertNotEqual(rs.pick(state, "general", rng=random.Random(seed)), "question")


class LastStrategyTests(unittest.TestCase):
    def test_same_strategy_cools_down(self):
        state = ConversationState()
        state.last_strategy = "reaction"
        self.assertLess(rs.weights_for(state, "sharing")["reaction"], rs.INTENT_WEIGHTS["sharing"]["reaction"])

    def test_question_intent_is_exempt(self):
        state = ConversationState()
        state.last_strategy = "direct"
        self.assertEqual(rs.weights_for(state, "question")["direct"], rs.INTENT_WEIGHTS["question"]["direct"])


class ObserveReplyTests(unittest.TestCase):
    def test_question_reply_counts(self):
        state = ConversationState()
        state.observe_reply("写到几点？")
        state.observe_reply("今天还顺利吗？")
        self.assertEqual(state.consecutive_questions, 2)

    def test_particle_statement_is_not_a_question(self):
        state = ConversationState()
        state.observe_reply("有我在呢。")
        self.assertEqual(state.consecutive_questions, 0)
        state.observe_reply("今天还顺利吗。")
        self.assertEqual(state.consecutive_questions, 1)

    def test_plain_reply_resets(self):
        state = ConversationState()
        state.observe_reply("写到几点？")
        state.observe_reply("好，去吧。")
        self.assertEqual(state.consecutive_questions, 0)
        self.assertEqual(state.question_count, 1)

    def test_reply_length_buckets(self):
        state = ConversationState()
        state.observe_reply("好。")
        self.assertEqual(state.reply_length, "short")
        state.observe_reply("一" * 200)
        self.assertEqual(state.reply_length, "long")


class InstructionTests(unittest.TestCase):
    def test_every_strategy_has_a_short_positive_line(self):
        for name in rs.STRATEGIES:
            text = rs.instruction(name)
            if name == "free":
                self.assertEqual(text, "")
                continue
            self.assertTrue(text.startswith("【本轮回复侧重】"), name)
            self.assertGreater(len(text), 10, name)

    def test_free_keeps_state_notes_only(self):
        state = ConversationState()
        self.assertEqual(rs.instruction("free", state), "")
        state.consecutive_questions = 1
        text = rs.instruction("free", state)
        self.assertIn("不要再用提问收尾", text)
        self.assertNotIn("【本轮回复侧重】", text)

    def test_no_stacked_bans(self):
        for name in rs.STRATEGIES:
            for word in ("必须", "禁止", "不许", "不得"):
                self.assertNotIn(word, rs.instruction(name), name)

    def test_choose_updates_state(self):
        state = ConversationState()
        intent, strategy = rs.choose(state, "今天好累", rng=random.Random(1))
        self.assertEqual(intent, "emotion")
        self.assertIn(strategy, ("care", "reaction", "continuation", "humor"))
        self.assertEqual(state.last_strategy, strategy)
        self.assertEqual(state.turn, 1)

    def test_instruction_warns_after_a_question(self):
        state = ConversationState()
        self.assertNotIn("不要再用提问收尾", rs.instruction("reaction", state))
        state.consecutive_questions = 1
        self.assertIn("不要再用提问收尾", rs.instruction("reaction", state))

    def test_instruction_includes_abandon_note(self):
        state = ConversationState()
        state.abandon_note = "上一轮的问题用户没有接，不要重复追问，接住用户现在说的事。"
        self.assertIn("不要重复追问", rs.instruction("direct", state))


class StanceTests(unittest.TestCase):
    def test_self_deprecation(self):
        self.assertIn("自我否定", rs.stance_note("我真是个废物"))
        self.assertIn("自我否定", rs.stance_note("我肯定做不好"))

    def test_help_request(self):
        self.assertIn("具体做法", rs.stance_note("帮我看看这个报错"))

    def test_completion(self):
        self.assertIn("认可", rs.stance_note("今天终于把报告写完了"))

    def test_free_cases_get_nothing(self):
        for text in ("今天去吃了拉面", "这个方案挺好的", "在改代码"):
            self.assertEqual(rs.stance_note(text), "", text)


class PendingQuestionTests(unittest.TestCase):
    def test_question_reply_sets_pending(self):
        state = ConversationState()
        state.observe_reply("看的哪一部？")
        self.assertTrue(state.pending_question)

    def test_short_answer_resolves_without_note(self):
        state = ConversationState()
        state.observe_reply("看的哪一部？")
        self.assertIsNone(state.resolve_pending("还行"))
        self.assertIsNone(state.pending_question)

    def test_topic_switch_returns_abandon_note(self):
        state = ConversationState()
        state.observe_reply("看的哪一部？")
        note = state.resolve_pending("对了，我发现程序有个bug")
        self.assertIn("不要重复追问", note or "")

    def test_choose_records_abandon_note(self):
        state = ConversationState()
        state.observe_reply("看的哪一部？")
        rs.choose(state, "对了，我发现程序有个bug", rng=random.Random(1))
        self.assertIn("不要重复追问", state.abandon_note or "")

    def test_no_pending_means_no_note(self):
        state = ConversationState()
        self.assertIsNone(state.resolve_pending("今天去吃了拉面"))


class PromptWiringTests(unittest.TestCase):
    def test_strategy_is_a_hint_not_a_template(self):
        from dialogue_style import NATURAL_STYLE
        self.assertIn("不是固定模板", NATURAL_STYLE)

    def test_memory_rule_is_present(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn("记住一件事不等于必须主动提起", source)

    def test_legacy_strategy_has_no_production_wiring(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertNotIn("import response_strategy", source)
        self.assertNotIn("response_strategy.", source)
        self.assertIn("self._conv_state.begin_turn(text)", source)
        self.assertIn("self._conv_state.continuity_note()", source)


class CardExampleShapeTests(unittest.TestCase):
    """few-shot 的形状要混合：不能每段都以问句/关心句收尾。"""

    def _replies(self, pack):
        data = json.loads((ROOT / "characters" / pack / "persona.json").read_text(encoding="utf-8-sig"))
        chunks = data["data"]["mes_example"].replace("<START>", "").split("{{user}}:")[1:]
        return [chunk.split("{{char}}:")[1].strip() for chunk in chunks]

    def test_cards_mix_reply_shapes(self):
        for pack in ("shizuka-side-motion", "shizuka-classic"):
            replies = self._replies(pack)
            if not replies:
                continue   # 当前采用 A 版（无示例）：空是合法状态
            self.assertGreaterEqual(len(replies), 6, pack)
            questions = sum(1 for r in replies if r.rstrip().endswith(("？", "?")))
            self.assertLessEqual(questions, len(replies) // 2, pack)
            self.assertTrue(any(len(r) <= 12 for r in replies), pack)

    def test_persona_loader_reads_the_card(self):
        from character_persona import load_character_persona
        text = load_character_persona(str(ROOT / "characters" / "shizuka-side-motion" / "persona.json"), None)
        self.assertIn("静香", text)
        self.assertIn("心菜", text)


if __name__ == "__main__":
    unittest.main()
