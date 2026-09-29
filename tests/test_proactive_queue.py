"""主动对话队列：TTL、优先级、感知分类、与旧接口的兼容。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402
from proactive_queue import (ProactiveIntent, ProactiveQueue,  # noqa: E402
                             classify_activity, TTL)


class ActivityTests(unittest.TestCase):
    def test_idle_is_detected(self):
        self.assertEqual(classify_activity(1200, "explorer.exe"), "挂机")

    def test_work_and_browse(self):
        self.assertEqual(classify_activity(10, "Code.exe"), "工作")
        self.assertEqual(classify_activity(30, "chrome.exe"), "浏览")

    def test_quiet_means_game(self):
        self.assertEqual(classify_activity(5, "game.exe", quiet=True), "游戏/全屏")

    def test_default_is_light_activity(self):
        self.assertEqual(classify_activity(20, "explorer.exe"), "轻度活动")


class QueueTests(unittest.TestCase):
    def test_priority_order(self):
        queue = ProactiveQueue()
        queue.push(ProactiveIntent("topic", "想到一件事"))
        queue.push(ProactiveIntent("reminder", "该喝水了"))
        self.assertEqual(queue.pop_ready().kind, "reminder")

    def test_ttl_expires(self):
        queue = ProactiveQueue()
        intent = ProactiveIntent("screen", "画面内容", created=0)
        queue._items.append(intent)
        queue.prune()
        self.assertEqual(len(queue), 0)

    def test_kind_helpers(self):
        queue = ProactiveQueue()
        queue.push(ProactiveIntent("topic", "A"))
        queue.push(ProactiveIntent("screen", "B"))
        self.assertEqual([item.text for item in queue.by_kind("topic")], ["A"])
        queue.replace_kind("topic", [ProactiveIntent("topic", "C")])
        self.assertEqual([item.text for item in queue.by_kind("topic")], ["C"])
        queue.clear_kind("screen")
        self.assertEqual(len(queue), 1)

    def test_ttl_table_matches_spec(self):
        self.assertEqual(TTL["screen"], 120)
        self.assertEqual(TTL["topic"], 900)
        self.assertGreaterEqual(TTL["reminder"], 1800)


class PetCompatTests(unittest.TestCase):
    """用 __new__ 构造的实例（没有 __init__）也要能走旧接口。"""

    def test_pending_reminders_property_roundtrip(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        app._pending_reminders = [{"text": "给妈妈打电话", "todo_id": "t1", "due": None}]
        self.assertEqual(len(app._pending_reminders), 1)
        self.assertEqual(app._pending_reminders[0]["text"], "给妈妈打电话")
        app._pending_reminders = []
        self.assertEqual(app._pending_reminders, [])

    def test_deferred_is_alias(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        app._deferred_reminders = [{"text": "该喝水了", "todo_id": None, "due": None}]
        self.assertEqual(len(app._pending_reminders), 1)
        app._deferred_reminders = []
        self.assertEqual(len(app._pending_reminders), 0)


if __name__ == "__main__":
    unittest.main()
