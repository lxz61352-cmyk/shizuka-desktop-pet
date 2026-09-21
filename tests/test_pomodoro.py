"""番茄钟：时间格式、分钟钳制。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pomodoro import PomodoroMixin  # noqa: E402


class PomodoroTests(unittest.TestCase):
    def test_mmss(self):
        self.assertEqual(PomodoroMixin._pomo_mmss(0), "00:00")
        self.assertEqual(PomodoroMixin._pomo_mmss(61), "01:01")
        self.assertEqual(PomodoroMixin._pomo_mmss(1500), "25:00")
        self.assertEqual(PomodoroMixin._pomo_mmss(-5), "00:00")

    def test_minutes_clamped(self):
        obj = PomodoroMixin.__new__(PomodoroMixin)
        obj._settings = {"pomodoro_focus": 999}
        self.assertEqual(obj._pomo_minutes("pomodoro_focus", 25), 180)
        obj._settings = {"pomodoro_focus": 0}
        self.assertEqual(obj._pomo_minutes("pomodoro_focus", 25), 25)   # 0 当没设，回到默认
        obj._settings = {"pomodoro_focus": "abc"}
        self.assertEqual(obj._pomo_minutes("pomodoro_focus", 25), 25)
        obj._settings = {}
        self.assertEqual(obj._pomo_minutes("pomodoro_break", 5), 5)

    def test_left_uses_focus_when_idle(self):
        obj = PomodoroMixin.__new__(PomodoroMixin)
        obj._pomo_phase = None
        obj._pomo_focus = 25
        obj._pomo_end_at = 0.0
        self.assertEqual(obj._pomo_left(), 1500)


if __name__ == "__main__":
    unittest.main()
