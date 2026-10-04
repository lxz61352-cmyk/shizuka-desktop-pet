"""P2c-8 Phase 2：Shared History 原型（保存/去重更新/检索/最近使用）。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shizuka_shared_history import SharedHistoryStore  # noqa: E402


class SharedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = SharedHistoryStore(self.dir)

    def test_record_creates_entry(self):
        entry_id = self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"])
        self.assertTrue(entry_id)
        self.assertEqual(len(self.store.entries), 1)
        entry = self.store.entries[0]
        self.assertEqual(entry["mention_count"], 1)
        self.assertIn("报告", entry["topics"])
        self.assertIn("first_seen", entry)
        self.assertIn("last_seen", entry)

    def test_similar_record_updates_instead_of_appending(self):
        self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"])
        self.store.record("用户和静香之前讨论过实习报告的事", topics=["学校"])
        self.assertEqual(len(self.store.entries), 1)
        entry = self.store.entries[0]
        self.assertEqual(entry["mention_count"], 2)
        self.assertIn("学校", entry["topics"])

    def test_distinct_record_appends(self):
        self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"])
        self.store.record("用户以前反复拿某件小事开过玩笑", topics=["玩笑"])
        self.assertEqual(len(self.store.entries), 2)

    def test_match_finds_related_entry(self):
        self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"])
        hit = self.store.match("报告的格式改完了吗", topic="报告")
        self.assertIsNotNone(hit)
        self.assertIn("实习报告", hit["summary"])

    def test_match_returns_none_below_threshold(self):
        self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"])
        self.assertIsNone(self.store.match("今天的云很好看"))

    def test_touch_updates_counts_and_time(self):
        entry_id = self.store.record("用户和静香之前一起讨论过实习报告")
        self.assertTrue(self.store.touch(entry_id, now=123456.0))
        entry = self.store.entries[0]
        self.assertEqual(entry["mention_count"], 2)
        self.assertEqual(entry["last_seen"], 123456.0)

    def test_persistence_roundtrip(self):
        self.store.record("用户和静香之前一起讨论过实习报告", topics=["报告"], importance=0.7)
        reloaded = SharedHistoryStore(self.dir)
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0]["importance"], 0.7)

    def test_empty_summary_ignored(self):
        self.assertIsNone(self.store.record("  "))
        self.assertEqual(len(self.store.entries), 0)


if __name__ == "__main__":
    unittest.main()
