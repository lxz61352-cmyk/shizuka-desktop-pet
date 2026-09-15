"""Real two-journal regression tests; no network, pet GUI, API or credentials."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sync_store import SyncStore, Snapshot, stable_rows
from sync_bridge import SyncBridge, atomic_json


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = SyncStore(self.root / "a.db", device="a")
        self.b = SyncStore(self.root / "b.db", device="b")

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.tmp.cleanup()

    def exchange(self):
        self.a.import_bundle(self.b.bundle())
        self.b.import_bundle(self.a.bundle())

    def seed(self, collection="memories"):
        row = {"id": "m1", "content": "原记忆", "pinned": False, "created": 1}
        self.a.commit_snapshot(collection, [row], Snapshot())
        self.exchange()

    def test_offline_additions_merge_and_replay_is_idempotent(self):
        for store in (self.a, self.b):
            store.commit_snapshot("todos", [{"id": store.device, "text": "离线新增", "done": False}], Snapshot())
        self.exchange()
        self.assertEqual(len(self.a.rows("todos")), 2)
        self.assertEqual(self.a.rows("todos"), self.b.rows("todos"))
        self.assertEqual(self.a.import_bundle(self.b.bundle()), 0)

    def test_concurrent_different_fields_survive(self):
        self.seed()
        a, b = self.a.rows("memories"), self.b.rows("memories")
        aw, bw = deepcopy(a), deepcopy(b)
        aw[0]["content"] = "Windows 修改"
        bw[0]["pinned"] = True
        self.a.commit_snapshot("memories", aw, a)
        self.b.commit_snapshot("memories", bw, b)
        self.exchange()
        self.assertEqual(self.a.rows("memories"), self.b.rows("memories"))
        self.assertEqual(self.a.rows("memories")[0]["content"], "Windows 修改")
        self.assertTrue(self.a.rows("memories")[0]["pinned"])
        self.assertEqual(self.a.conflicts(), [])

    def test_same_field_conflict_retains_both_values(self):
        self.seed()
        for store in (self.a, self.b):
            before = store.rows("memories")
            desired = deepcopy(before)
            desired[0]["content"] = store.device
            store.commit_snapshot("memories", desired, before)
        self.exchange()
        self.assertEqual(self.a.rows("memories"), self.b.rows("memories"))
        conflicts = self.a.conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual({conflicts[0]["other"], conflicts[0]["selected"]}, {"a", "b"})

    def test_stale_ui_save_preserves_received_record_and_fields(self):
        self.seed()
        stale = self.a.rows("memories")
        b = self.b.rows("memories")
        desired = deepcopy(b)
        desired[0]["pinned"] = True
        desired.append({"id": "remote", "content": "来自 Mac"})
        self.b.commit_snapshot("memories", desired, b)
        self.a.import_bundle(self.b.bundle())
        edits = deepcopy(stale)
        edits[0]["content"] = "本地新编辑"
        self.a.commit_snapshot("memories", edits, stale)
        merged = {r["id"]: r for r in self.a.rows("memories")}
        self.assertEqual(len(merged), 2)
        self.assertTrue(merged["m1"]["pinned"])
        self.assertEqual(merged["m1"]["content"], "本地新编辑")

    def test_delete_wins_stale_edit_and_late_legacy_creation(self):
        self.seed()
        stale = self.b.rows("memories")
        self.a.commit_snapshot("memories", [], self.a.rows("memories"))
        edited = deepcopy(stale)
        edited[0]["content"] = "离线编辑"
        self.b.commit_snapshot("memories", edited, stale)
        self.exchange()
        self.assertEqual(self.a.rows("memories"), [])
        # Late migration of the same ID with a higher unrelated Lamport clock.
        incoming = self.b.bundle()
        incoming["events"] = [{"device": "late", "seq": 1, "logical": 500,
            "context": {}, "collection": "memories", "record": "m1",
            "patch": {"content": "老副本", "_deleted": False}}]
        self.a.import_bundle(incoming)
        self.assertEqual(self.a.rows("memories"), [])

    def test_invalid_bundle_is_atomic_and_character_isolated(self):
        self.seed()
        incoming = self.a.bundle()
        incoming["character"] = "other"
        with self.assertRaises(ValueError):
            self.b.import_bundle(incoming)
        incoming = self.a.bundle()
        e = deepcopy(incoming["events"][0])
        e.update(device="other", seq=1)
        incoming["events"].append(e)
        bad = deepcopy(e)
        bad.update(seq=2, patch={"api_key": "never sync credentials"})
        incoming["events"].append(bad)
        with self.assertRaises(ValueError):
            self.b.import_bundle(incoming)
        self.assertEqual(len(self.b.bundle()["events"]), 1)

    def test_journal_collision_rolls_back(self):
        self.seed()
        incoming = self.a.bundle()
        incoming["events"][0]["patch"]["content"] = "different same event ID"
        with self.assertRaises(ValueError):
            self.b.import_bundle(incoming)
        self.assertEqual(self.b.rows("memories")[0]["content"], "原记忆")

    def test_legacy_chat_ids_and_order_are_stable(self):
        old = [{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"}, {"role": "user", "text": "a"}]
        first = stable_rows("chats", old)
        self.assertEqual(first, stable_rows("chats", old))
        self.assertNotEqual(first[0]["id"], first[2]["id"])
        self.assertEqual([r["created"] for r in first], [0, 1, 2])
        self.assertEqual(first, stable_rows("chats", first))

    def test_invalid_local_data_does_not_enter_journal(self):
        for value in (None, "yesterday", float("nan")):
            with self.assertRaises(ValueError):
                self.a.commit_snapshot("memories", [{"id": "bad", "content": "x", "last_used": value}], [])
        self.assertEqual(self.a.rows("memories"), [])


class BridgeTests(unittest.TestCase):
    def test_migration_backup_restart_and_projections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = {"items": [{"id": "m1", "content": "记忆", "pinned": False}]}
            atomic_json(root / "characters/shizuka/memory.json", original)
            bridge = SyncBridge(root)
            device = bridge.store.device
            self.assertEqual(json.loads((root / "characters/shizuka/.sync/before-sync/memory.json").read_text("utf8")), original)
            before = bridge.read("memories")
            desired = deepcopy(before)
            desired[0]["content"] = "已更新"
            bridge.commit("memories", desired, before)
            bridge.close()
            bridge = SyncBridge(root)
            self.assertEqual(bridge.store.device, device)
            self.assertEqual(bridge.read("memories")[0]["content"], "已更新")
            bridge.close()

    def test_malformed_legacy_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "characters/shizuka/todos.json"
            path.parent.mkdir(parents=True)
            path.write_text("broken", encoding="utf8")
            with self.assertRaises(ValueError):
                SyncBridge(td)
            self.assertEqual(path.read_text(), "broken")

    def test_other_character_has_separate_directory(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = SyncBridge(td), SyncBridge(td, "new_character")
            a.commit("todos", [{"id": "t1", "text": "Shizuka"}], [])
            self.assertEqual(b.read("todos"), [])
            a.close()
            b.close()

    def test_clipped_chat_view_does_not_delete_older_history(self):
        with tempfile.TemporaryDirectory() as td:
            bridge = SyncBridge(td)
            chats = [{"id": "c" + str(n), "text": str(n), "created": n} for n in range(1002)]
            view = bridge.commit("chats", chats, [])
            self.assertEqual(len(view), 1002)
            bridge.commit("chats", view, view)
            self.assertEqual(len(bridge.store.rows("chats")), 1002)
            bridge.close()


if __name__ == "__main__":
    unittest.main()
