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
        self.assertEqual(obj._tts_q.get()[0], "你好呀")


if __name__ == "__main__":
    unittest.main()
