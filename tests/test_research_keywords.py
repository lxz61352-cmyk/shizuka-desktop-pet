"""研究进展：关注方向的输入/去重/上限/落盘，以及关键词真的会驱动检索。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import assistant_features  # noqa: E402
import pet  # noqa: E402
from research_watch import fetch_candidates  # noqa: E402


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self, *args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ResearchKeywordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def app(self):
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._computer_data_dir = lambda: str(self.root)
        obj._research_init()
        return obj

    def saved(self):
        return json.loads((self.root / "research-profile.json").read_text("utf-8"))

    # ---- 开关 ----
    def test_feature_is_enabled_and_menu_drops_the_wip_marker(self):
        self.assertIs(assistant_features.RESEARCH_ENABLED, True)
        source = (ROOT / "src" / "pet.py").read_text(encoding="utf-8")
        self.assertIn('("研究进展", self.show_research)', source)
        self.assertNotIn("研究进展（开发中）", source)

    # ---- 添加 ----
    def test_enter_binding_and_helper_are_wired(self):
        source = (ROOT / "src" / "assistant_features.py").read_text(encoding="utf-8")
        self.assertIn('self._research_entry.bind("<Return>",self._add_research_keyword)', source)
        self.assertIn("command=self._add_research_keyword", source)

    def test_add_writes_topics_and_queries(self):
        app = self.app()
        self.assertEqual(app._add_research_topic("偏微分方程 数值解"), "")
        self.assertEqual(app._research.profile["topics"], ["偏微分方程 数值解"])
        self.assertEqual(app._research.profile["queries"], ["偏微分方程 数值解"])
        self.assertEqual(self.saved()["topics"], ["偏微分方程 数值解"])

    def test_whitespace_is_collapsed(self):
        app = self.app()
        app._add_research_topic("  偏微分   方程的   数值解  ")
        self.assertEqual(app._research.profile["topics"], ["偏微分 方程的 数值解"])

    def test_duplicate_is_rejected_with_a_message(self):
        app = self.app()
        app._add_research_topic("图论")
        message = app._add_research_topic("图论")
        self.assertIn("已经在关注列表", message)
        self.assertEqual(app._research.profile["topics"], ["图论"])

    def test_empty_input_is_rejected(self):
        app = self.app()
        self.assertIn("先输入", app._add_research_topic("   "))
        self.assertEqual(app._research.profile["topics"], [])

    def test_too_long_is_rejected(self):
        app = self.app()
        self.assertIn("60 字以内", app._add_research_topic("方" * 200))
        self.assertEqual(app._research.profile["topics"], [])

    def test_capacity_is_capped(self):
        app = self.app()
        for index in range(assistant_features.RESEARCH_KEYWORD_MAX):
            self.assertEqual(app._add_research_topic("方向%d" % index), "")
        message = app._add_research_topic("再来一个")
        self.assertIn("最多关注", message)
        self.assertEqual(len(app._research.profile["topics"]), assistant_features.RESEARCH_KEYWORD_MAX)

    def test_capacity_matches_what_the_search_actually_queries(self):
        # fetch_candidates 只查前 6 条，界面上的上限必须和它一致，否则用户加了却不生效。
        self.assertEqual(assistant_features.RESEARCH_KEYWORD_MAX, 6)

    # ---- 中文方向自动配英文检索词 ----
    def test_chinese_topic_needs_an_english_query(self):
        self.assertTrue(assistant_features.AssistantFeaturesMixin._needs_research_query("偏微分方程数值解"))
        self.assertFalse(assistant_features.AssistantFeaturesMixin._needs_research_query("graph theory"))
        self.assertFalse(assistant_features.AssistantFeaturesMixin._needs_research_query("PDE numerical methods"))

    def test_english_query_is_generated_for_chinese_topics(self):
        app = self.app()
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message.content = json.dumps({"query": "numerical solution of PDEs"})
        client = Mock()
        client.chat.completions.create.return_value = response
        with patch.object(pet, "has_api_key", return_value=True), \
             patch.object(pet, "get_client", return_value=client):
            query = app._research_query_for("偏微分方程数值解")
        self.assertEqual(query, "numerical solution of PDEs")
        self.assertIn("英文学术文献", client.chat.completions.create.call_args.kwargs["messages"][0]["content"])

    def test_query_generation_falls_back_to_the_topic(self):
        app = self.app()
        with patch.object(pet, "has_api_key", return_value=True), \
             patch.object(pet, "get_client", side_effect=RuntimeError("offline")):
            self.assertEqual(app._research_query_for("图论"), "图论")

    def test_english_topics_skip_the_model_call(self):
        app = self.app()
        with patch.object(pet, "has_api_key", return_value=True), \
             patch.object(pet, "get_client") as client:
            self.assertEqual(app._research_query_for("graph theory"), "graph theory")
        client.assert_not_called()

    def test_topic_and_query_are_stored_separately(self):
        app = self.app()
        app._add_research_topic("偏微分方程数值解", "numerical solution of PDEs")
        profile = app._research.profile
        self.assertEqual(profile["topics"], ["偏微分方程数值解"])
        self.assertEqual(profile["queries"], ["numerical solution of PDEs"])
        self.assertEqual(profile["query_for"], {"偏微分方程数值解": "numerical solution of PDEs"})
        saved = self.saved()
        self.assertEqual(saved["query_for"], {"偏微分方程数值解": "numerical solution of PDEs"})

    def test_removing_a_topic_also_removes_its_english_query(self):
        app = self.app()
        app._add_research_topic("偏微分方程数值解", "numerical solution of PDEs")
        app._add_research_topic("graph theory")
        app._remove_research_topic("偏微分方程数值解")
        profile = app._research.profile
        self.assertEqual(profile["topics"], ["graph theory"])
        self.assertEqual(profile["queries"], ["graph theory"])
        self.assertEqual(profile["query_for"], {})

    def test_the_english_query_is_what_actually_reaches_crossref(self):
        app = self.app()
        app._add_research_topic("偏微分方程数值解", "numerical solution of PDEs")
        seen = []

        def opener(request, timeout=None):
            seen.append(request.full_url)
            return _Response(json.dumps({"message": {"items": []}}).encode("utf-8"))

        fetch_candidates(app._research.profile, now=1_700_000_000, opener=opener)
        self.assertEqual(len(seen), 1)
        self.assertIn("numerical+solution+of+PDEs", seen[0])

    # ---- 删除 ----
    def test_remove_deletes_from_both_lists(self):
        app = self.app()
        app._add_research_topic("图论")
        app._add_research_topic("组合优化")
        app._remove_research_topic("图论")
        self.assertEqual(app._research.profile["topics"], ["组合优化"])
        self.assertEqual(app._research.profile["queries"], ["组合优化"])
        self.assertEqual(self.saved()["topics"], ["组合优化"])

    # ---- 关键词真的驱动检索 ----
    def test_keywords_are_sent_to_crossref(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(request.full_url)
            return _Response(json.dumps({"message": {"items": []}}).encode("utf-8"))

        works, errors = fetch_candidates({"queries": ["偏微分方程 数值解"]}, now=1_700_000_000, opener=opener)
        self.assertEqual(works, [])
        self.assertEqual(errors, [])
        self.assertEqual(len(seen), 1)
        self.assertIn("api.crossref.org", seen[0])
        self.assertIn("%E5%81%8F%E5%BE%AE%E5%88%86%E6%96%B9%E7%A8%8B", seen[0])   # 关键词被编码进查询

    # ---- 猜方向 ----
    def test_suggest_without_api_key_only_prompts(self):
        app = self.app()
        with patch.object(pet, "has_api_key", return_value=False), \
             patch.object(assistant_features.messagebox, "showinfo") as info:
            app._suggest_research_keywords()
        info.assert_called_once()
        self.assertFalse(getattr(app, "_research_suggesting", False))

    def test_suggestion_click_adds_the_keyword(self):
        app = self.app()
        app._research_suggestions = ["拓扑数据分析"]
        with patch.object(app, "_refresh_research"), patch.object(app, "_research_check"):
            app._accept_research_suggestion("拓扑数据分析")
        self.assertEqual(app._research.profile["topics"], ["拓扑数据分析"])
        self.assertEqual(app._research_suggestions, [])


if __name__ == "__main__":
    unittest.main()
