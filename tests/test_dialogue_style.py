"""剪贴板回复的空话尾巴清理：只砍掉「我陪你一起弄」这类收尾，不动有内容的话。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dialogue_style import clean_filler_tail


class FillerTailTests(unittest.TestCase):
    def test_tail_after_dash_is_removed(self):
        text = "别砸，键盘又没得罪你。先去接杯水，等手不抖了再说——崩掉的东西我陪你一块重新弄。"
        self.assertEqual(clean_filler_tail(text), "别砸，键盘又没得罪你。先去接杯水，等手不抖了再说")

    def test_pure_filler_becomes_empty(self):
        self.assertEqual(clean_filler_tail("我陪你一起弄。"), "")
        self.assertEqual(clean_filler_tail("先别急，把它发我看看，我陪你一起弄。"), "")

    def test_concrete_reply_is_untouched(self):
        text = "requests 没装上呢，多半是环境不对，看看是不是忘了 source 那个虚拟环境。"
        self.assertEqual(clean_filler_tail(text), text)
        self.assertEqual(clean_filler_tail("今天陪你去医院。"), "今天陪你去医院。")

    def test_empty_input(self):
        self.assertEqual(clean_filler_tail(""), "")
        self.assertEqual(clean_filler_tail(None), "")


if __name__ == "__main__":
    unittest.main()
