"""剪贴板去重：文字按内容（含加长/截短），图片按 sha1 + dHash 近似，记录带 TTL 且会落盘。"""
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from dialogue_grounding import (GroundingMixin, clip_image_signature, clip_image_phash,
                                _hamming_hex, CLIP_RECENT_TTL, PHASH_TOLERANCE)


class Stub(GroundingMixin):
    def __init__(self):
        self._clip_recent = []
        self.saved = []

    def _save_clip_recent(self, recent):
        self.saved.append(list(recent))


def gradient(shift=0):
    img = Image.new("L", (32, 32))
    img.putdata([(x * 7 + shift) % 256 for _ in range(32) for x in range(32)])
    return img


def checker():
    img = Image.new("L", (32, 32))
    img.putdata([255 if (x // 4 + y // 4) % 2 else 0 for y in range(32) for x in range(32)])
    return img


class TextDedupTests(unittest.TestCase):
    def test_same_text_is_repeated(self):
        s = Stub()
        s._clip_remember("text", "同济和宝马中国合作的模型")
        self.assertTrue(s._clip_repeat("text", "同济和宝马中国合作的模型"))
        self.assertFalse(s._clip_repeat("text", "完全不相干的一段话"))

    def test_grown_or_trimmed_selection_counts_as_same(self):
        s = Stub()
        s._clip_remember("text", "上海拥堵收费当例子的政策评估模型")
        self.assertTrue(s._clip_repeat("text", "上海拥堵收费当例子的政策评估模型，用MATSim复现"))
        self.assertTrue(s._clip_repeat("text", "上海拥堵收费当例子"))

    def test_empty_text_is_treated_as_seen(self):
        self.assertTrue(Stub()._clip_repeat("text", "   "))

    def test_expired_records_are_ignored(self):
        s = Stub()
        s._clip_recent = [("text", "很久以前复制过的话", time.time() - CLIP_RECENT_TTL - 1)]
        self.assertFalse(s._clip_repeat("text", "很久以前复制过的话"))

    def test_remember_calls_persist_and_caps(self):
        s = Stub()
        for i in range(300):
            s._clip_remember("text", "内容 %d" % i)
        self.assertEqual(len(s._clip_recent), 200)
        self.assertTrue(s.saved)


class ImageDedupTests(unittest.TestCase):
    def test_phash_is_stable_and_discriminating(self):
        same = clip_image_phash(gradient(0))
        self.assertEqual(same, clip_image_phash(gradient(0)))
        self.assertGreater(_hamming_hex(same, clip_image_phash(checker())), PHASH_TOLERANCE)

    def test_small_change_is_within_tolerance(self):
        near = _hamming_hex(clip_image_phash(gradient(0)), clip_image_phash(gradient(1)))
        self.assertLessEqual(near, PHASH_TOLERANCE)

    def test_near_image_is_deduped_but_different_image_is_not(self):
        s = Stub()
        s._clip_remember("phash", clip_image_phash(gradient(0)))
        self.assertTrue(s._clip_repeat("phash", clip_image_phash(gradient(1))))
        self.assertFalse(s._clip_repeat("phash", clip_image_phash(checker())))

    def test_exact_signature_dedup(self):
        s = Stub()
        sig = clip_image_signature(b"png-bytes")
        s._clip_remember("image", sig)
        self.assertTrue(s._clip_repeat("image", sig))
        self.assertFalse(s._clip_repeat("image", clip_image_signature(b"other")))


if __name__ == "__main__":
    unittest.main()
