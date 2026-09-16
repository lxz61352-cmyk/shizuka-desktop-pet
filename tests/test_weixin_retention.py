"""微信去重记录的保留策略，以及跨天「图N」的说明文案。

去重按**时间**保留（不再只看条数），跨天回退时必须在给模型的提示里写明是哪天的图。
"""
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import weixin_channel  # noqa: E402
from weixin_channel import ImageIndex, ProtectedStore  # noqa: E402


class SeenRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ProtectedStore(self.root, lambda b, protect: bytes(v ^ 42 for v in b))

    def tearDown(self):
        self.tmp.cleanup()

    def saved_seen(self):
        raw = json.loads((self.root / "weixin-state.json").read_text("utf8"))
        return json.loads(bytes(v ^ 42 for v in
                                __import__("base64").b64decode(raw["protected"])).decode("utf8"))["seen"]

    def test_duplicate_message_is_rejected(self):
        self.assertTrue(self.store.claim("m1"))
        self.assertFalse(self.store.claim("m1"))

    def test_recent_messages_are_kept(self):
        for index in range(5):
            self.store.claim(f"m{index}")
        self.assertEqual(len(self.saved_seen()), 5)
        self.assertFalse(self.store.claim("m0"))

    def test_entries_older_than_the_ttl_are_dropped(self):
        self.store.claim("old")
        seen = self.store.data["seen"]
        seen["old"] = time.time() - weixin_channel.SEEN_TTL_SECONDS - 60
        self.store.claim("fresh")
        self.assertNotIn("old", self.store.data["seen"])
        self.assertIn("fresh", self.store.data["seen"])

    def test_corrupt_timestamps_are_treated_as_stale(self):
        self.store.claim("old")
        self.store.data["seen"]["old"] = "not-a-timestamp"
        self.store.claim("fresh")
        self.assertNotIn("old", self.store.data["seen"])

    def test_hard_cap_still_protects_the_state_file(self):
        with patch.object(weixin_channel, "SEEN_MAX", 3):
            for index in range(6):
                self.store.claim(f"m{index}")
            self.assertEqual(len(self.store.data["seen"]), 3)
            # 最近的三条仍在，最老的被挤掉
            self.assertIn("m5", self.store.data["seen"])
            self.assertNotIn("m0", self.store.data["seen"])


class CrossDayImageNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "index.json"
        self.index = ImageIndex(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, n, day, name):
        item = {"n": n, "day": day, "path": str(Path(self.tmp.name) / name), "at": time.time()}
        self.index.data["items"].append(item)
        return item

    def test_today_image_uses_the_plain_note(self):
        self.index.data["day"] = "20260916"
        today = self.record(1, "20260916", "图1.jpg")
        self.assertEqual(self.index.note_for([today]), "用户指的是这些图片：")

    def test_cross_day_fallback_says_which_day_it_is(self):
        self.index.data["day"] = "20260917"
        older = self.record(3, "20260916", "图3.jpg")
        note = self.index.note_for([older])
        self.assertIn("不是今天", note)
        self.assertIn("9月16日", note)

    def test_mixed_days_list_every_older_day(self):
        self.index.data["day"] = "20260917"
        older = [self.record(2, "20260915", "a.jpg"), self.record(4, "20260916", "b.jpg")]
        note = self.index.note_for(older)
        self.assertIn("9月15日", note)
        self.assertIn("9月16日", note)

    def test_unknown_day_label_is_passed_through(self):
        self.assertEqual(weixin_channel._day_label(""), "")
        self.assertEqual(weixin_channel._day_label("2026-09-16"), "2026-09-16")


if __name__ == "__main__":
    unittest.main()
