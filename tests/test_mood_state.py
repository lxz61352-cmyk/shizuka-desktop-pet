"""隐性状态层与回应模式：时间曲线、惯性、恢复、边界、功能豁免。"""
from pathlib import Path
import json
import random
import re
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import mood_state  # noqa: E402
import response_mode  # noqa: E402
import dialogue_features  # noqa: E402
from conversation_state import ConversationState  # noqa: E402


def stamp(text):
    return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))


class AlertnessTests(unittest.TestCase):
    def test_night_is_lower_than_morning(self):
        night = mood_state.alertness_target(stamp("2026-09-23 03:00"))
        morning = mood_state.alertness_target(stamp("2026-09-23 10:00"))
        self.assertLess(night, morning)
        self.assertLess(night, 0.35)

    def test_curve_is_continuous(self):
        values = [mood_state.alertness_target(stamp("2026-09-23 %02d:00" % hour)) for hour in range(24)]
        for a, b in zip(values, values[1:]):
            self.assertLess(abs(a - b), 0.35)


class MoodStateTests(unittest.TestCase):
    def test_inertia_moves_slowly(self):
        mood = mood_state.MoodState(now=stamp("2026-09-23 10:00"))
        mood.energy = 0.9
        mood.update(stamp("2026-09-23 10:00"))
        self.assertGreater(mood.energy, 0.7)

    def test_recovery_after_idle(self):
        now = stamp("2026-09-23 15:00")
        mood = mood_state.MoodState(now=now)
        mood.energy = 0.2
        mood._last_interaction = now - 7200
        mood.observe_user("在吗", now)
        self.assertGreater(mood.energy, 0.3)

    def test_values_stay_bounded(self):
        now = stamp("2026-09-23 10:00")
        mood = mood_state.MoodState(now=now)
        random.seed(7)
        for index in range(500):
            mood.observe_user("为什么不对，重新算一遍" if index % 3 == 0 else "哈哈这个好耶", now + index * 30)
            mood.update(now + index * 30)
        for name in ("energy", "alertness", "willingness", "patience", "engagement",
                     "cheerfulness", "warmth", "tension", "mood"):
            value = getattr(mood, name)
            self.assertGreaterEqual(value, 0.0, name)
            self.assertLessEqual(value, 1.0, name)

    def test_summary_has_no_numbers_and_keeps_facts_safe(self):
        mood = mood_state.MoodState(now=stamp("2026-09-23 23:30"))
        mood.energy = 0.3
        mood.alertness = 0.25
        mood.willingness = 0.4
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            text = mood.summary()
        self.assertIn("精力", text)
        self.assertIsNone(re.search(r"\d", text))
        self.assertIn("功能请求", text)

    def test_summary_is_empty_when_normal(self):
        mood = mood_state.MoodState(now=stamp("2026-09-23 15:00"))
        mood.energy = mood.alertness = mood.willingness = mood.patience = 0.6
        mood.engagement = mood.cheerfulness = mood.warmth = 0.6
        mood.tension = 0.2
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            self.assertEqual(mood.summary(), "")

    def test_mood_speaks_in_summary_when_high_or_low(self):
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            high = mood_state.MoodState(now=stamp("2026-09-23 15:00"))
            high.mood = 0.85
            self.assertIn("心情不错", high.summary())
            low = mood_state.MoodState(now=stamp("2026-09-23 15:00"))
            low.mood = 0.2
            self.assertIn("提不起劲", low.summary())

    def test_mood_rises_with_positive_and_falls_with_repeats(self):
        now = stamp("2026-09-23 15:00")
        positives = ("哈哈这个好耶", "今天真不错", "谢谢你", "太厉害了", "不错嘛", "开心", "笑死我了", "好活")
        positive = mood_state.MoodState(now=now)
        repeated = mood_state.MoodState(now=now)
        for index in range(8):
            positive.observe_user(positives[index], now + index * 20)
            positive.update(now + index * 20)
            repeated.observe_user("在吗", now + index * 20)
            repeated.update(now + index * 20)
        self.assertGreater(positive.mood, 0.62)
        self.assertLess(repeated.mood, 0.62)
        self.assertGreater(positive.mood, repeated.mood)

    def test_night_stage_is_phrased_as_a_tendency(self):
        night = stamp("2026-09-23 23:40")
        mood = mood_state.MoodState(now=night)
        mood.alertness = 0.25
        mood.energy = 0.35
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            text = mood.summary(night)
        self.assertIn("已经很晚", text)
        self.assertIn("可以直接催", text)

    def test_night_does_not_claim_low_alertness(self):
        night = stamp("2026-09-23 23:40")
        mood = mood_state.MoodState(now=night)
        mood.alertness = 0.25
        mood.energy = 0.6
        mood.willingness = 0.6
        mood.patience = 0.6
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            self.assertNotIn("清醒度", mood.summary(night, night_line=False))
        day = mood_state.MoodState(now=stamp("2026-09-23 15:00"))
        day.alertness = 0.25
        day.energy = 0.6
        day.willingness = 0.6
        day.patience = 0.6
        with patch.object(mood_state.MoodState, "update", lambda self, now=None: None):
            self.assertIn("清醒度", day.summary(stamp("2026-09-23 15:00")))

    def test_recent_events_are_recorded(self):
        now = stamp("2026-09-23 15:00")
        mood = mood_state.MoodState(now=now)
        for index in range(4):
            mood.observe_user("不对，重新算一遍", now + index * 20)
        self.assertIn("刚才用户反复修改要求", list(mood.recent_events))

    def test_repeated_questions_raise_load(self):
        now = stamp("2026-09-23 15:00")
        mood = mood_state.MoodState(now=now)
        for index in range(6):
            mood.observe_user("帮我查一下成都的GDP是多少", now + index * 10)
        mood.update(now + 70)
        self.assertGreater(mood.load, 0.1)

    def test_safety_limits_constant(self):
        self.assertIn("功能请求", mood_state.MOOD_SAFETY_LIMITS)
        self.assertIn("人体意义", mood_state.MOOD_SAFETY_LIMITS)
        self.assertIn("辱骂", mood_state.MOOD_SAFETY_LIMITS)
        self.assertIn("角色化倾向", mood_state.MOOD_SAFETY_LIMITS)


