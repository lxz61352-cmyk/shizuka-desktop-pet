"""journal 压实：本地读走「快照 + 热事件」，但对外仍是完整历史（信封不变、对端不缺事件）。
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sync_store import SyncStore, Snapshot  # noqa: E402
from sync_bridge import SyncBridge  # noqa: E402


class CompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SyncStore(self.root / "a.db", device="a")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def seed(self):
        self.store.commit_snapshot("memories", [
            {"id": "m1", "content": "第一条", "pinned": False, "created": 1},
            {"id": "m2", "content": "第二条", "pinned": True, "created": 2},
        ], Snapshot())
        self.store.commit_snapshot("todos", [{"id": "t1", "text": "给妈妈打电话", "done": False}], Snapshot())
        self.store.commit_snapshot("chats", [{"id": "c1", "role": "user", "text": "你好", "kind": "chat",
                                              "created": 3}], Snapshot(), delete_missing=False)

    def test_reads_are_identical_before_and_after_compaction(self):
        self.seed()
        before = {name: self.store.rows(name) for name in ("memories", "todos", "chats")}
        self.assertEqual(self.store.compact()["moved"], 4)
        after = {name: self.store.rows(name) for name in ("memories", "todos", "chats")}
        self.assertEqual(before, after)

    def test_hot_table_is_emptied_but_history_is_kept(self):
        self.seed()
        bundle_before = self.store.bundle()
        self.store.compact()
        self.assertEqual(self.store._events(), [])
        bundle_after = self.store.bundle()
        # 对外仍然是完整事件流：只是搬到了归档冷表，没有任何事件消失。
        self.assertEqual(len(bundle_after["events"]), len(bundle_before["events"]))
        self.assertEqual(bundle_after["events"], bundle_before["events"])

    def test_tombstones_survive_compaction(self):
        self.seed()
        self.store.commit_snapshot("memories", [{"id": "m1", "content": "第一条", "pinned": False, "created": 1}],
                                   self.store.rows("memories"))
        self.assertEqual([row["id"] for row in self.store.rows("memories")], ["m1"])
        stale = self.store.bundle()
        self.store.compact()
        self.assertEqual([row["id"] for row in self.store.rows("memories")], ["m1"])
        # 对端重发压实前的旧包（含 m2 的创建事件）也不能把已删除的记录复活
        self.assertEqual(self.store.import_bundle(stale), 0)
        self.assertEqual([row["id"] for row in self.store.rows("memories")], ["m1"])

    def test_new_edits_after_compaction_are_visible(self):
        self.seed()
        self.store.compact()
        before = self.store.rows("memories")
        desired = deepcopy(list(before))
        desired[0]["content"] = "压实之后改的"
        self.store.commit_snapshot("memories", desired, before)
        self.assertEqual(self.store.rows("memories")[0]["content"], "压实之后改的")
        self.assertEqual(len(self.store.rows("memories")), 2)

    def test_sequence_does_not_restart_after_compaction(self):
        self.seed()
        self.store.compact()
        before = self.store._vector()["a"]
        self.store.commit_snapshot("todos", [{"id": "t2", "text": "新待办", "done": False}],
                                   Snapshot([{"id": "t1", "text": "给妈妈打电话", "done": False}]))
        added = [row for row in self.store.rows("todos") if row["id"] == "t2"]
        self.assertEqual(len(added), 1)
        self.assertGreater(self.store._vector()["a"], before)
        # 新事件的 seq 必须大于归档里的旧 seq，否则会和归档主键撞车
        self.assertTrue(all(e["seq"] > before for e in self.store._events()))

    def test_collision_detection_still_covers_archived_events(self):
        self.seed()
        archived = self.store.bundle()["events"][0]
        self.store.compact()
        # 同 (device,seq) 不同内容 → 仍然报“不要克隆本地同步库”
        with self.assertRaises(ValueError):
            self.store._insert({**archived, "patch": {"content": "被篡改的内容"}})
        # 同 (device,seq) 同内容 → 幂等，不算新增
        self.assertFalse(self.store._insert(archived))

    def test_conflicts_are_still_detected_across_compaction(self):
        other = SyncStore(self.root / "b.db", device="b")
        try:
            self.store.commit_snapshot("memories", [{"id": "m1", "content": "起点", "pinned": False}], Snapshot())
            other.import_bundle(self.store.bundle())
            for store in (self.store, other):
                observed = store.rows("memories")
                desired = deepcopy(list(observed))
                desired[0]["content"] = "各改各的-" + store.device
                store.commit_snapshot("memories", desired, observed)
            other.import_bundle(self.store.bundle())
            self.store.import_bundle(other.bundle())
            self.assertTrue(self.store.conflicts())
            self.store.compact()
            self.assertTrue(self.store.conflicts(), "压实后仍要能报出并发冲突")
        finally:
            other.close()   # Windows 上必须先关库，否则临时目录删不掉

    def test_compaction_is_idempotent(self):
        self.seed()
        self.store.compact()
        first = self.store.rows("memories")
        result = self.store.compact()
        self.assertEqual(result["moved"], 0)
        self.assertEqual(self.store.rows("memories"), first)

    def test_maybe_compact_respects_the_threshold(self):
        self.seed()
        self.assertIsNone(self.store.maybe_compact(threshold=1000))
        self.assertTrue(self.store._events())
        self.assertIsNotNone(self.store.maybe_compact(threshold=1))
        self.assertEqual(self.store._events(), [])


class BridgeCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bridge_checks_periodically_and_survives_failure(self):
        bridge = SyncBridge(self.root, "shizuka")
        try:
            with patch.object(SyncBridge, "COMPACT_CHECK_EVERY", 3), \
                 patch.object(type(bridge.store), "maybe_compact", return_value="compacted") as checker:
                for index in range(5):
                    bridge.commit("chats", [{"id": f"c{index}", "role": "user", "text": "hi",
                                             "kind": "chat", "created": index}], Snapshot())
                self.assertEqual(checker.call_count, 1)   # 每 3 次提交检查一次

            with patch.object(SyncBridge, "COMPACT_CHECK_EVERY", 1), \
                 patch.object(type(bridge.store), "maybe_compact", side_effect=RuntimeError("boom")):
                bridge.commit("chats", [], Snapshot())
                self.assertEqual(bridge.compact_error, "RuntimeError")
                self.assertIn("compact_error", bridge.status())
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
