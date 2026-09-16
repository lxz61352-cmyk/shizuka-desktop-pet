"""微信图片编号解析与「按文本挑图」：图N/中文数字/最新一张/编号不存在时给候选。"""
from pathlib import Path
import sys
import tempfile
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
    """只借用 image_context 需要的两个成员，避免起 Tk。"""
    image_block = staticmethod(WeixinChannel.image_block)
    image_context = WeixinChannel.image_context

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


if __name__ == "__main__":
    unittest.main()
