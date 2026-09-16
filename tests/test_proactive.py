"""主动发言：方向池按权重随机、同一方向不连续、内容太像就不说。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dialogue_features import DialogueFeaturesMixin


class Stub(DialogueFeaturesMixin):
    def _dialogue_style(self):
        return getattr(self, "style", {})

    def _todo_state_context(self):
        return []


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()

    def test_weighted_and_never_twice_in_a_row(self):
        seen = {}
        last = None
        for _ in range(400):
            row = self.stub._pick_proactive_direction()
            self.assertNotEqual(row["id"], last)   # 同一方向不连续
            last = row["id"]
            seen[row["id"]] = seen.get(row["id"], 0) + 1
        self.assertGreater(seen["observe"], seen["company"])   # 权重生效：观察多于陪伴

    def test_style_pool_overrides_default(self):
        self.stub.style = {"proactive_directions": [
            {"id": "only", "weight": 1, "label": "唯一方向", "prompt": "只说这一句"}]}
        self.assertEqual(self.stub._pick_proactive_direction()["id"], "only")

    def test_prompt_carries_direction_and_silence_escape(self):
        row = {"id": "tip", "weight": 1, "label": "相关小知识", "prompt": "给一条技巧。"}
        text = self.stub._proactive_prompt("前台程序变化", {"程序": "VS Code"}, row)
        self.assertIn("相关小知识", text)
        self.assertIn("VS Code", text)
        self.assertIn("空字符串", text)


class FillerGateTests(unittest.TestCase):
    def test_companion_line_only_allowed_for_company_direction(self):
        stub = Stub()
        company = {"id": "company", "label": "安静陪伴"}
        observe = {"id": "observe", "label": "具体观察"}
        self.assertTrue(stub._proactive_text_ok("我就在这儿，你忙你的。", company))
        self.assertFalse(stub._proactive_text_ok("我就在这儿，你忙你的。", observe))
        self.assertTrue(stub._proactive_text_ok("VS Code 开着，像是在改打包脚本。", observe))


class DedupTests(unittest.TestCase):
    def test_repeat_or_near_repeat_is_rejected(self):
        stub = Stub()
        self.assertTrue(stub._proactive_recent_ok("我就在这儿，你忙你的。"))
        stub._proactive_remember("我就在这儿，你忙你的。")
        self.assertFalse(stub._proactive_recent_ok("我就在这儿，你忙你的。"))
        self.assertFalse(stub._proactive_recent_ok("我就在这儿，你忙你的就好。"))
        self.assertTrue(stub._proactive_recent_ok("VS Code 开着，像是在改打包脚本。"))

    def test_empty_text_is_rejected(self):
        self.assertFalse(Stub()._proactive_recent_ok("   "))


if __name__ == "__main__":
    unittest.main()
