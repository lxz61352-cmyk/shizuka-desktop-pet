"""聊天里问最新进展的汇报、称呼规则、关注方向标签的换行排布。"""
from pathlib import Path
import sys
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import assistant_features  # noqa: E402
import intent_routing  # noqa: E402
import pet  # noqa: E402
import todo_reply  # noqa: E402
import todo_voice  # noqa: E402


class ResearchRoutingTests(unittest.TestCase):
    def test_progress_questions_are_local(self):
        for text in ("最新进展", "最近有什么新论文", "有没有新文献", "帮我查查最新的文献",
                     "最近的研究动态怎么样", "有什么新论文吗"):
            self.assertEqual(intent_routing.local_intent(text), {'action': 'research'}, text)

    def test_specific_papers_are_not_hijacked(self):
        for text in ("这篇论文的最新进展", "刚才那篇文献讲了什么", "怎么查最新的论文"):
            self.assertNotEqual(intent_routing.local_intent(text), {'action': 'research'}, text)

    def test_plain_chat_stays_chat(self):
        for text in ("最近怎么样", "你在研究什么"):
            self.assertEqual(intent_routing.local_intent(text), {'action': 'chat'}, text)

    def test_other_topics_go_to_the_router(self):
        # 天气/新闻、以及没带「最新/最近」的「研究进展」，都交给模型路由器判断
        for text in ("今天天气怎么样", "最近有什么新闻", "研究进展如何"):
            self.assertNotEqual(intent_routing.local_intent(text), {'action': 'research'}, text)

    def test_long_or_empty_text_goes_to_router(self):
        self.assertFalse(intent_routing.research_question("帮我看看最近这个方向有什么值得读的新论文并总结一下要点"))
        self.assertFalse(intent_routing.research_question(""))


class _State:
    def __init__(self, alerts=(), checked_at=0):
        self._research = types.SimpleNamespace(
            profile={"topics": ["偏微分方程数值解"], "enabled": True},
            state={"alerts": list(alerts), "checked_at": checked_at, "errors": [], "evaluated": {}})
        self.said = []

    def say(self, text, **kwargs):
        self.said.append(text)
        return True


def _alert(title, journal="J. Test", comment="这条跟你的方向很接近。"):
    return {"title": title, "journal": journal, "comment": comment, "summary": "s", "reason": "r",
            "url": "https://doi.org/10.1/x", "doi": "10.1/x", "date": "2024-05-01",
            "evidence_basis": "abstract", "notified": False}


class ReportTextTests(unittest.TestCase):
    def _report(self, stub):
        return assistant_features.AssistantFeaturesMixin._research_report_text(
            stub, stub._research.profile["topics"])

    def test_no_alerts_says_so_and_promises_a_look(self):
        stub = _State(checked_at=time.time())
        text = self._report(stub)
        self.assertIn("偏微分方程数值解", text)
        self.assertIn("还没有", text)
        self.assertIn("再去看一遍", text)

    def test_titles_are_wrapped_in_book_marks(self):
        stub = _State(alerts=[_alert("Deep Learning for PDEs")], checked_at=time.time())
        text = self._report(stub)
        self.assertIn("《Deep Learning for PDEs》", text)
        self.assertIn("J. Test", text)
        # 书名号标题在朗读时会单独占一轮气泡
        self.assertTrue(pet._looks_like_title("《Deep Learning for PDEs》"))

    def test_only_the_newest_few_are_reported(self):
        alerts = [_alert("Paper %d" % i) for i in range(6)]
        stub = _State(alerts=alerts, checked_at=time.time())
        text = self._report(stub)
        self.assertIn("Paper 5", text)
        self.assertIn("Paper 4", text)
        self.assertNotIn("Paper 0", text)
        self.assertLessEqual(len(text), 2 * assistant_features.RESEARCH_REPORT_NOTE + 400)

    def test_long_comment_is_trimmed(self):
        stub = _State(alerts=[_alert("T", comment="很长的评论。" * 60)], checked_at=time.time())
        text = self._report(stub)
        self.assertLessEqual(len(text), assistant_features.RESEARCH_REPORT_NOTE + 300)

    def test_trim_note_cuts_at_punctuation(self):
        note = assistant_features.trim_note("第一句就这样结束了。第二句很长" + "很长" * 40 + "，还有后半段。")
        self.assertTrue(note.endswith("。") or note.endswith("…"), note)
        self.assertLessEqual(len(note), assistant_features.RESEARCH_REPORT_NOTE + 1)
        self.assertEqual(assistant_features.trim_note("短句。"), "短句。")
        self.assertEqual(assistant_features.trim_note(""), "")


