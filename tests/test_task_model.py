"""模型选择：模型名只在 api_runtime 定义一处；电脑助手按 base/选项解析实际模型。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api_runtime
from api_runtime import DEEPSEEK_MODEL, current_model, model_from_settings
from computer_agent import task_model, resolved_task_model, valid_model_selection, MODEL_CHOICES


def settings_file(root, **values):
    Path(root, "settings.json").write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")


class RuntimeModelTests(unittest.TestCase):
    def test_deepseek_legacy_names_collapse_to_one_model(self):
        for name in ("deepseek-chat", "deepseek-v4-flash", "deepseek-flash",
                     "deepseek-v4-pro", DEEPSEEK_MODEL):
            self.assertEqual(current_model("https://api.deepseek.com", name), DEEPSEEK_MODEL, name)

    def test_other_providers_keep_their_model(self):
        self.assertEqual(current_model("https://api.moonshot.cn/v1", "moonshot-v1-8k"), "moonshot-v1-8k")
        self.assertEqual(current_model("https://api.deepseek.com", "some-new-model"), "some-new-model")

    def test_model_from_settings(self):
        self.assertEqual(model_from_settings({"api_base": "https://api.deepseek.com",
                                              "api_model": "deepseek-chat"}), DEEPSEEK_MODEL)
        self.assertEqual(model_from_settings({}), DEEPSEEK_MODEL)
        self.assertEqual(model_from_settings({"api_base": "https://api.moonshot.cn/v1",
                                              "api_model": "moonshot-v1-8k"}), "moonshot-v1-8k")


class TaskModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_deepseek_uses_the_vision_model(self):
        settings_file(self.root, api_base="https://api.deepseek.com", api_model="deepseek-flash")
        self.assertEqual(task_model("follow-chat", self.root), DEEPSEEK_MODEL)
        self.assertEqual(task_model("follow-chat", self.root, has_images=True), DEEPSEEK_MODEL)
        self.assertEqual(task_model("vision", self.root), DEEPSEEK_MODEL)

    def test_inherit_and_legacy_names_are_normalized(self):
        settings_file(self.root, api_base="https://api.deepseek.com")
        self.assertEqual(task_model("inherit", self.root), "inherit")
        # 显式写旧模型名也会归一成统一模型（所有模型都换成它）
        self.assertEqual(task_model("deepseek-v4-pro", self.root), DEEPSEEK_MODEL)
        self.assertEqual(task_model("deepseek-chat", self.root), DEEPSEEK_MODEL)

    def test_custom_provider_falls_back_to_dsh_default(self):
        settings_file(self.root, api_base="https://api.moonshot.cn/v1", api_model="moonshot-v1-8k")
        self.assertEqual(task_model("follow-chat", self.root), "inherit")
        self.assertEqual(task_model("vision", self.root), "inherit")
        self.assertEqual(task_model("moonshot-v1-8k", self.root), "moonshot-v1-8k")

    def test_resolved_label_is_readable(self):
        settings_file(self.root, api_base="https://api.deepseek.com")
        self.assertEqual(resolved_task_model("follow-chat", self.root), DEEPSEEK_MODEL)
        self.assertEqual(resolved_task_model("inherit", self.root), "DSH 默认模型")

    def test_choice_values_are_all_valid(self):
        for value in MODEL_CHOICES:
            self.assertTrue(valid_model_selection(value), value)
        self.assertTrue(valid_model_selection("deepseek-v4-flash-vision-exp"))
        self.assertFalse(valid_model_selection(""))
        self.assertFalse(valid_model_selection("bad model name!"))


if __name__ == "__main__":
    unittest.main()
