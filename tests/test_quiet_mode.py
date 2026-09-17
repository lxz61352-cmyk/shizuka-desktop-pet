"""免打扰判定：游戏/全屏时该安静，其他时候一律照常说话。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402
import quiet_mode  # noqa: E402


class ReasonTests(unittest.TestCase):
    def test_known_game_is_quiet(self):
        self.assertEqual(quiet_mode.quiet_reason("Overwatch", "Overwatch.exe", False), "Overwatch")

    def test_unknown_exe_on_fullscreen_is_quiet(self):
        self.assertEqual(quiet_mode.quiet_reason("Some Game", "game.exe", True), "Some Game")

    def test_windowed_unknown_app_is_not_quiet(self):
        self.assertEqual(quiet_mode.quiet_reason("Visual Studio Code", "Code.exe", False), "")

    def test_desktop_is_not_a_game(self):
        for exe in ("explorer.exe", "Progman.exe", ""):
            self.assertEqual(quiet_mode.quiet_reason("", exe, True), "", exe)

    def test_turning_the_switches_off(self):
        self.assertEqual(quiet_mode.quiet_reason("Overwatch", "Overwatch.exe", False, games=False), "")
        self.assertEqual(quiet_mode.quiet_reason("Some Game", "game.exe", True, use_fullscreen=False), "")

    def test_user_list_wins(self):
        self.assertEqual(quiet_mode.quiet_reason("剪视频", "Premiere.exe", False, quiet_apps=["premiere.exe"]),
                         "剪视频")
        self.assertEqual(quiet_mode.quiet_reason("剪视频", "Premiere.exe", False, quiet_apps=["  ", "Premiere.EXE"]),
                         "剪视频")

    def test_long_title_is_trimmed(self):
        reason = quiet_mode.quiet_reason("标题" * 40, "game.exe", False)
        self.assertLessEqual(len(reason), 40)

    def test_status_text(self):
        self.assertIn("Overwatch", quiet_mode.status_text("Overwatch"))
        self.assertEqual(quiet_mode.status_text(""), "没有在免打扰")

    def test_overwatch_is_in_the_list(self):
        self.assertIn("overwatch.exe", quiet_mode.GAME_EXES)


class ProbeTests(unittest.TestCase):
    def test_fullscreen_probe_never_raises(self):
        # 探测不到就当作「可以说话」，绝不能因为探测异常把静香永久静音
        value = quiet_mode.foreground_is_fullscreen()
        self.assertIsInstance(value, bool)


class SettingsTests(unittest.TestCase):
    """免打扰开关要走 settings.json（读取容错、写回保留）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.saved = pet.SETTINGS_FILE
        pet.SETTINGS_FILE = str(self.path)

    def tearDown(self):
        pet.SETTINGS_FILE = self.saved
        self.tmp.cleanup()

    def test_defaults_quiet_on_but_english_off(self):
        config = pet.load_settings()
        self.assertTrue(config["quiet_fullscreen"])
        self.assertTrue(config["quiet_games"])
        self.assertEqual(config["quiet_apps"], [])
        self.assertFalse(config["voice_en_phonemes"])

    def test_round_trip(self):
        self.path.write_text(json.dumps({"quiet_fullscreen": False, "quiet_games": False,
                                         "quiet_apps": ["code.exe", "  ", 5],
                                         "voice_en_phonemes": True}), encoding="utf-8")
        config = pet.load_settings()
        self.assertFalse(config["quiet_fullscreen"])
        self.assertFalse(config["quiet_games"])
        self.assertEqual(config["quiet_apps"], ["code.exe", "5"])
        self.assertTrue(config["voice_en_phonemes"])

    def test_broken_file_falls_back(self):
        self.path.write_text("{ 这不是 JSON", encoding="utf-8")
        self.assertTrue(pet.load_settings()["quiet_fullscreen"])


class MenuTests(unittest.TestCase):
    """「免打扰」子菜单要真的能建出来（建不出来只会在打开菜单那一刻炸，所以要挡住）。
    用一个只借菜单方法的替身对象 + 隐藏的 Tk root，不启动桌宠本体。"""

    def setUp(self):
        try:
            import tkinter as tk
        except Exception as exc:      # pragma: no cover - 无 Tk 的环境
            self.skipTest("没有 Tk：%s" % exc)
        self.tk = tk
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception as exc:      # pragma: no cover
            self.skipTest("Tk 起不来：%s" % exc)
        self.shim = self._shim(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _shim(self, root):
        class Shim:
            _menu_row = pet.DeskPet._menu_row
            _add_menu_quiet = pet.DeskPet._add_menu_quiet
            _add_menu_en_phonemes = pet.DeskPet._add_menu_en_phonemes
            _add_quiet_app = pet.DeskPet._add_quiet_app
            _clear_quiet_apps = pet.DeskPet._clear_quiet_apps

            def __init__(self, root):
                self.root = root
                self._menu_marks = {}
                self._submenus = []
                self._submenu = None
                self._quiet_fullscreen = True
                self._quiet_games = True
                self._quiet_apps = []
                self._quiet_checked_at = 0.0
                self._quiet_reason_text = ""
                self._tts_en_phonemes = False
                self.said = []
                self.saved = 0
                self.built = []

            def say(self, text, **kwargs):
                self.said.append(text)
                return True

            def _save_settings(self):
                self.saved += 1

            def _quiet_now(self):
                return ""

            def _cancel_hide_submenu(self):
                pass

            def _add_menu_submenu(self, win, text, builder, level=0, width=12):
                self.built.append((text, builder))
                return self.tk.Label(win, text=text)

        shim = Shim(root)
        shim.tk = self.tk
        return shim

    def _build(self):
        self.shim._add_menu_quiet(self.root)
        title, builder = self.shim.built[-1]
        self.assertEqual(title, "免打扰")
        sub = self.tk.Frame(self.root)
        builder(sub, 1)
        return sub

    def test_quiet_submenu_has_both_switches(self):
        sub = self._build()
        texts = [child.cget("text") for child in sub.winfo_children()
                 if child.winfo_class() == "Label"]
        joined = " | ".join(texts)
        self.assertIn("全屏程序时安静", joined)
        self.assertIn("游戏进程时安静", joined)
        self.assertIn("把当前程序加进名单", joined)
        self.assertTrue(any(text.startswith("✓") for text in texts))   # 默认是勾上的

    def test_quiet_submenu_rebuilds_after_adding_a_program(self):
        sub = self._build()
        before = len(sub.winfo_children())
        self.shim._add_quiet_app()          # 前台程序探测不到时会提示，不该抛异常
        self.assertTrue(self.shim.said)

    def test_clear_list_saves(self):
        self.shim._quiet_apps = ["code.exe"]
        self.shim._clear_quiet_apps()
        self.assertEqual(self.shim._quiet_apps, [])
        self.assertEqual(self.shim.saved, 1)

    def test_english_phoneme_row_builds(self):
        saved = pet.gsv_available
        pet.gsv_available = lambda *a, **k: True
        try:
            self.shim._add_menu_en_phonemes(self.root)
        finally:
            pet.gsv_available = saved
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "Label" and isinstance(child.cget("text"), str):
                    texts.append(child.cget("text"))
                walk(child)

        walk(self.root)
        self.assertTrue(any("英文按英文念" in text for text in texts), texts)


if __name__ == "__main__":
    unittest.main()
