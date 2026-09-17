"""语音分段：网址不念、标题单独成段、标题前停顿更短。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet  # noqa: E402


ALERT = ("我看到一条与您课题相关的新文献。\n"
         "Deep Learning for Solving Partial Differential Equations\n"
         "发表于《Journal of Computational Physics》。\n"
         "\n"
         "这篇把网络当算子来学，和您手上的数值解路线能对照着看。\n"
         "\n"
         "https://doi.org/10.1016/j.jcp.2024.112345")


class StripUrlTests(unittest.TestCase):
    def test_url_is_removed_and_chinese_text_survives(self):
        # 中文句子没有空格，网址后面的正文不能被一起吃掉
        self.assertEqual(pet._strip_urls("见 https://doi.org/10.1/abc。记得核对"),
                         "见 。记得核对")
        self.assertEqual(pet._strip_urls("详情见：https://a.com/b"),
                         "详情见：")

    def test_ascii_punctuation_after_url_is_kept(self):
        self.assertEqual(pet._strip_urls("see https://a.com/b, then stop"),
                         "see , then stop")

    def test_plain_text_untouched(self):
        self.assertEqual(pet._strip_urls("就是一句话，没有链接。"), "就是一句话，没有链接。")
        self.assertEqual(pet._strip_urls(None), "")


class SplitTests(unittest.TestCase):
    def test_alert_has_no_url_segment(self):
        pieces = pet._tts_split(ALERT)
        self.assertTrue(pieces)
        self.assertFalse([p for p in pieces if "http" in p or "doi.org" in p])

    def test_long_english_title_stays_one_segment(self):
        pieces = pet._tts_split(ALERT)
        title = [p for p in pieces if p.startswith("Deep Learning")][0]
        self.assertEqual(title, "Deep Learning for Solving Partial Differential Equations")

    def test_journal_sentence_is_not_a_title_and_still_splits(self):
        long_line = "发表于《Journal of Computational Physics》的一篇综述值得留意"
        pieces = pet._tts_split(long_line)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 45 for p in pieces))

    def test_book_title_line_stays_whole(self):
        pieces = pet._tts_split("《基于深度学习的偏微分方程数值解法研究及其在流体力学中的应用》")
        self.assertEqual(len(pieces), 1)

    def test_newline_keeps_title_off_the_next_line(self):
        # 标题行没有句末标点；没有「换行即边界」的话它会和下一行粘成一段再被切开
        text = ("Deep Learning for Solving Partial Differential Equations\n"
                "这篇把网络当算子来学，和您手上的数值解路线能对照着看。")
        pieces = pet._tts_split(text)
        self.assertEqual(len(pieces), 2)
        self.assertEqual(pieces[0], "Deep Learning for Solving Partial Differential Equations")

    def test_short_lines_are_merged(self):
        # 太短的句子单独合成会平淡，往后并成一段
        pieces = pet._tts_split("嗯。\n好的，我知道了。")
        self.assertEqual(pieces, ["嗯。好的，我知道了。"])

    def test_only_url_is_dropped(self):
        self.assertEqual(pet._tts_split("https://example.com/a/b"), [])


class TitleTests(unittest.TestCase):
    def test_book_title_line(self):
        self.assertTrue(pet._looks_like_title("《基于深度学习的图像去噪方法研究》"))

    def test_journal_in_a_sentence_is_not_a_title(self):
        self.assertFalse(pet._looks_like_title("发表于《Nature》。"))

    def test_english_line_is_a_title(self):
        self.assertTrue(pet._looks_like_title("Operator Learning for PDEs"))

    def test_short_noise_is_not_a_title(self):
        self.assertFalse(pet._looks_like_title("OK"))
        self.assertFalse(pet._looks_like_title("这句话是中文的。"))


class _Speaker:
    """只保留 _speak/_speak_stream 用到的东西。"""
    _voice_on = True

    def __init__(self):
        self.calls = []

    def _tts_enqueue(self, text, gap_ms=None):
        self.calls.append((text, gap_ms))


class PauseTests(unittest.TestCase):
    def test_gap_by_punctuation(self):
        self.assertEqual(pet._tts_gap("这一句结束了。"), pet.TTS_SENTENCE_GAP_MS)
        self.assertEqual(pet._tts_gap("前面这半句，"), pet.TTS_PAUSE_COMMA_MS)
        self.assertEqual(pet._tts_gap("半句没有标点"), pet.TTS_HALF_GAP_MS)
        self.assertEqual(pet._tts_gap("这一段的最后一句。", block_end=True), pet.TTS_PARAGRAPH_GAP_MS)

    def test_gap_before_title_is_shortest(self):
        self.assertEqual(pet._tts_gap("前面这句。", following="《A Long Title》"), pet.TTS_TITLE_GAP_MS)
        # 标题规则优先于段落规则
        self.assertEqual(pet._tts_gap("这一段。", following="Deep Learning for PDEs", block_end=True),
                         pet.TTS_TITLE_GAP_MS)

    def test_segments_mark_paragraph_ends(self):
        segments = pet._tts_segments("第一段够长的一句话。\n第二段也够长的一句话。")
        self.assertEqual([piece for piece, _ in segments],
                         ["第一段够长的一句话。", "第二段也够长的一句话。"])
        self.assertEqual([block for _, block in segments], [True, False])

    def test_single_segment_is_not_a_paragraph_break(self):
        segments = pet._tts_segments("只有一句话，但也就这样了。")
        self.assertEqual([block for _, block in segments], [False])


class SpeakGapTests(unittest.TestCase):
    def test_piece_before_title_gets_shorter_gap(self):
        stub = _Speaker()
        pet.DeskPet._speak(stub, ALERT)
        gaps = {text: gap for text, gap in stub.calls if text}
        lead = "我看到一条与您课题相关的新文献。"
        self.assertEqual(gaps[lead], pet.TTS_TITLE_GAP_MS)
        # 标题独占一行，它后面是另起一段 → 段落停顿
        self.assertEqual(gaps["Deep Learning for Solving Partial Differential Equations"],
                         pet.TTS_PARAGRAPH_GAP_MS)
        # 其余段用默认句末停顿；结尾是结束标记
        self.assertEqual(gaps["这篇把网络当算子来学，和您手上的数值解路线能对照着看。"],
                         pet.TTS_SENTENCE_GAP_MS)
        self.assertEqual(stub.calls[-1], (None, None))

    def test_every_segment_gets_an_explicit_gap(self):
        stub = _Speaker()
        pet.DeskPet._speak(stub, "今天天气是真的不错。要不要一起出去走走？")
        spoken = [gap for text, gap in stub.calls if text]
        self.assertEqual(len(spoken), 2)
        self.assertTrue(all(gap is not None for gap in spoken))

    def test_stream_gaps_follow_the_terminator(self):
        stub = _Speaker()
        text = "第一句话已经够长了。第二句话也已经够长了。\n第三句话同样够长一些。"
        pet.DeskPet._speak_stream(stub, text, 0)
        gaps = [gap for _, gap in stub.calls]
        # 换行紧跟句末标点时，换行自己会变成一个空片段被丢掉 —— 段落停顿要算在它前面那句上
        self.assertEqual(gaps[:3], [pet.TTS_SENTENCE_GAP_MS, pet.TTS_PARAGRAPH_GAP_MS,
                                    pet.TTS_SENTENCE_GAP_MS])


class StreamTests(unittest.TestCase):
    def test_stream_never_queues_a_url(self):
        stub = _Speaker()
        text = "先看看这个 https://example.com/paper 这个方法很值得留意。还有一句收尾。"
        used = pet.DeskPet._speak_stream(stub, text, 0)
        self.assertLessEqual(used, len(text))
        queued = [t for t, _ in stub.calls]
        self.assertFalse([t for t in queued if "http" in t or "example" in t])
        # 网址前后的正文都留着，只有链接本身不念
        self.assertIn("先看看这个  这个方法很值得留意。", queued)

    def test_incomplete_url_waits_for_more_text(self):
        stub = _Speaker()
        head = "先看看这个 https://doi.org/10.1016/j.jcp"
        used = pet.DeskPet._speak_stream(stub, head, 0)
        self.assertFalse(stub.calls)
        self.assertLessEqual(used, len(head))
        full = head + ".2024.112345 这个方法很值得留意。"
        pet.DeskPet._speak_stream(stub, full, used)
        self.assertTrue(stub.calls)
        self.assertFalse([t for t, _ in stub.calls if "doi.org" in t])

    def test_final_flush_strips_url(self):
        stub = _Speaker()
        pet.DeskPet._speak_stream(stub, "结论在 https://a.com/b 里。", 0, final=True)
        self.assertEqual([t for t, _ in stub.calls], ["结论在  里。"])


if __name__ == "__main__":
    unittest.main()
