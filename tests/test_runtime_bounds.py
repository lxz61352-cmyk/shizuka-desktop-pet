"""运行期有界性与一致性：缓存不无界增长、网络模式会过期重探、bat 转义 %、正则只有一份定义。
"""
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import api_runtime  # noqa: E402
import dialogue_style  # noqa: E402
import pet  # noqa: E402
import updater  # noqa: E402
import weather  # noqa: E402


class ModelCapsTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(api_runtime._MODEL_CAPS)
        api_runtime._MODEL_CAPS.clear()

    def tearDown(self):
        api_runtime._MODEL_CAPS.clear()
        api_runtime._MODEL_CAPS.update(self.saved)

    def test_model_caps_stays_bounded(self):
        for index in range(api_runtime._MODEL_CAPS_MAX + 20):
            api_runtime._model_caps("https://example.invalid/v1", f"model-{index}")
        self.assertLessEqual(len(api_runtime._MODEL_CAPS), api_runtime._MODEL_CAPS_MAX)
        # 新模型仍然拿得到默认能力表
        caps = api_runtime._model_caps("https://example.invalid/v1", "another-model")
        self.assertEqual(caps["max_key"], "max_tokens")
        # 缓存键带上接口类型：同一个模型在 chat / responses 下参数名不一样
        self.assertIn(("https://example.invalid/v1", "another-model", "chat"), api_runtime._MODEL_CAPS)
        self.assertEqual(
            api_runtime._model_caps("https://example.invalid/v1", "another-model", "responses")["max_key"],
            "max_output_tokens")


class EmbedCacheTests(unittest.TestCase):
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def setUp(self):
        pet._EMB_CACHE.clear()
        self.saved_down = pet._EMB_DOWN_UNTIL
        pet._EMB_DOWN_UNTIL = 0.0

    def tearDown(self):
        pet._EMB_CACHE.clear()
        pet._EMB_DOWN_UNTIL = self.saved_down

    def test_cache_evicts_partially_instead_of_clearing(self):
        total = pet._EMB_CACHE_MAX + 1

        def urlopen(request, timeout=None):
            texts = json.loads(request.data.decode("utf-8"))["texts"]
            return self._Response(json.dumps({"vecs": [[1.0, 0.0]] * len(texts)}).encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=urlopen):
            vectors = pet._embed_texts([f"记忆-{i}" for i in range(total)])
        self.assertEqual(len(vectors), total)
        self.assertLessEqual(len(pet._EMB_CACHE), pet._EMB_CACHE_MAX)
        # 整表清空时这里会是 0：必须保留一部分，否则紧接着的请求全部落空。
        self.assertGreater(len(pet._EMB_CACHE), 0)


class NetModeTests(unittest.TestCase):
    def setUp(self):
        self.saved = (weather._NET_MODE, weather._NET_MODE_AT)
        weather._NET_MODE = None
        weather._NET_MODE_AT = 0.0

    def tearDown(self):
        weather._NET_MODE, weather._NET_MODE_AT = self.saved

    def test_mode_is_reprobed_after_ttl(self):
        with patch.object(weather, "_foreign_net_ok", return_value=True):
            self.assertEqual(weather._net_mode(), "proxy")
        # TTL 内沿用缓存：网络探测不该每次提问都跑一遍
        with patch.object(weather, "_foreign_net_ok", side_effect=AssertionError("不应重探")):
            self.assertEqual(weather._net_mode(), "proxy")
        weather._NET_MODE_AT = time.time() - weather._NET_MODE_TTL - 1
        with patch.object(weather, "_foreign_net_ok", return_value=False):
            self.assertEqual(weather._net_mode(), "direct")


class UpdateBatTests(unittest.TestCase):
    def test_percent_in_paths_is_escaped(self):
        with tempfile.TemporaryDirectory(prefix="shizuka-bat-") as folder:
            with patch.object(updater.subprocess, "Popen"):
                updater.launch_swap(r"D:\100%done\new", folder, r'"D:\100%done\Shizuka.exe"', pid=1234)
            bat = (Path(folder) / "_update.bat").read_text(encoding="gbk", errors="ignore")
        self.assertIn("%%done", bat)
        self.assertNotIn("100%done", bat.replace("%%done", ""))

    def test_pid_wait_and_data_exclusions_are_kept(self):
        with tempfile.TemporaryDirectory(prefix="shizuka-bat-") as folder:
            with patch.object(updater.subprocess, "Popen"):
                updater.launch_swap(r"D:\new", folder, r'"D:\new\Shizuka.exe"', pid=4321)
            bat = (Path(folder) / "_update.bat").read_text(encoding="gbk", errors="ignore")
        self.assertIn('PID eq 4321', bat)
        self.assertIn("/XD data voice_model experiments", bat)
        self.assertIn("/XF api_key.txt", bat)


class LeadRegexTests(unittest.TestCase):
    def test_pet_reuses_the_shared_lead_regexes(self):
        self.assertIs(pet._ACK_LEAD_RE, dialogue_style.ACK_LEAD_RE)
        self.assertIs(pet._FORMULA_LEAD_RE, dialogue_style.FORMULA_LEAD_RE)

    def test_you_are_still_lead_is_cleaned_in_both_entries(self):
        # 「你还在……」以前只有 dialogue_style 会删，pet 的闸门认不出来。
        for text in ("哦，这样啊。", "你还在忙呢。", "又在看代码。"):
            self.assertFalse(pet.clean_reply_style(text).startswith(("哦", "你还在", "又在")), text)
            self.assertFalse(dialogue_style.clean_text(text).startswith(("哦", "你还在", "又在")), text)


if __name__ == "__main__":
    unittest.main()
