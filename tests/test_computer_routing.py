"""Real pet routes with fake backend, without GUI creation or API requests."""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pet


class RoutingTests(unittest.TestCase):
    def app(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        app._conv_id = 4
        app._sound_mode='none'
        for name in ("_log_chat", "say", "_start_computer_task", "show_computer_assistant",
                     "_cancel_reply", "_close_think_bubble", "open_chat_input"):
            setattr(app, name, Mock())
        return app

    def test_explicit_command_uses_dsh_without_requesting_pet_api_key(self):
        app = self.app()
        with patch.object(pet, "has_api_key", side_effect=AssertionError("explicit dsh route must use its own credentials")):
            app.on_chat_submit("/电脑 读取 test.txt")
        app._start_computer_task.assert_called_once_with("读取 test.txt", 4)

    def test_empty_command_opens_file_controls(self):
        app = self.app()
        app.on_chat_submit("/电脑")
        app.show_computer_assistant.assert_called_once()
        app._start_computer_task.assert_not_called()

    def test_natural_language_route_preserves_the_original_request(self):
        app = self.app()
        app._route_intent({"action": "computer_task", "content": "model rewrote request"}, "把原文件重命名", 4)
        app._start_computer_task.assert_called_once_with("把原文件重命名", 4)
        app._route_intent({"action": "computer_task"}, "stale", 3)
        self.assertEqual(app._start_computer_task.call_count, 1)

    def test_completion_does_not_extract_file_contents_as_long_term_memory(self):
        app = self.app()
        token = threading.Event()
        app._computer_cancel = token
        app._computer_state = {}
        app._post_memory = Mock(side_effect=AssertionError("do not learn tool contents as personal facts"))
        # Real DeskPet.say records the response; the completion handler must not duplicate it.
        app.say.side_effect = lambda text, **kwargs: app._log_chat("assistant", text)
        app._computer_task_done("读取文件", {"status": "completed", "output": "文件内容"}, 4, token)
        app._post_memory.assert_not_called()
        app._log_chat.assert_called_once()
        self.assertEqual(app._log_chat.call_args.args[0],'assistant')
        self.assertIn('文件内容',app._log_chat.call_args.args[1])

    def test_stale_completion_does_not_interrupt_a_new_chat(self):
        app = self.app()
        token = threading.Event()
        app._computer_cancel = token
        app._computer_state = {}
        app._computer_task_done("old", {"status": "completed", "output": "old output"}, 3, token)
        app.say.assert_not_called()
        app._log_chat.assert_not_called()

    def todo_app(self):
        app = self.app()
        app.todos = []
        app._save_todos = Mock()
        app._save_todo_details = Mock()
        app._todo_options = Mock(return_value={})
        return app

    def test_natural_language_add_todo_saves_a_reminder(self):
        app = self.todo_app()
        app._route_intent({"action": "add_todo", "content": "晾衣服", "content_clear": True},
                          "30s后提醒我晾衣服", 4)
        self.assertEqual(len(app.todos), 1)
        item = app.todos[0]
        self.assertEqual(item["text"], "晾衣服")
        self.assertIsNotNone(item["due"])
        self.assertTrue(0 < item["due"] - time.time() <= 30)
        app.say.assert_called_once()

    def test_add_todo_without_a_task_asks_for_one(self):
        app = self.todo_app()
        app._route_intent({"action": "add_todo", "content": "", "content_clear": False},
                          "提醒我明天9点", 4)
        self.assertEqual(app.todos, [])
        self.assertEqual(app._pending_todo["need"], "content")
        app.say.assert_called_once()


if __name__ == "__main__":
    unittest.main()