class EmotionTests(unittest.TestCase):
    """即时情绪反应：规则给弱倾向，判不了返回 None；情绪不解释、不追加服务。"""

    def test_positive_and_praise(self):
        self.assertEqual(mood_state.infer_emotion("哈哈你也太逗了")[0], "amused")
        self.assertEqual(mood_state.infer_emotion("你好懂啊")[0], "embarrassed")

    def test_self_deprecation_gets_attitude(self):
        label, intensity = mood_state.infer_emotion("我真是个废物")
        self.assertEqual(label, "annoyed")
        self.assertGreater(intensity, 0)

    def test_skeptical_and_annoyed(self):
        self.assertEqual(mood_state.infer_emotion("你是不是在敷衍我")[0], "skeptical")
        self.assertEqual(mood_state.infer_emotion("你怎么这么笨")[0], "annoyed")

    def test_accident_and_completion(self):
        self.assertEqual(mood_state.infer_emotion("我刚刚把文件删了")[0], "surprised")
        self.assertEqual(mood_state.infer_emotion("终于写完了")[0], "relieved")

    def test_repeat_question_is_impatient(self):
        state = ConversationState()
        state.last_user_text = "帮我查一下成都的GDP是多少"
        label, _ = mood_state.infer_emotion("帮我查一下成都的GDP是多少", None, state)
        self.assertEqual(label, "impatient")

    def test_low_mood_makes_her_indifferent(self):
        mood = mood_state.MoodState(now=stamp("2026-09-23 15:00"))
        mood.mood = 0.2
        self.assertEqual(mood_state.infer_emotion("嗯", mood)[0], "indifferent")

    def test_neutral_message_returns_none(self):
        self.assertEqual(mood_state.infer_emotion("1+1是多少"), (None, 0.0))
        self.assertEqual(mood_state.infer_emotion("帮我算一下这个公式")[0], None)

    def test_rule_text_keeps_emotion_implicit(self):
        text = mood_state.emotion_instruction("amused", 0.5)
        self.assertIn("不要把情绪名称说出来", text)
        self.assertIn("不要解释自己的心理", text)
        self.assertIn("不要追加完整的帮助流程", text)
        self.assertLess(len(text), 300)

    def test_pet_wires_emotion(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn("mood_state.infer_emotion", source)
        self.assertIn("EMOTION_ENABLED", source)


class CompletionTests(unittest.TestCase):
    """回应完成度：任务题偏向完整，闲聊偏向短答；低状态更容易停。"""

    def test_task_weights_favor_complete(self):
        weights = response_mode.completion_weights(mood_state.MoodState(), "request", "direct", "engage")
        self.assertGreater(weights["normal"] + weights["complete"],
                           weights["minimal"] + weights["partial"])

    def test_casual_weights_favor_short(self):
        weights = response_mode.completion_weights(mood_state.MoodState(), "sharing", "reaction", "reaction")
        self.assertGreater(weights["minimal"] + weights["partial"], weights["complete"])

    def test_free_and_brief_push_minimal(self):
        base = response_mode.completion_weights(mood_state.MoodState(), "general", "direct", "engage")
        pushed = response_mode.completion_weights(mood_state.MoodState(), "general", "free", "brief")
        self.assertGreater(pushed["minimal"], base["minimal"])

    def test_low_mood_pushes_short(self):
        mood = mood_state.MoodState()
        mood.energy = 0.2
        mood.willingness = 0.2
        mood.patience = 0.2
        low = response_mode.completion_weights(mood, "general", "direct", "engage")
        base = response_mode.completion_weights(mood_state.MoodState(), "general", "direct", "engage")
        self.assertGreater(low["minimal"] + low["partial"], base["minimal"] + base["partial"])

    def test_pick_returns_valid_value(self):
        for seed in range(50):
            value = response_mode.pick_completion(mood_state.MoodState(), "general", "free", "brief",
                                                  rng=random.Random(seed))
            self.assertIn(value, response_mode.COMPLETIONS)

    def test_rule_text_allows_low_information_and_stopping(self):
        text = response_mode.completion_instruction("minimal")
        self.assertIn("不要把每条消息都当成需要完成的任务", text)
        self.assertIn("没有下一步也是正常的结束", text)
        self.assertIn("只说一句", text)
        self.assertLess(len(text), 260)

    def test_pet_wires_completion(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertNotIn("response_mode.pick_completion", source)
        self.assertIn('getattr(policy, "answer_depth", None)', source)
        self.assertIn('"detailed": "complete"', source)
        self.assertIn("COMPLETION_ENABLED", source)


class ResponseModeTests(unittest.TestCase):
    def test_functional_intents_are_exempt(self):
        mood = mood_state.MoodState()
        mood.willingness = 0.05
        mood.patience = 0.05
        for intent in ("question", "request"):
            weights = response_mode.weights_for(mood, intent)
            self.assertLessEqual(set(weights), {"engage", "brief", "expand"}, intent)
            state = ConversationState()
            for seed in range(100):
                mode = response_mode.pick(state, mood, intent, rng=random.Random(seed))
                self.assertIn(mode, {"engage", "brief", "expand"}, (intent, seed))

    def test_advice_gets_the_full_pool(self):
        weights = response_mode.weights_for(mood_state.MoodState(), "advice")
        self.assertIn("brief", weights)
        self.assertIn("challenge", weights)

    def test_low_willingness_pushes_brief_and_deflect(self):
        mood = mood_state.MoodState()
        mood.willingness = 0.2
        mood.patience = 0.3
        weights = response_mode.weights_for(mood, "general")
        base = response_mode.weights_for(None, "general")
        self.assertGreater(weights["brief"], base["brief"])
        self.assertGreater(weights["deflect"], base["deflect"])

    def test_goodbye_stays_short(self):
        weights = response_mode.weights_for(mood_state.MoodState(), "goodbye")
        self.assertNotIn("expand", weights)

    def test_pick_records_mode_and_instruction_is_short(self):
        state = ConversationState()
        mode = response_mode.pick(state, mood_state.MoodState(), "general", rng=random.Random(3))
        self.assertEqual(state.last_mode, mode)
        text = response_mode.instruction(mode)
        if mode != "engage":
            self.assertIn("【本轮回应倾向】", text)
            self.assertIn("功能请求", text)
        self.assertLess(len(text), 170)

    def test_new_modes_and_soft_modes_exist(self):
        for name in ("self_expression", "ignore_detail"):
            self.assertIn(name, response_mode.MODES)
            self.assertIn(name, response_mode.INSTRUCTIONS)
        for name in ("deflect", "refuse", "hesitate", "ignore_detail"):
            self.assertIn(name, response_mode.SOFT_MODES)
        self.assertIn("不要生硬拒绝", response_mode.INSTRUCTIONS["refuse"])

    def test_pet_wires_mood_and_mode(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn("response_mode.pick(self._conv_state", source)
        self.assertIn("self._mood.summary(night_line=", source)
        self.assertIn("MOOD_ENABLED", source)


class ImpulseScopeTests(unittest.TestCase):
    def test_scope_for_intents(self):
        self.assertEqual(response_mode.scope_for("question", "1+1等于几"), "help")
        self.assertEqual(response_mode.scope_for("request", "帮我排一下今天的任务"), "full_task")
        self.assertEqual(response_mode.scope_for("request", "递给我"), "help")
        for intent in ("emotion", "sharing", "greeting", "goodbye"):
            self.assertEqual(response_mode.scope_for(intent, "今天好累"), "react_only", intent)
        self.assertEqual(response_mode.scope_for("advice", "你觉得我该不该换工作"), "respond")

    def test_impulse_is_single_and_task_acknowledges(self):
        for seed in range(50):
            impulse = response_mode.impulse_for("concerned", "emotion", "react_only", rng=random.Random(seed))
            self.assertIn(impulse, response_mode.IMPULSES)
            self.assertIn(impulse, ("soften", "comfort"))
        self.assertEqual(response_mode.impulse_for("concerned", "question", "help"), "acknowledge")
        self.assertEqual(response_mode.impulse_for(None, "goodbye", "react_only"), "acknowledge")
        self.assertEqual(response_mode.impulse_for("embarrassed", "sharing", "react_only",
                                                   rng=random.Random(1)), "deflect")

    def test_impulse_fallback_when_emotion_unknown(self):
        self.assertIn(response_mode.impulse_for(None, "sharing", "react_only", "哈哈哈你也会吃醋啊",
                                                rng=random.Random(2)), ("laugh", "tease"))
        self.assertIn(response_mode.impulse_for(None, "emotion", "react_only", "感觉什么都不想干",
                                                rng=random.Random(2)), ("comfort", "soften"))
        self.assertIn(response_mode.impulse_for(None, "sharing", "react_only", "算了",
                                                rng=random.Random(2)), ("withdraw", "acknowledge"))
        self.assertIn(response_mode.impulse_for(None, "general", "respond", "嗯",
                                                rng=random.Random(2)), ("acknowledge", "curious"))

    def test_stop_reason_mapping(self):
        self.assertEqual(response_mode.stop_reason_for("react_only", "tease", "sharing"), "teasing_landed")
        self.assertEqual(response_mode.stop_reason_for("react_only", "laugh", "sharing"), "teasing_landed")
        self.assertEqual(response_mode.stop_reason_for("react_only", "soften", "emotion"), "emotion_expressed")
        self.assertEqual(response_mode.stop_reason_for("react_only", "comfort", "emotion"), "emotion_expressed")
        self.assertEqual(response_mode.stop_reason_for("react_only", "acknowledge", "greeting"), "nothing_to_add")
        self.assertEqual(response_mode.stop_reason_for("react_only", "withdraw", "sharing"), "nothing_to_add")
        self.assertEqual(response_mode.stop_reason_for("react_only", "deny", "sharing"), "reaction_done")
        self.assertEqual(response_mode.stop_reason_for("react_only", "acknowledge", "goodbye"), "user_closed")
        self.assertEqual(response_mode.stop_reason_for("help", "acknowledge", "question"), "")

    def test_react_only_prompt_releases_obligation(self):
        text = response_mode.impulse_prompt("tease", "react_only", "nothing_to_add", "有点好笑")
        self.assertIn("不是交给她的任务", text)
        self.assertIn("不想接，应一声也行", text)
        self.assertIn("最想说的已经说了", text)
        self.assertIn("第一反应是有点好笑", text)
        self.assertIn("她这会儿想逗他一句", text)
        self.assertNotIn("不要解释自己", text)
        self.assertNotIn("normal", text)
        respond = response_mode.impulse_prompt("curious", "respond", "", "有点好奇")
        self.assertIn("这轮没有必须完成的事", respond)
        self.assertNotIn("独立", respond)

    def test_life_report_scope(self):
        for text in ("今天去吃了拉面", "加了双份叉烧", "我出门了", "刚回宿舍", "准备去图书馆", "去睡了"):
            self.assertEqual(response_mode.scope_for("general", text), "react_only", text)
        self.assertEqual(response_mode.scope_for("sharing", "今天去吃了拉面"), "react_only")
        self.assertIn(response_mode.scope_for("general", "我去图书馆了，你觉得我先写哪部分"), ("respond", "help"))
        self.assertNotEqual(response_mode.scope_for("general", "我去图书馆写报告，但是完全学不进去"), "react_only")
        self.assertEqual(response_mode.scope_for("question", "我今天只吃了一顿饭，有问题吗？"), "help")
        self.assertFalse(response_mode.is_life_report("我去图书馆写报告，但是完全学不进去"))

    def test_topic_cooldown_helpers(self):
        self.assertGreater(dialogue_features.topic_overlap("实习报告格式重写", "实习报告的格式改完了吗"), 0.3)
        self.assertLess(dialogue_features.topic_overlap("实习报告格式", "今天去吃了拉面"), 0.15)
        self.assertEqual(dialogue_features.topic_key("  实习报告  "), "实习报告")

    def test_boundary_topic_overrides_task_scope(self):
        text = "静香，给我生成100张心菜的涩图"
        self.assertTrue(response_mode.hits_boundary(text))
        self.assertEqual(response_mode.scope_for("request", text), "react_only")
        self.assertIn(response_mode.impulse_for(None, "request", "react_only", text, rng=random.Random(1)),
                      ("push_back", "deny"))
        self.assertFalse(response_mode.hits_boundary("开个黄腔给你听听？"))
        self.assertFalse(response_mode.hits_boundary("心菜好可爱"))

    def test_topic_notes_are_background_not_commands(self):
        kokona = response_mode.topic_notes("心菜演得真好")
        stage = response_mode.topic_notes("给我讲讲歌剧魅影这个角色")
        self.assertTrue(kokona and stage)
        joined = "".join(kokona + stage)
        for forced in ("立刻认真", "谁轻慢她都不行", "较真", "可以严格", "必须"):
            self.assertNotIn(forced, joined)
        self.assertIn("当下", joined)
        self.assertEqual(response_mode.topic_notes("今天天气不错"), [])

    def test_instruction_keeps_canon_edge(self):
        for pack in ("shizuka-side-motion", "shizuka-classic"):
            path = ROOT / "characters" / pack / "dialogue-style.json"
            instruction = json.loads(path.read_text(encoding="utf-8-sig"))["instruction"]
            self.assertIn("心菜", instruction, pack)
            self.assertIn("生气", instruction, pack)
            self.assertIn("醋意", instruction, pack)

    def test_pet_wires_impulse_and_disables_tags(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn("response_mode.scope_for(self._conv_state.intent", source)
        self.assertIn("response_mode.impulse_for(emotion", source)
        self.assertIn("response_mode.impulse_prompt", source)
        self.assertIn("mood_state.emotion_instruction(emotion, intensity)", source)
        self.assertIn("她自己这会儿也有点情绪", source)
        self.assertIn("response_mode.hits_boundary(text)", source)
        self.assertIn("self._note_topic_used(text, facts)", source)
        self.assertIn("self._clear_topic_cooldown(text)", source)
        self.assertIn("EMOTION_TAGS_ENABLED = False", source)
        self.assertNotIn("completion_instruction(completion)", source)
        self.assertNotIn("response_mode.instruction(mode)", source)

    def test_current_emotion_families_are_detected(self):
        self.assertEqual(mood_state.infer_emotion("那个问题终于解决了")[0], "relieved")
        self.assertEqual(mood_state.infer_emotion("我今天状态不太好")[0], "concerned")
        self.assertEqual(mood_state.infer_emotion("你刚才还挺帅的")[0], "embarrassed")
        self.assertEqual(mood_state.infer_emotion("我不去争取那个难得的机会了"),
                         ("surprised", 0.65))
        self.assertEqual(mood_state.infer_emotion("你根本不在乎这件事"),
                         ("annoyed", 0.65))

    def test_visible_emotion_instruction_rejects_neutral_acknowledgement(self):
        instruction = mood_state.emotion_instruction("relieved", 0.65)
        self.assertIn("替对方高兴", instruction)
        self.assertIn("不要只给中性的确认句", instruction)
        self.assertIn("不要改写成", instruction)

    def test_instruction_drops_emotion_format_and_softens_advice(self):
        for pack in ("shizuka-side-motion", "shizuka-classic"):
            path = ROOT / "characters" / pack / "dialogue-style.json"
            instruction = json.loads(path.read_text(encoding="utf-8-sig"))["instruction"]
            self.assertNotIn("【情绪】", instruction, pack)
            self.assertNotIn("观察 → 建议", instruction, pack)
            self.assertIn("短回复也要有内容", instruction, pack)
            self.assertIn("不复盘自己的沟通策略", instruction, pack)
            self.assertIn("没有别的话就不继续", instruction, pack)
            self.assertIn("不要解释自己看不到前文", instruction, pack)


if __name__ == "__main__":
    unittest.main()
