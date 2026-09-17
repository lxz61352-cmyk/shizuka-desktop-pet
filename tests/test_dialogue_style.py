"""剪贴板回复的空话尾巴清理，以及「篇幅跟问题需要的信息量匹配」这条回复策略。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dialogue_style import clean_filler_tail, PLAIN_STYLE


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


class ReplyLengthPolicyTests(unittest.TestCase):
    """篇幅要按问题需要的信息量定：简单问题短，复杂问题才展开，讲题不受限。"""

    def test_simple_questions_are_told_to_stay_short(self):
        for phrase in ("一个词或名字是什么意思", "是不是", "能不能", "一两句话答完就够"):
            self.assertIn(phrase, PLAIN_STYLE, phrase)

    def test_background_and_extras_are_discouraged(self):
        for phrase in ("不要顺带讲背景", "延伸联想", "为了显得有用而多讲"):
            self.assertIn(phrase, PLAIN_STYLE, phrase)

    def test_complex_questions_may_expand(self):
        for phrase in ("要多步推理", "要比较取舍", "要完整过程", "详细讲讲"):
            self.assertIn(phrase, PLAIN_STYLE, phrase)

    def test_unsure_defaults_to_short(self):
        self.assertIn("拿不准该写多长时先按短的答", PLAIN_STYLE)

    def test_tutoring_and_code_are_exempt(self):
        self.assertIn("解题讲题、代码和技术推导不受这条限制", PLAIN_STYLE)

    def test_weixin_adds_a_phone_specific_hint(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "weixin_ui.py").read_text(encoding="utf-8")
        self.assertIn("屏幕小、打字慢，能用一两句说清的就别写成一段", source)

    def test_persona_composition_keeps_the_policy(self):
        import pet
        self.assertIn("一两句话答完就够", pet.load_persona())


class FormulaLayoutTests(unittest.TestCase):
    """窄屏公式排版：式子独立成行、符号用 Unicode、不许吐 LaTeX、下标要统一。"""

    def test_formula_goes_on_its_own_line(self):
        self.assertIn("一个式子单独占一行", PLAIN_STYLE)

    def test_long_paragraphs_must_be_split(self):
        self.assertIn("正文一段不超过三四句", PLAIN_STYLE)

    def test_unicode_symbols_are_required(self):
        self.assertIn("符号用 Unicode 数学写法", PLAIN_STYLE)
        for symbol in ("∂", "∫", "√", "×", "≠", "π"):
            self.assertIn(symbol, PLAIN_STYLE, symbol)

    def test_latex_is_banned(self):
        self.assertIn("不要用 LaTeX 记号", PLAIN_STYLE)
        self.assertIn("\\frac", PLAIN_STYLE)

    def test_subscripts_must_be_consistent(self):
        self.assertIn("下标要全篇统一", PLAIN_STYLE)
        self.assertIn("F_z", PLAIN_STYLE)

    def test_layout_must_not_inflate_content(self):
        self.assertIn("排版只改写法", PLAIN_STYLE)
        self.assertIn("不要为了排版多堆公式", PLAIN_STYLE)

    def test_persona_composition_keeps_the_formula_rules(self):
        import pet
        self.assertIn("一个式子单独占一行", pet.load_persona())


if __name__ == "__main__":
    unittest.main()
