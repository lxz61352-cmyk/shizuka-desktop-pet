"""朗读语言：选日文时保留假名、走 ja 音素，并要求模型用日语写要念的话。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402


class SpeakableKanaTests(unittest.TestCase):
    def test_kana_kept_only_when_asked(self):
        self.assertEqual(pet.speakable("これはテストです"), "")
        self.assertEqual(pet.speakable("これはテストです", kana=True), "これはテストです")

    def test_chinese_still_kept_with_kana(self):
        self.assertEqual(pet.speakable("おはよう、今天天气不错", kana=True), "おはよう、今天天气不错")

    def test_tts_keep_flag(self):
        self.assertFalse(pet.tts_keep("あ"))
        self.assertTrue(pet.tts_keep("あ", True))
        self.assertTrue(pet.tts_keep("你", True))


class KanaDetectTests(unittest.TestCase):
    def test_has_kana(self):
        self.assertTrue(pet._has_kana("おはよう"))
        self.assertTrue(pet._has_kana("テスト"))
        self.assertFalse(pet._has_kana("今天天气不错"))
        self.assertFalse(pet._has_kana("hello world"))


class VoiceLangHintTests(unittest.TestCase):
    def make_pet(self, lang="zh", voice=True):
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._tts_lang = lang
        obj._voice_on = voice
        return obj

    def test_hint_only_when_japanese_and_voice_on(self):
        self.assertEqual(self.make_pet("zh", True)._voice_lang_hint(), "")
        self.assertEqual(self.make_pet("ja", False)._voice_lang_hint(), "")
        self.assertIn("日语", self.make_pet("ja", True)._voice_lang_hint())
        self.assertIn(pet.VOICE_JA_MARK, self.make_pet("ja", True)._voice_lang_hint())


class SplitVoiceLangTests(unittest.TestCase):
    def test_splits_display_and_spoken(self):
        show, spoken = pet._split_voice_lang("今天也要加油哦。\n[[JA]]今日も頑張ってね。", True)
        self.assertEqual(show, "今天也要加油哦。")
        self.assertEqual(spoken, "今日も頑張ってね。")

    def test_no_marker_keeps_chinese_only(self):
        show, spoken = pet._split_voice_lang("固定台词", True)
        self.assertEqual(show, "固定台词")
        self.assertEqual(spoken, "")

    def test_chinese_mode_returns_same_text(self):
        text = "今天也要加油哦。"
        self.assertEqual(pet._split_voice_lang(text, False), (text, text))

    def test_partial_marker_is_held_back(self):
        show, spoken = pet._split_voice_lang("正文[[J", True)
        self.assertEqual(show, "正文")
        self.assertEqual(spoken, "")

    def test_tolerates_marker_variants(self):
        for mark in ("[[JA]]", "[[ja]]", "[JA]", "【JA】", "[[ JA ]]"):
            show, spoken = pet._split_voice_lang("今天也要加油。\n%s今日も頑張ってね。" % mark, True)
            self.assertEqual(show, "今天也要加油。", mark)
            self.assertEqual(spoken, "今日も頑張ってね。", mark)

    def test_marker_without_japanese_gives_empty_spoken(self):
        show, spoken = pet._split_voice_lang("正文[[JA]]", True)
        self.assertEqual(show, "正文")
        self.assertEqual(spoken, "")


class EnqueueLangTests(unittest.TestCase):
    def make_pet(self, lang):
        import queue
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._conv_id = 1
        obj._tts_q = queue.Queue()
        obj._synth_q = queue.Queue(maxsize=3)
        obj._tts_prod_thread = None
        obj._tts_thread = None
        obj._tts_lang = lang
        return obj

    def _enqueue(self, obj, text):
        original = pet.threading.Thread
        pet.threading.Thread = lambda *a, **k: type("T", (), {"start": lambda self: None, "is_alive": lambda self: True})()
        try:
            obj._tts_enqueue(text)
        finally:
            pet.threading.Thread = original

    def test_japanese_queued_in_japanese_mode(self):
        obj = self.make_pet("ja")
        self._enqueue(obj, "これはテストです")
        self.assertEqual(obj._tts_q.get()[0], "これはテストです")

    def test_japanese_dropped_in_chinese_mode(self):
        obj = self.make_pet("zh")
        self._enqueue(obj, "これはテストです")
        self.assertTrue(obj._tts_q.empty())


if __name__ == "__main__":
    unittest.main()
