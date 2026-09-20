"""记忆提取：quote 必须来自用户原话（防编造），落库用改写后的事实；旧记忆可手动整理。"""
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import memory_maintenance as mm  # noqa: E402
import pet  # noqa: E402


def rows():
    return [{"id": "u1", "role": "user", "text": "我准备考研，还有90天就要初试了，最近在补数学基础", "created": 1},
            {"id": "a1", "role": "assistant", "text": "加油，我陪着你", "created": 2}]


class GroundedFactsTests(unittest.TestCase):
    def test_uses_rewritten_fact_as_content(self):
        payload = {"memories": [{"source_id": "u1", "quote": "我准备考研，还有90天就要初试了",
                                 "fact": "用户准备考研，距初试约 90 天", "stable": True}]}
        out = mm.grounded_facts(payload, rows())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["content"], "用户准备考研，距初试约 90 天")
        self.assertEqual(out[0]["quote"], "我准备考研，还有90天就要初试了")
        self.assertEqual(out[0]["source_id"], "u1")

    def test_falls_back_to_quote_without_fact(self):
        payload = {"memories": [{"source_id": "u1", "quote": "最近在补数学基础", "stable": True}]}
        self.assertEqual(mm.grounded_facts(payload, rows())[0]["content"], "最近在补数学基础")

    def test_rejects_quote_not_in_user_message(self):
        payload = {"memories": [{"source_id": "u1", "quote": "用户是研究生",
                                 "fact": "用户是研究生", "stable": True}]}
        self.assertEqual(mm.grounded_facts(payload, rows()), [])

    def test_rejects_assistant_source_and_unstable(self):
        self.assertEqual(mm.grounded_facts({"memories": [{"source_id": "a1", "quote": "加油", "stable": True}]},
                                           rows()), [])
        self.assertEqual(mm.grounded_facts({"memories": [{"source_id": "u1", "quote": "最近在补数学基础",
                                                          "stable": False}]}, rows()), [])

    def test_overlong_fact_falls_back_to_quote(self):
        payload = {"memories": [{"source_id": "u1", "quote": "最近在补数学基础",
                                 "fact": "x" * 200, "stable": True}]}
        self.assertEqual(mm.grounded_facts(payload, rows())[0]["content"], "最近在补数学基础")


class RewriteTests(unittest.TestCase):
    def make_store(self):
        store = pet.MemoryStore.__new__(pet.MemoryStore)
        store.items = [{"id": "m1", "content": "我准备考研", "pinned": False, "use_count": 0,
                        "created": 1, "last_used": 1}]
        store._lock = threading.RLock()
        return store

    def test_rewrite_changes_content_only(self):
        store = self.make_store()
        self.assertEqual(store.rewrite({"m1": "用户正在准备考研"}), 1)
        self.assertEqual(store.items[0]["content"], "用户正在准备考研")
        self.assertEqual(store.items[0]["pinned"], False)

    def test_rewrite_skips_bad_or_unchanged(self):
        store = self.make_store()
        self.assertEqual(store.rewrite({"m1": "短"}), 0)
        self.assertEqual(store.rewrite({"m1": "我准备考研"}), 0)
        self.assertEqual(store.rewrite({"m9": "用户在做别的"}), 0)
        self.assertEqual(store.items[0]["content"], "我准备考研")


class FactGuardTests(unittest.TestCase):
    """改写可以更简洁，但不许把原话的意思放大。"""

    def test_scope_upgrade_rejected(self):
        self.assertEqual(mm.fact_guard("用户长期偏好蓝色", "最近比较喜欢蓝色"), "scope_upgraded")

    def test_number_change_rejected(self):
        self.assertEqual(mm.fact_guard("用户距考研初试还有100天", "我准备考研，还有90天就要初试了"), "number_added")

    def test_invented_entity_rejected(self):
        self.assertEqual(mm.fact_guard("用户就读于东京大学", "我准备考研"), "low_overlap")

    def test_clean_fact_passes(self):
        self.assertIsNone(mm.fact_guard("用户准备考研，距初试约 90 天", "我准备考研，还有90天就要初试了"))

    def test_guard_failure_falls_back_to_quote(self):
        payload = {"memories": [{"source_id": "u1", "quote": "最近在补数学基础",
                                 "fact": "用户长期在补数学基础", "stable": True}]}
        out = mm.grounded_facts(payload, rows())
        self.assertEqual(out[0]["content"], "最近在补数学基础")
        self.assertEqual(out[0]["guard"], "scope_upgraded")

    def test_replaces_passed_through(self):
        payload = {"memories": [{"source_id": "u1", "quote": "最近在补数学基础",
                                 "fact": "用户正在补数学基础", "stable": True, "replaces": ["m1", 7, ""]}]}
        self.assertEqual(mm.grounded_facts(payload, rows())[0]["replaces"], ["m1"])


class SupersedeTests(unittest.TestCase):
    def make_store(self):
        store = pet.MemoryStore.__new__(pet.MemoryStore)
        store.items = [{"id": "m1", "content": "用户喜欢黑色", "pinned": False, "use_count": 0,
                        "created": 1, "last_used": 1, "status": "active",
                        "supersedes": [], "superseded_by": None}]
        store._lock = threading.RLock()
        return store

    def test_replaces_marks_old_superseded_and_links(self):
        store = self.make_store()
        self.assertTrue(store.add("用户现在喜欢白色", replaces=["m1"]))
        old = next(it for it in store.items if it["id"] == "m1")
        new = next(it for it in store.items if it["content"] == "用户现在喜欢白色")
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(new["supersedes"], ["m1"])
        self.assertEqual(new["status"], "active")

    def test_superseded_not_injected_but_kept(self):
        store = self.make_store()
        store.add("用户现在喜欢白色", replaces=["m1"])
        self.assertEqual(len(store.snapshot()), 2)
        self.assertNotIn("用户喜欢黑色", [it["content"] for it in store.injectable("")])

    def test_pinned_gets_reserved_slots(self):
        store = self.make_store()
        store.add("用户是长期置顶的记忆", pinned=True)
        for i in range(30):
            store.add("用户的其他信息 %d" % i)
        contents = [it["content"] for it in store.injectable("")]
        self.assertIn("用户是长期置顶的记忆", contents)
        self.assertLessEqual(len(contents), pet.MEMORY_INJECT_MAX)


class PendingRowsTests(unittest.TestCase):
    def test_skip_excludes_dead_letters(self):
        rows = [{"id": "u1", "role": "user", "text": "甲", "kind": "chat"},
                {"id": "a1", "role": "assistant", "text": "乙", "kind": "chat"},
                {"id": "u2", "role": "user", "text": "丙", "kind": "chat"},
                {"id": "a2", "role": "assistant", "text": "丁", "kind": "chat"}]
        got = [row["id"] for row in mm.pending_rows(rows, [], skip={"u1", "a1"})]
        self.assertEqual(got, ["u2", "a2"])


if __name__ == "__main__":
    unittest.main()
