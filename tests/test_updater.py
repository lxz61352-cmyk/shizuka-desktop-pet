"""Update check, announcement parsing and the pending-update marker, without real network."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import updater


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class VersionTests(unittest.TestCase):
    def test_version_tuple_orders_numerically(self):
        self.assertGreater(updater.version_tuple("v0.10.0"), updater.version_tuple("0.9.9"))
        self.assertGreater(updater.version_tuple("0.7.6"), updater.version_tuple("0.7.4"))
        self.assertEqual(updater.version_tuple("v1.2.3"), (1, 2, 3))


class AnnouncementTests(unittest.TestCase):
    def test_reads_only_the_matching_section(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "更新公告.md"
            path.write_text("# 更新公告\n\n## v0.8.0\n\n新内容\n\n## v0.7.6\n\n旧内容\n", encoding="utf-8")
            with patch.object(updater, "ANNOUNCE_FILE", str(path)):
                self.assertEqual(updater.read_announcement("0.8.0"), "新内容")
                self.assertEqual(updater.read_announcement("v0.7.6"), "旧内容")
                self.assertEqual(updater.read_announcement("9.9.9"), "")


class PendingUpdateTests(unittest.TestCase):
    def test_round_trip_removes_the_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "_pending_update.json"
            with patch.object(updater, "PENDING_UPDATE_FILE", str(path)):
                updater.write_pending_update("0.8.0", "说明")
                self.assertTrue(path.exists())
                self.assertEqual(updater.read_pending_update(), {"version": "0.8.0", "notes": "说明"})
                self.assertFalse(path.exists())
                self.assertIsNone(updater.read_pending_update())


class CheckReleaseTests(unittest.TestCase):
    def test_github_release_is_parsed(self):
        payload = json.dumps({
            "tag_name": "v0.9.0",
            "body": "notes",
            "assets": [{"name": "Shizuka-0.9.0-update.zip",
                        "browser_download_url": "https://github.com/x/y/releases/download/v0.9.0/a.zip"}],
        }).encode()
        with patch.object(updater.urllib.request, "urlopen", return_value=_Resp(payload)):
            self.assertEqual(updater.check_latest_release(),
                             (True, "0.9.0", "https://github.com/x/y/releases/download/v0.9.0/a.zip", "notes"))

    def test_older_release_is_not_an_update(self):
        payload = json.dumps({"tag_name": "v0.0.1", "assets": []}).encode()
        with patch.object(updater.urllib.request, "urlopen", return_value=_Resp(payload)):
            self.assertFalse(updater.check_latest_release()[0])

    def test_total_network_failure_reports_nothing(self):
        with patch.object(updater.urllib.request, "urlopen", side_effect=OSError("blocked")):
            self.assertEqual(updater.check_latest_release(), (False, "", "", ""))


if __name__ == "__main__":
    unittest.main()
