"""输入框附件：文件读取、图片转 data URL、附件提示条。"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import conversation_ui as cu  # noqa: E402


class ReadTextFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_utf8_and_gbk(self):
        a = self.root / "a.md"
        a.write_text("中文内容 ok", encoding="utf-8")
        self.assertEqual(cu._read_text_file(str(a)), "中文内容 ok")
        b = self.root / "b.txt"
        b.write_bytes("中文内容 ok".encode("gbk"))
        self.assertEqual(cu._read_text_file(str(b)), "中文内容 ok")

    def test_rejects_binary_and_missing(self):
        c = self.root / "c.bin"
        c.write_bytes(b"\x00\x01\x02binary\x00")
        self.assertEqual(cu._read_text_file(str(c)), "")
        self.assertEqual(cu._read_text_file(str(self.root / "nope.txt")), "")


class ImageDataUrlTests(unittest.TestCase):
    def test_returns_png_data_url(self):
        from PIL import Image
        url = cu.image_data_url(Image.new("RGB", (8, 6), (10, 20, 30)))
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertGreater(len(url), 60)


class AttachPreviewTests(unittest.TestCase):
    def test_image_thumbnail_and_file_chip(self):
        from PIL import Image
        img = Image.new("RGBA", (460, 280), (0, 0, 0, 0))
        atts = [{"kind": "image", "name": "截图", "image": Image.new("RGB", (300, 200), (10, 20, 30))},
                {"kind": "text", "name": "笔记.md"}]
        rects = cu._draw_attach_previews(img, 161, 180, 32, atts)
        self.assertEqual([r[0] for r in rects], [1, 0])          # 从右往左排，索引对得上
        for index, x1, y1, x2, y2 in rects:
            self.assertLessEqual(x2, 162)
            self.assertGreaterEqual(x1, 0)
            self.assertEqual((y1, y2), (180, 212))

    def test_thumbnail_keeps_aspect(self):
        from PIL import Image
        wide = cu._thumb(Image.new("RGB", (400, 100), (200, 0, 0)), 44, 30)
        self.assertEqual(wide.size, (44, 30))
        # 宽图缩进去后上下应该留白（不拉伸）
        self.assertEqual(wide.getpixel((22, 2)), (255, 255, 255))
        self.assertNotEqual(wide.getpixel((22, 15)), (255, 255, 255))

    def test_max_six_previews_with_overflow(self):
        from PIL import Image
        img = Image.new("RGBA", (900, 280), (0, 0, 0, 0))
        atts = [{"kind": "text", "name": "a%d" % i} for i in range(7)]
        rects = cu._draw_attach_previews(img, 880, 180, 32, atts)
        self.assertEqual([rect[0] for rect in rects], [6, 5, 4, 3, 2, 1])


if __name__ == "__main__":
    unittest.main()
