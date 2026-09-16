"""双端共享/同步记忆还没做好：入口菜单显示「开发中」，后台整体不启动。

和研究进展一样——代码都留着，只是把入口和运行时一起收起来。
"""
from pathlib import Path
import base64
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import assistant_features  # noqa: E402
import pet  # noqa: E402
import sync_runtime  # noqa: E402


def valid_config():
    return {"transport": "rustdesk-tcp", "enabled": True, "character": "shizuka",
            "channel": "a" * 32, "pairing_key": base64.b64encode(b"k" * 32).decode("ascii"),
            "listen_port": 47631}


class SyncDisabledTests(unittest.TestCase):
    def test_switch_is_off(self):
        self.assertIs(sync_runtime.SYNC_ENABLED, False)

    def test_runtime_stays_none_even_with_a_valid_pairing_config(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "sync-config.json").write_text(
                json.dumps(valid_config()), encoding="utf-8")
            self.assertIsNone(sync_runtime.get_runtime(folder, "shizuka"))

    def test_runtime_is_none_without_a_config(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(sync_runtime.get_runtime(folder, "shizuka"))

    def stub(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        app.say = Mock()
        app.close_popup = Mock()
        return app

    def test_show_sync_only_says_it_is_in_development(self):
        app = self.stub()
        app.show_sync()
        app.say.assert_called_once_with(assistant_features.SYNC_WIP_REPLY)

    def test_sync_now_only_says_it_is_in_development(self):
        app = self.stub()
        app.sync_now()
        app.say.assert_called_once_with(assistant_features.SYNC_WIP_REPLY)

    def test_menu_labels_are_marked_in_development(self):
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn('("双端共享记忆（开发中）", self.show_sync)', source)
        self.assertIn('("立即同步记忆（开发中）", self.sync_now)', source)

    def test_wip_reply_matches_the_research_wording_style(self):
        self.assertIn("开发中", assistant_features.SYNC_WIP_REPLY)
        self.assertIn("开发中", assistant_features.RESEARCH_WIP_REPLY)


if __name__ == "__main__":
    unittest.main()