class ReportFlowTests(unittest.TestCase):
    def test_no_topics_guides_to_the_window(self):
        calls = []
        stub = types.SimpleNamespace(_research=types.SimpleNamespace(profile={"topics": []}),
                                     _research_init=lambda: None,
                                     show_research=lambda: calls.append("window"),
                                     say=lambda text, **k: calls.append(text) or True,
                                     _research_running=False)
        assistant_features.AssistantFeaturesMixin._report_research(stub)
        self.assertIn("window", calls)
        self.assertTrue(any("方向" in c for c in calls if isinstance(c, str)))

    def test_check_in_progress_says_so(self):
        said = []
        stub = types.SimpleNamespace(_research=types.SimpleNamespace(profile={"topics": ["x"]}),
                                     _research_init=lambda: None, _research_running=True,
                                     say=lambda text, **k: said.append(text) or True)
        assistant_features.AssistantFeaturesMixin._report_research(stub)
        self.assertTrue(said and "正在查" in said[0])


class FlowLayoutTests(unittest.TestCase):
    class _Board:
        def __init__(self):
            self.height = None
            self.propagate = None

        def update_idletasks(self):
            pass

        def pack_propagate(self, flag):
            self.propagate = flag

        def configure(self, **kwargs):
            if "height" in kwargs:
                self.height = kwargs["height"]

    class _Widget:
        def __init__(self, width, height=20):
            self.width = width
            self.height = height
            self.spot = None

        def winfo_reqwidth(self):
            return self.width

        def winfo_reqheight(self):
            return self.height

        def place(self, **kwargs):
            self.spot = kwargs

    def _layout(self, widths, budget):
        widgets = [self._Widget(w) for w in widths]
        board = self._Board()
        rows, columns = assistant_features.AssistantFeaturesMixin._flow_layout(board, widgets, budget)
        return widgets, board, rows, columns

    def test_wraps_when_the_row_is_full(self):
        widgets, board, rows, columns = self._layout([100, 100, 100, 100], 250)
        self.assertEqual((rows, columns), (2, 2))
        self.assertEqual([w.spot["x"] for w in widgets], [0, 106, 0, 106])
        self.assertEqual([w.spot["y"] for w in widgets], [0, 0, 24, 24])
        self.assertEqual(board.height, 44)      # 两行：20+4+20
        self.assertFalse(board.propagate)       # place 的控件不参与父容器请求尺寸

    def test_wide_widget_gets_its_own_row(self):
        widgets, _, rows, _ = self._layout([80, 600, 80], 400)
        self.assertEqual(rows, 3)
        self.assertEqual([w.spot["y"] for w in widgets], [0, 24, 48])

    def test_short_widgets_share_one_row(self):
        widgets, board, rows, columns = self._layout([80, 80, 80], 400)
        self.assertEqual((rows, columns), (1, 3))
        self.assertEqual([w.spot["x"] for w in widgets], [0, 86, 172])
        self.assertEqual(board.height, 20)

    def test_single_widget_always_placed(self):
        widgets, _, rows, columns = self._layout([999], 240)
        self.assertEqual((rows, columns), (1, 1))
        self.assertEqual(widgets[0].spot, {"x": 0, "y": 0})


class ClipRouteTests(unittest.TestCase):
    def test_paper_links_go_to_the_paper_reader(self):
        self.assertEqual(pet._clip_route("https://arxiv.org/abs/2310.06825"), "paper")
        self.assertEqual(pet._clip_route("https://doi.org/10.1038/s41586-021-03819-2"), "paper")
        self.assertEqual(pet._clip_route("10.1016/j.jcp.2024.112345"), "paper")

    def test_other_clipboard_content_keeps_its_route(self):
        self.assertEqual(pet._clip_route("https://example.com/news"), "web")
        self.assertEqual(pet._clip_route("https://example.com/a.png"), "image-url")
        self.assertEqual(pet._clip_route("就是一段普通文字。"), "text")

    def test_long_text_with_a_doi_stays_text(self):
        text = "这是一段很长的复制内容，" * 20 + "里面提到 10.1016/j.jcp.2024.112345 这个号。"
        self.assertEqual(pet._clip_route(text), "text")


class AddressTests(unittest.TestCase):
    def test_persona_forbids_master(self):
        persona = pet.load_persona()
        self.assertIn("不喊「主人」", persona)
        self.assertNotIn("自然需要时称主人", persona)

    def test_literal_replies_dropped_master(self):
        self.assertNotIn("主人", todo_reply.TodoReplyMixin._todo_complete_reply.__doc__ or "")
        source = (ROOT / "src" / "todo_reply.py").read_text(encoding="utf-8")
        self.assertNotIn("主人", source)
        voice = (ROOT / "src" / "todo_voice.py").read_text(encoding="utf-8")
        self.assertNotIn("主人", voice)

    def test_reminder_lines_are_natural(self):
        text = todo_voice.local_reminder({"text": "喝水"}, {}, time.time())
        self.assertNotIn("主人", text)
        self.assertIn("喝水", text)


if __name__ == "__main__":
    unittest.main()
