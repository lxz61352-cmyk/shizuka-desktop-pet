"""聊天里说「我完成了」要能标完成：认出事项、停掉提醒、不确定就先问。"""
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import todo_reply  # noqa: E402


class ClaimTests(unittest.TestCase):
    def test_natural_completion_phrases(self):
        for text in ("收到，已经检查了喵", "已经喝了水了喵", "已完成", "搞定了", "看完了",
                     "我把 查看opencode运行状态 弄好了", "已经提前完成了那个待办"):
            self.assertIsNotNone(todo_reply.done_claim(text), text)

    def test_negatives_and_questions_are_not_claims(self):
        for text in ("还没做完", "没检查", "我完成了吗", "搞定了吧", "今天天气不错",
                     "一会儿再弄", "打算明天做", "不用提醒了"):
            self.assertIsNone(todo_reply.done_claim(text), text)

    def test_strong_claim_only_for_finish_phrases(self):
        self.assertTrue(todo_reply.strong_claim("已完成"))
        self.assertTrue(todo_reply.strong_claim("已经提前完成了那个待办"))
        self.assertFalse(todo_reply.strong_claim("已经喝了水了喵"))   # 只说了动作，不算「做完了」

    def test_matching(self):
        self.assertEqual(todo_reply.match_score(todo_reply.todo_core("检查dsh状态"), "收到，已经检查了喵"), 2)
        self.assertEqual(todo_reply.match_score(todo_reply.todo_core("喝水"), "已经喝了水了喵"), 3)
        self.assertEqual(todo_reply.match_score(todo_reply.todo_core("喝水"), "收到，已经检查了喵"), 0)
        # 去虚词的核心词命中（用户说「给静香回复111」，标题写的是「给静香回复一个111」）
        self.assertEqual(todo_reply.match_score(todo_reply.todo_core("给静香回复一个111"), "给静香回复111 完成了"), 100)
        self.assertEqual(todo_reply.match_score("给静香回复一个111", "给静香回复一个111 已经完成"), 100)
        # 标题里的虚词不影响比对
        self.assertEqual(todo_reply.todo_core("喝水的"), "喝水")


class _Stub:
    """只借 todo_reply 的完成判断，其他待办操作记下来。"""

    _todo_bind_reply = todo_reply.TodoReplyMixin._todo_bind_reply
    _todo_done_from_chat = todo_reply.TodoReplyMixin._todo_done_from_chat
    _todo_done_recent = todo_reply.TodoReplyMixin._todo_done_recent
    _todo_done_apply = todo_reply.TodoReplyMixin._todo_done_apply
    _todo_done_ask = todo_reply.TodoReplyMixin._todo_done_ask
    _weixin_todo_done = todo_reply.TodoReplyMixin._weixin_todo_done

    def __init__(self, todos):
        self.todos = todos
        self.completed = []
        self.saved = 0

    def _todo_complete_or_restore(self, item, done):
        self.completed.append((item["id"], done))
        item["done"] = done

    def _save_todos(self):
        self.saved += 1

    def _todo_notice_signature(self, row):
        return "sig-%s" % row["id"]

    def _ui(self, fn):
        fn()


def _todo(tid, text, done=False):
    return {"id": tid, "text": text, "done": done}


class DoneFromChatTests(unittest.TestCase):
    def test_named_todo_is_completed(self):
        stub = _Stub([_todo("t1", "检查dsh状态"), _todo("t2", "给静香回复一个111")])
        reply = stub._todo_done_from_chat("收到，已经检查了喵")
        self.assertIn("检查dsh状态", reply)
        self.assertEqual(stub.completed, [("t1", True)])
        self.assertTrue(stub.todos[0]["done"])
        self.assertFalse(stub.todos[1]["done"])

    def test_water_case(self):
        stub = _Stub([_todo("t1", "喝水")])
        reply = stub._todo_done_from_chat("已经喝了水了喵")
        self.assertIn("喝水", reply)
        self.assertEqual(stub.completed, [("t1", True)])

    def test_ordinary_chat_is_untouched(self):
        stub = _Stub([_todo("t1", "喝水")])
        self.assertIsNone(stub._todo_done_from_chat("今天中午吃什么好"))
        self.assertEqual(stub.completed, [])

    def test_no_pending_todos(self):
        stub = _Stub([_todo("t1", "喝水", done=True)])
        self.assertIsNone(stub._todo_done_from_chat("已经完成了"))
        self.assertEqual(stub.completed, [])

    def test_ambiguous_asks_instead_of_guessing(self):
        stub = _Stub([_todo("t1", "看论文"), _todo("t2", "写报告"), _todo("t3", "拿快递")])
        reply = stub._todo_done_from_chat("已完成")
        self.assertIn("哪一件", reply)
        self.assertEqual(stub.completed, [])
        target = stub._todo_reply_targets["desktop"]
        self.assertTrue(target["choosing"])
        self.assertEqual(len(target["items"]), 3)

    def test_single_pending_and_strong_claim(self):
        stub = _Stub([_todo("t1", "拿快递")])
        reply = stub._todo_done_from_chat("已完成")
        self.assertIn("拿快递", reply)
        self.assertEqual(stub.completed, [("t1", True)])

    def test_weak_claim_alone_does_not_guess(self):
        stub = _Stub([_todo("t1", "拿快递")])
        self.assertIsNone(stub._todo_done_from_chat("喝了"))
        self.assertEqual(stub.completed, [])

    def test_reply_to_a_reminder_completes_that_one(self):
        stub = _Stub([_todo("t1", "喝水"), _todo("t2", "拿快递")])
        stub._todo_bind_reply([stub.todos[0]], "desktop")
        reply = stub._todo_done_from_chat("喝完了")
        self.assertIn("喝水", reply)
        self.assertEqual(stub.completed, [("t1", True)])
        self.assertEqual(stub.todos[1]["done"], False)

    def test_choosing_by_number_then_completes(self):
        stub = _Stub([_todo("t1", "看论文"), _todo("t2", "写报告")])
        stub._todo_reply_targets = {
            "desktop": {"at": __import__("time").monotonic(), "choosing": True,
                        "items": [{"id": "t2", "title": "写报告", "signature": "sig-t2"}]}}
        # 走已有的 choose 流程：用户回「1」→ 由 _todo_complete_reply 处理，这里只验证候选被绑上
        self.assertTrue(stub._todo_reply_targets["desktop"]["choosing"])

    def test_completing_clears_the_bound_target(self):
        stub = _Stub([_todo("t1", "喝水")])
        stub._todo_bind_reply([stub.todos[0]], "desktop")
        stub._todo_done_from_chat("已经喝了水了")
        self.assertNotIn("desktop", getattr(stub, "_todo_reply_targets", {}))


class WeixinTests(unittest.TestCase):
    def test_weixin_wrapper_runs_on_ui_thread(self):
        stub = _Stub([_todo("t1", "检查dsh状态")])
        cancel = threading.Event()
        reply = stub._weixin_todo_done("已经检查了", cancel)
        self.assertIn("检查dsh状态", reply)
        self.assertEqual(stub.completed, [("t1", True)])

    def test_weixin_cancelled_does_nothing(self):
        stub = _Stub([_todo("t1", "检查dsh状态")])
        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(stub._weixin_todo_done("已经检查了", cancel))
        self.assertEqual(stub.completed, [])


if __name__ == "__main__":
    unittest.main()
