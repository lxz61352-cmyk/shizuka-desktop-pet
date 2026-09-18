"""联网查证：什么时候该搜、搜不到怎么说、结果只给摘要、缓存别重复搜。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import web_search  # noqa: E402


class TriggerTests(unittest.TestCase):
    def test_explicit_requests_always_search(self):
        for text in ("帮我查一下今年春运什么时候开始", "搜一下 deepseek 最新版本", "联网查个资料",
                     "查证一下这个说法", "百度一下这个词"):
            want, reason = web_search.needs_search(text)
            self.assertTrue(want, text)
            self.assertEqual(reason, "你让我查的", text)

    def test_timely_version_number_date(self):
        for text, reason in (("最近有什么新发布的模型", "时事"),
                             ("deepseek 现在是什么版本", "版本"),
                             ("这趟高铁有多少公里", "数字"),
                             ("这个比赛什么时候发布结果", "日期"),
                             ("茅台股价现在多少钱", "数字")):
            want, got = web_search.needs_search(text)
            self.assertTrue(want, text)
            self.assertEqual(got, reason, text)

    def test_not_searching_what_the_model_can_do(self):
        for text in ("1+1等于多少", "现在几点", "今天天气怎么样", "提醒我明天九点开会",
                     "帮我翻译这句话", "讲一下这道题", "这段代码为什么报错", "记住我明天要交报告",
                     "为什么不开心的时候要听歌", "什么是递归"):
            want, _reason = web_search.needs_search(text)
            self.assertFalse(want, text)


class QueryTests(unittest.TestCase):
    def test_cleanup_strips_politeness_and_punctuation(self):
        # 中间的「的」保留（「我的世界」这种专名不能乱删），只去掉句尾那个
        self.assertEqual(web_search.cleanup_query("帮我查一下 deepseek 的最新版本？"), "deepseek 的最新版本")
        self.assertEqual(web_search.cleanup_query("搜一下：费米悖论是什么。"), "费米悖论")
        self.assertEqual(web_search.cleanup_query("搜一下 特斯拉的"), "特斯拉")

    def test_cleanup_turns_xin_fabu_into_zuixin(self):
        # 「最近有什么新发布的 AI 模型」会被引擎按「新」字去搜，得换成「最新」
        self.assertEqual(web_search.cleanup_query("最近有什么新发布的 AI 模型"), "最新的 AI 模型")

    def test_cleanup_falls_back_to_original(self):
        self.assertEqual(web_search.cleanup_query("搜一下"), "搜一下")


class ParseTests(unittest.TestCase):
    RSS = ("<rss><channel>"
           "<item><title>费米悖论 - 百度百科</title><link>https://baike.baidu.com/x</link>"
           "<description>费米悖论是一个有关外星人的科学悖论</description></item>"
           "<item><title>知乎讨论</title><link>https://zhuanlan.zhihu.com/y</link>"
           "<description>宇宙浩瀚而生命罕见</description></item>"
           "</channel></rss>")

    def test_bing_rss_parsing(self):
        saved = web_search._http_get
        web_search._http_get = lambda url, **kwargs: self.RSS
        try:
            results = web_search._bing_rss("费米悖论")
        finally:
            web_search._http_get = saved
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "费米悖论 - 百度百科")
        self.assertIn("外星人", results[0]["snippet"])

    def test_site_of(self):
        self.assertEqual(web_search._site_of("https://www.baidu.com/s?wd=x"), "baidu.com")
        self.assertEqual(web_search._site_of(""), "")

    def test_evidence_is_short_and_says_summarise(self):
        found = {"results": [{"title": "标题一", "url": "https://a.com/1", "snippet": "摘要一"},
                             {"title": "标题二", "url": "https://b.com/2", "snippet": "摘要二"}]}
        block = web_search.format_evidence(found, "测试问题")
        self.assertIn("不要照抄", block)
        self.assertIn("标题一", block)
        self.assertIn("a.com", block)
        self.assertLess(len(block), 600)

    def test_failure_text_tells_her_to_admit_it(self):
        block = web_search.format_failure({"error": "bing-rss-cn:URLError"})
        self.assertIn("没查到", block)
        self.assertIn("别编", block)


class SearchTests(unittest.TestCase):
    def test_falls_back_to_the_next_source(self):
        def bad(_query):
            raise RuntimeError("超时")
        def empty(_query):
            return []
        def good(_query):
            return [{"title": "找到了", "url": "https://x.com", "snippet": "内容"}]
        found = web_search.search("问题", sources=[("坏", bad), ("空", empty), ("好", good)])
        self.assertEqual(found["source"], "好")
        self.assertEqual(len(found["results"]), 1)
        self.assertIn("坏:RuntimeError", found["error"])

    def test_all_sources_failing_is_not_an_exception(self):
        found = web_search.search("问题", sources=[("坏", lambda q: None)])
        self.assertEqual(found["results"], [])
        self.assertTrue(found["error"])

    def test_only_three_results_are_kept(self):
        def many(_query):
            return [{"title": "t%d" % i, "url": "", "snippet": ""} for i in range(8)]
        found = web_search.search("问题", sources=[("多", many)])
        self.assertEqual(len(found["results"]), web_search.MAX_RESULTS)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "search-cache.json"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _sources(self):
        def source(query):
            return [{"title": "结果", "url": "https://x.com", "snippet": "内容"}]
        return [("假源", source)]

    def test_second_identical_query_hits_the_cache(self):
        first = web_search.search_cached("同一个问题", self.path, sources=self._sources(), counter=self.calls)
        self.assertFalse(first.get("cached"))
        second = web_search.search_cached("同一个问题", self.path, sources=self._sources(), counter=self.calls)
        self.assertTrue(second.get("cached"))
        self.assertEqual(len(self.calls), 1)          # 只真的搜了一次
        self.assertEqual(second["results"][0]["title"], "结果")

    def test_expired_cache_searches_again(self):
        web_search.search_cached("问题", self.path, sources=self._sources(), counter=self.calls)
        stale = json.loads(self.path.read_text(encoding="utf-8"))
        for entry in stale.values():
            entry["at"] = 0
        self.path.write_text(json.dumps(stale), encoding="utf-8")
        again = web_search.search_cached("问题", self.path, sources=self._sources(), counter=self.calls)
        self.assertFalse(again.get("cached"))
        self.assertEqual(len(self.calls), 2)

    def test_cache_file_stays_bounded(self):
        for index in range(web_search.CACHE_MAX + 20):
            web_search.search_cached("问题%d" % index, self.path, sources=self._sources())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertLessEqual(len(data), web_search.CACHE_MAX)

    def test_sources_tried_without_foreign_when_offline(self):
        names = [name for name, _ in web_search.default_sources(allow_foreign=False)]
        self.assertEqual(names[0], "bing-rss-cn")           # 不需要加速器的主源
        self.assertIn("360", names)
        self.assertIn("sogou", names)
        self.assertNotIn("ddg", names)

    def test_foreign_sources_come_last_when_online(self):
        names = [name for name, _ in web_search.default_sources(allow_foreign=True)]
        self.assertEqual(names[0], "bing-rss-cn")
        self.assertEqual(names[-3:], ["ddg", "wikipedia", "google-news"])
        # www.bing.com 跟出口地区走，排在国产源之后
        self.assertLess(names.index("360"), names.index("bing-rss"))


if __name__ == "__main__":
    unittest.main()
