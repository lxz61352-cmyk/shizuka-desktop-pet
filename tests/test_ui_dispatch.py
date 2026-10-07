"""UI dispatch yields under load without dropping or reordering callbacks."""
import ast
from pathlib import Path
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class DispatchTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'src/pet.py'
        tree = ast.parse(path.read_text('utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeskPet')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_poll_ui')
        self.now = 0.0
        self.errors = Mock()
        scope = dict(time=SimpleNamespace(monotonic=lambda: self.now), queue=queue, _err_log=self.errors)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
        self.app = SimpleNamespace(_ui_q=queue.Queue(), root=SimpleNamespace(after=Mock()))
        self.app._poll_ui = scope['_poll_ui'].__get__(self.app)

    def test_time_budget_yields_and_remaining_tasks_keep_order(self):
        completed = []
        def task(i):
            completed.append(i)
            self.now += 0.003
        for i in range(5):
            self.app._ui_q.put(lambda i=i: task(i))
        self.app._poll_ui()
        self.assertEqual(completed, [0, 1])
        self.app.root.after.assert_called_with(1, self.app._poll_ui)
        self.app._poll_ui()
        self.app._poll_ui()
        self.assertEqual(completed, list(range(5)))
        self.app.root.after.assert_called_with(25, self.app._poll_ui)

    def test_self_replenishing_queue_cannot_monopolize_dispatch(self):
        completed = []
        def task():
            completed.append(1)
            self.app._ui_q.put(task)
        self.app._ui_q.put(task)
        self.app._poll_ui()
        self.assertEqual(len(completed), 64)
        self.assertEqual(self.app._ui_q.qsize(), 1)
        self.app.root.after.assert_called_with(1, self.app._poll_ui)

    def test_callback_failure_does_not_drop_following_task(self):
        completed = []
        def fail():
            raise ValueError('fixture')
        self.app._ui_q.put(fail)
        self.app._ui_q.put(lambda: completed.append('done'))
        self.app._poll_ui()
        self.errors.assert_called_once_with('poll_ui')
        self.assertEqual(completed, ['done'])
        self.app.root.after.assert_called_with(25, self.app._poll_ui)

    def test_empty_queue_uses_idle_interval(self):
        self.app._poll_ui()
        self.app.root.after.assert_called_once_with(25, self.app._poll_ui)


if __name__ == '__main__':
    unittest.main()
