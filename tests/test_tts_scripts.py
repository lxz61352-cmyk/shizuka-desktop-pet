"""语音只念中文和英文：日文假名整段跳过，从下一个中文/英文字符接着念。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402


class SpeakableTests(unittest.TestCase):
    def test_japanese_is_skipped(self):
        self.assertEqual(pet.speakable("これはテストです"), "")
        self.assertEqual(pet.speakable("これはテストです。你好呀"), "你好呀")

    def test_english_and_chinese_are_kept(self):
        # 首尾的标点会被削掉（合成时不需要），字一个不少
        self.assertEqual(pet.speakable("DeepSeek V4.1 已经发布了，速度挺快的！"),
                         "DeepSeek V4.1 已经发布了，速度挺快的")

    def test_korean_and_cyrillic_are_skipped(self):
        self.assertEqual(pet.speakable("안녕하세요 你好"), "你好")
        self.assertEqual(pet.speakable("Привет 你好"), "你好")

    def test_latin_punctuation_survives(self):
        self.assertEqual(pet.speakable("Error: 404 not found"), "Error: 404 not found")


class EnqueueTests(unittest.TestCase):
    def make_pet(self):
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._conv_id = 1
        obj._tts_q = __import__("queue").Queue()
        obj._synth_q = __import__("queue").Queue(maxsize=3)
        obj._tts_prod_thread = None
        obj._tts_thread = None
        return obj

    def test_japanese_segment_is_not_queued(self):
        obj = self.make_pet()
        original = pet.threading.Thread
        pet.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None, "is_alive": lambda self: True})()
        try:
            obj._tts_enqueue("これはテストです")
        finally:
            pet.threading.Thread = original
        self.assertTrue(obj._tts_q.empty())

    def test_mixed_segment_keeps_the_chinese(self):
        obj = self.make_pet()
        original = pet.threading.Thread
        pet.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None, "is_alive": lambda self: True})()
        try:
            obj._tts_enqueue("これはテストです 你好呀")
        finally:
            pet.threading.Thread = original
        item = obj._tts_q.get()
        self.assertEqual(item[0], "これはテストです 你好呀")   # 显示用原文：整句都留着
        self.assertEqual(item[1], "你好呀")                    # 合成用文本：日语被剔掉

    def test_display_text_keeps_sentence_punctuation(self):
        """合成会把句末标点削掉；显示不能用合成文本，否则每句话最后的标点都会被吞。"""
        obj = self.make_pet()
        original = pet.threading.Thread
        pet.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None, "is_alive": lambda self: True})()
        try:
            obj._tts_enqueue("好的呀。我这就去办。")
        finally:
            pet.threading.Thread = original
        display, tts, _conv, _gap = obj._tts_q.get()
        self.assertEqual(display, "好的呀。我这就去办。")
        self.assertTrue(tts.endswith("去办"))
        self.assertFalse(tts.endswith("。"))


if __name__ == "__main__":
    unittest.main()
