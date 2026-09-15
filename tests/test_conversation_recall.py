"""历史召回：只召回用户原话与自动摘要，且至少两个词重合，避免助手复述自己的旧回复。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import conversation_memory as cm

ASSISTANT_REPLY = "压力带要自己学会喘口气"
USER_WEAK = "我今天压力好大"
USER_STRONG = "压力带要怎么处理"
SUMMARY = "对话自动摘要（可核对原文）：用户提过压力"


def rows():
    def r(role, text, kind="chat", created=0):
        return {"id": "r%d" % created, "role": role, "kind": kind, "text": text, "created": created}
    return [
        r("assistant", ASSISTANT_REPLY, created=1),
        r("user", USER_WEAK, created=2),
        r("user", USER_STRONG, created=3),
        r("assistant", "嗯，我看看", created=4),
        r("assistant", SUMMARY, kind="memory_summary", created=5),
        r("user", "最近的闲聊", created=6),
        r("assistant", "好", created=7),
    ]


def texts(query, recent_count):
    return [e["text"] for e in cm.recall(rows(), query, recent_count)]


class RecallTests(unittest.TestCase):
    def test_assistant_replies_are_never_recalled(self):
        # 与「压力带」有两个词重合，但它是助手自己说过的话，不能当资料召回
        self.assertNotIn(ASSISTANT_REPLY, texts("压力带", 1))

    def test_single_word_overlap_is_not_enough(self):
        got = texts("压力带", 1)
        self.assertNotIn(USER_WEAK, got)   # 只有「压力」一个词重合
        self.assertIn(USER_STRONG, got)    # 「压力」「力带」两个词重合

    def test_summaries_are_always_recalled(self):
        self.assertIn(SUMMARY, texts("毫不相关的一句话", 1))

    def test_recent_turns_are_excluded(self):
        self.assertIn(USER_STRONG, texts("压力带要怎么处理", 1))
        self.assertNotIn(USER_STRONG, texts("压力带要怎么处理", 2))


if __name__ == "__main__":
    unittest.main()
