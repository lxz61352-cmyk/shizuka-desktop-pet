"""删除待办必须连旁表和提醒一起收尾：旁表条目不再只增不减，在途提醒也不会再弹。
"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402


class TodoDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.details_path = Path(self.tmp.name) / "todo-details.json"
        self.app = pet.DeskPet.__new__(pet.DeskPet)
        self.app.todos = [{"id": "t1", "text": "给妈妈打电话", "due": None, "on_boot": False,
                           "done": False, "created": 1.0},
                          {"id": "t2", "text": "留下的一条", "due": None, "on_boot": False,
                           "done": False, "created": 2.0}]
        self.app._todo_details = {"t1": {"category": "生活", "desktop": True, "weixin": True},
                                  "t2": {"category": "生活", "desktop": True, "weixin": True}}
        self.app._todo_details_path = self.details_path
        self.app._todo_sending = set()
        self.app._chat_lock = threading.RLock()
        self.app._chat_log = []
        self.app._pending_reminders = [{"text": "给妈妈打电话", "todo_id": "t1"}]
        self.app._active_todo_id = "t1"
        self.app._todo_notice_win = None
        self.app._reply_win = None
        self.app._save_todos = Mock()
        self.app._refresh_todo_view = Mock()
        self.app._todo_start_memory_review = Mock()
        self.app._cancel_reply = Mock()

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_removes_todo_and_its_sidecar_entry(self):
        self.app._todo_delete("t1")
        self.assertEqual([row["id"] for row in self.app.todos], ["t2"])
        self.assertNotIn("t1", self.app._todo_details)
        self.assertIn("t2", self.app._todo_details)
        self.app._save_todos.assert_called_once()

    def test_delete_cancels_pending_reminders_and_active_notice(self):
        self.app._todo_delete("t1")
        self.assertEqual(self.app._pending_reminders, [])
        self.assertIsNone(self.app._active_todo_id)

    def test_delete_persists_the_pruned_sidecar(self):
        self.app._todo_delete("t1")
        saved = json.loads(self.details_path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(saved["items"]), ["t2"])

    def test_delete_of_unknown_id_is_harmless(self):
        self.app._todo_delete("missing")
        self.assertEqual([row["id"] for row in self.app.todos], ["t1", "t2"])
        self.app._save_todos.assert_called_once()


if __name__ == "__main__":
    unittest.main()
