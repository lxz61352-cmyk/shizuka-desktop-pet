"""微信图片编号解析与「按文本挑图」：图N/中文数字/最新一张/编号不存在时给候选。"""
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from weixin_channel import ImageIndex, WeixinChannel, cn_number
from weixin_ui import weixin_image_paths, weixin_visible_text


def build_index(root, count=3):
    index = ImageIndex(Path(root) / "index.json")
    for _ in range(count):
        record = index.add(lambda n, day: Path(root) / ("图%d-%s.jpg" % (n, day)))
        Path(record["path"]).write_bytes(b"x")
    return index


class ChannelStub:
    """只借用 image_context 需要的几个成员，避免起 Tk。"""
    image_block = staticmethod(WeixinChannel.image_block)
    image_context = WeixinChannel.image_context
    _recent_note = WeixinChannel._recent_note

    def __init__(self, index):
        self._index = index

    def image_index(self):
        return self._index


class NumberTests(unittest.TestCase):
    def test_chinese_numbers(self):
        self.assertEqual(cn_number("三"), 3)
        self.assertEqual(cn_number("十二"), 12)
        self.assertEqual(cn_number("两"), 2)
        self.assertEqual(cn_number("2"), 2)
        self.assertEqual(cn_number("?"), 0)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = build_index(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_arabic_and_chinese_number(self):
        for text in ("用图2 讲题", "讲下图二这道题"):
            found, unknown = self.index.resolve(text)
            self.assertEqual([r["n"] for r in found], [2], text)
            self.assertEqual(unknown, [], text)

    def test_missing_number_is_reported_unknown(self):
        found, unknown = self.index.resolve("讲下图9")
        self.assertEqual(found, [])
        self.assertEqual(unknown, [9])

    def test_latest_words(self):
        for text in ("最新那张", "刚才那张", "这张"):
            found, _ = self.index.resolve(text)
            self.assertEqual([r["n"] for r in found], [3], text)

    def test_unrelated_text_resolves_nothing(self):
        self.assertEqual(self.index.resolve("今天天气怎么样"), ([], []))


class ImageContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = build_index(self.tmp.name)
        self.channel = ChannelStub(self.index)

    def tearDown(self):
        self.tmp.cleanup()

    def test_named_image_is_attached(self):
        block, ask, wait = self.channel.image_context("讲下图2", [])
        self.assertIn("[图片]", block)
        self.assertIn("图2-", block)
        self.assertEqual((ask, wait), ([], False))

    def test_missing_number_offers_candidates(self):
        block, ask, wait = self.channel.image_context("讲下图9", [])
        self.assertEqual(block, "")
        self.assertTrue(ask)
        self.assertFalse(wait)

    def test_unnamed_question_uses_latest(self):
        block, ask, wait = self.channel.image_context("讲下这道题", [])
        self.assertIn("[图片]", block)
        self.assertIn("图3-", block)
        self.assertEqual((ask, wait), ([], False))

    def test_unnamed_question_brings_the_two_latest(self):
        block, _, _ = self.channel.image_context("讲下这道题", [])
        self.assertIn("图2-", block)   # 带上倒数第二张，方便「那第二问呢」这类追问
        self.assertNotIn("图1-", block)

    def test_attached_images_are_all_kept(self):
        records = self.index.recent(3)
        block, _, _ = self.channel.image_context("看看这个", records)
        for record in records:
            self.assertIn(record["path"], block)

    def test_attach_word_without_any_image_waits(self):
        empty = ChannelStub(build_index(tempfile.mkdtemp(), count=0))
        self.assertEqual(empty.image_context("附图给你整理一下", []), ("", [], True))


class BlockParsingTests(unittest.TestCase):
    def test_paths_and_visible_text_round_trip(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            index = build_index(tmp.name, count=2)
            records = index.recent(2)
            block = WeixinChannel.image_block(records, "用户指的是这些图片：")
            text = "讲下图2这道题\n\n" + block
            self.assertEqual(weixin_image_paths(text), [r["path"] for r in records])
            self.assertEqual(weixin_visible_text(text), "讲下图2这道题")
            self.assertEqual(weixin_image_paths("没有图片的一句话"), [])
        finally:
            tmp.cleanup()

    def test_visible_text_without_block_is_unchanged(self):
        self.assertEqual(weixin_visible_text("  讲下这道题  "), "讲下这道题")


class DayRolloverTests(unittest.TestCase):
    """跨天的记录不能丢：序号按天重置，但昨天的图还要能按序号回退到。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = build_index(self.tmp.name, count=2)     # 今天的图1、图2

    def tearDown(self):
        self.tmp.cleanup()

    def test_items_survive_the_day_change(self):
        self.index.data["day"] = "20000101"                  # 假装昨天
        record = self.index.add(lambda n, day: Path(self.tmp.name) / ("图%d-%s.jpg" % (n, day)))
        self.assertEqual(record["n"], 1)                     # 序号重新从 1 开始
        self.assertEqual(len(self.index.data["items"]), 3)   # 昨天的两条还在
        found, unknown = self.index.resolve("图2")
        self.assertEqual([r["n"] for r in found], [2])
        self.assertEqual(unknown, [])

    def test_items_are_capped(self):
        for _ in range(60):
            self.index.add(lambda n, day: Path(self.tmp.name) / ("x%d.jpg" % n))
        self.assertEqual(len(self.index.data["items"]), 50)


class NumberedQuestionTests(unittest.TestCase):
    """「讲一下第三题」这种说法：图是刚发的，必须能带上（实测就是这里没认出来）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = build_index(self.tmp.name, count=1)
        self.channel = ChannelStub(self.index)

    def tearDown(self):
        self.tmp.cleanup()

    def _age(self, minutes):
        for record in self.index.data["items"]:
            record["at"] = time.time() - minutes * 60
        self.index._save()

    def test_just_sent_image_is_attached(self):
        self._age(0.05)
        block, ask, wait = self.channel.image_context("讲一下第三题", [])
        self.assertIn("[图片]", block)
        self.assertEqual((ask, wait), ([], False))

    def test_same_question_an_hour_later_still_works(self):
        self._age(90)
        block, _ask, wait = self.channel.image_context("这题怎么做", [])
        self.assertIn("[图片]", block)
        self.assertFalse(wait)

    def test_plain_question_does_not_reach_back(self):
        self._age(90)
        block, _ask, wait = self.channel.image_context("今天天气怎么样", [])
        self.assertEqual(block, "")
        self.assertFalse(wait)

    def test_nothing_matching_asks_for_the_image(self):
        self._age(600)
        block, _ask, wait = self.channel.image_context("讲一下第三题", [])
        self.assertEqual(block, "")
        self.assertTrue(wait)      # 让她明确说「把题目发过来」，而不是答「没收到」

    def test_note_says_which_image_and_asks_her_to_mention_it(self):
        self._age(2)
        block, _ask, _wait = self.channel.image_context("讲一下第三题", [])
        self.assertIn("不是本条消息", block)
        self.assertIn("哪张", block)


if __name__ == "__main__":
    unittest.main()
