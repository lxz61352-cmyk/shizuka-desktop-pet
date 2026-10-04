"""记忆「已用」标记与退役（archived）行为。

背景（2026-09-30 审计）：`_refresh_memories` 原来要求记忆的**完整内容逐字出现在回复里**，
而静香是转述记忆的，78 条上一次都没命中过——`last_used` / `use_count` 从来没更新，
`injectable()` 里所有「按 last_used 降序」的排序都退化成按创建时间排序。
现在改成「本轮真正被选入请求的记忆即算已用」。
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402
from memory_lifecycle import active, label  # noqa: E402


def store_with(items):
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    Path(path).write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    store = pet.MemoryStore(path)
    return store, path


def item(ident, content, **extra):
    row = {"id": ident, "content": content, "pinned": False, "created": 1.0,
           "last_used": 1.0, "use_count": 0, "status": "active",
           "supersedes": [], "superseded_by": None}
    row.update(extra)
    return row


class MarkUsedTests(unittest.TestCase):
    def test_mark_used_updates_recency_and_count(self):
        store, path = store_with([item("m1", "用户所在城市是成都")])
        try:
            before = store.items[0]["last_used"]
            store.mark_used(["m1"])
            self.assertGreater(store.items[0]["last_used"], before)
            self.assertEqual(store.items[0]["use_count"], 1)
        finally:
            os.unlink(path)

    def test_mark_used_ignores_unknown_ids(self):
        store, path = store_with([item("m1", "用户所在城市是成都")])
        try:
            store.mark_used(["不存在"])
            self.assertEqual(store.items[0]["use_count"], 0)
        finally:
            os.unlink(path)


class ArchivedTests(unittest.TestCase):
    def test_archived_is_inactive_and_labelled(self):
        row = item("m1", "用户知道OW职业选手徐秋林外号雪神", status="archived")
        self.assertFalse(active(row))
        self.assertEqual(label(row), "已归档")

    def test_injectable_skips_archived(self):
        store, path = store_with([
            item("m1", "用户所在城市是成都"),
            item("m2", "用户知道OW职业选手徐秋林外号雪神", status="archived"),
        ])
        try:
            ids = {row["id"] for row in store.injectable("")}
            self.assertIn("m1", ids)
            self.assertNotIn("m2", ids)
        finally:
            os.unlink(path)

    def test_archived_pinned_item_is_still_skipped(self):
        store, path = store_with([
            item("m1", "用户所在城市是成都"),
            item("m2", "用户知道OW职业选手陈诚游戏名sunzo", pinned=True, status="archived"),
        ])
        try:
            ids = {row["id"] for row in store.injectable("")}
            self.assertNotIn("m2", ids, "退役条目即使置顶也不该再进入请求")
        finally:
            os.unlink(path)


class RefreshWiringTests(unittest.TestCase):
    """_refresh_memories 标记的是「本轮注入的」，且一次注入只计一次。"""

    def _call(self, recorded):
        marked = {}

        class FakeMemory:
            def mark_used(self, ids):
                marked["ids"] = list(ids)

        stub = types.SimpleNamespace(_memories_in_context=list(recorded))
        with mock.patch.object(pet, "get_memory", lambda: FakeMemory()):
            pet.DeskPet._refresh_memories(stub, "随便一句回复")
        return stub, marked

    def test_marks_recorded_ids(self):
        stub, marked = self._call(["m1", "m2"])
        self.assertEqual(marked["ids"], ["m1", "m2"])
        self.assertEqual(stub._memories_in_context, [], "标记后必须清空，避免重复计数")

    def test_no_injection_means_no_marking(self):
        stub, marked = self._call([])
        self.assertNotIn("ids", marked)

    def test_missing_attribute_is_tolerated(self):
        marked = {}

        class FakeMemory:
            def mark_used(self, ids):
                marked["ids"] = list(ids)

        stub = types.SimpleNamespace()
        with mock.patch.object(pet, "get_memory", lambda: FakeMemory()):
            pet.DeskPet._refresh_memories(stub, "x")
        self.assertNotIn("ids", marked)


class SourceGuardTests(unittest.TestCase):
    """把接线钉住：改回逐字匹配会让 last_used 再次失效。"""

    def setUp(self):
        self.src = (ROOT / "src/pet.py").read_text(encoding="utf-8")

    def test_verbatim_content_match_is_gone(self):
        # 只查真正的判定行；文档字符串里提到旧写法不算。
        self.assertNotIn("if len(core) >= 6 and core in reply", self.src)
        self.assertNotIn('core = it["content"].strip()', self.src)

    def test_refresh_memories_marks_the_injected_ids(self):
        self.assertIn("get_memory().mark_used(ids)", self.src)

    def test_memory_block_records_injected_ids(self):
        marker = "self._memories_in_context=[it.get('id') for it in items if it.get('id')]"
        self.assertEqual(self.src.count(marker), 2,
                         "profile 与旧路径都要记录本轮注入的记忆 id")


if __name__ == "__main__":
    unittest.main()
