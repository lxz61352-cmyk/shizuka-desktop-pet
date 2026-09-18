"""联网查证：什么时候该搜、搜不到怎么说、结果怎么排、缓存别重复搜。"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import web_search  # noqa: E402


def setUpModule():
    # 单元测试一律不碰网络：抓正文默认返回空（要测抓正文的用例自己临时换回来）
    web_search.read_web_page = lambda url, limit=4000: ""


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

    def test_search_query_adds_the_intent_word(self):
        # 实测：`iPhone 18 发布` 出来是官网换购页，`iPhone 18 发布时间` 才是发布稿和百科条目
        self.assertEqual(web_search.search_query("iPhone 18 什么时候发布", "日期"), "iPhone 18 发布时间")
        self.assertEqual(web_search.search_query("deepseek 是什么版本", "版本"), "deepseek 最新版本")
        self.assertEqual(web_search.search_query("费米悖论是什么", "你让我查的"), "费米悖论")

    def test_cache_ttl_is_shorter_for_timely_questions(self):
        self.assertEqual(web_search.cache_ttl_for("时事"), web_search.CACHE_TTL_FAST)
        self.assertEqual(web_search.cache_ttl_for("你让我查的"), web_search.CACHE_TTL)


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
            return [{"title": "问题找到了", "url": "https://x.com/a", "snippet": "问题 内容"}]
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
            return [{"title": "问题 t%d" % i, "url": "https://x.com/%d" % i, "snippet": "问题 内容"} for i in range(8)]
        found = web_search.search("问题", sources=[("多", many)])
        self.assertEqual(len(found["results"]), web_search.MAX_RESULTS)

    def test_offtopic_titles_are_dropped(self):
        """标题对不上题的（新闻列表首页之类）直接清掉：宁可说没查到，也别拿垃圾当资料。"""
        def junk(_query):
            return [{"title": "最新滚动新闻_网易新闻中心", "url": "https://news.163.com/",
                     "snippet": "城市更新 公园藏新意"},
                    {"title": "今日热榜", "url": "https://tophub.today/", "snippet": "床虱酒店地图"}]
        found = web_search.search("最新的 AI 模型", sources=[("垃圾源", junk)])
        self.assertEqual(found["results"], [])
        self.assertIn("对不上题", found["error"])

    def test_a_slow_source_does_not_hold_up_the_answer(self):
        done = threading.Event()

        def slow(_query):
            try:
                time.sleep(1.5)          # 比 GRACE_AFTER_FIRST 长，但别拖住整个测试进程
                return [{"title": "慢 问题", "url": "https://slow.example/a", "snippet": "问题"}]
            finally:
                done.set()

        def fast(_query):
            return [{"title": "快 问题", "url": "https://fast.example/b", "snippet": "问题"}]
        started = time.monotonic()
        found = web_search.search("问题", sources=[("慢", slow), ("快", fast)])
        self.assertLess(time.monotonic() - started, 3.0)        # 不为了等慢源拖住回答
        self.assertEqual(found["source"], "快")
        done.wait(3)                                            # 等后台线程收工，别留尾巴


class RankTests(unittest.TestCase):
    QUERY = "费米悖论是什么"

    def rank(self, batches):
        items = web_search.merge_results(batches)
        words, grams = web_search._terms(self.QUERY)
        for item in items:
            item["date"] = web_search.date_of(item)
            item["score"] = web_search.score_result(item, words, grams)
        return sorted(items, key=lambda row: -row["score"])

    def test_same_page_from_two_sources_is_merged(self):
        rows = [{"title": "费米悖论 - 百度百科", "url": "https://baike.baidu.com/item/x", "snippet": "短"}]
        merged = self.rank([("a", rows),
                            ("b", [dict(rows[0], snippet="更完整的摘要，讲了外星人和宇宙尺度的关系")])])
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(merged[0]["sources"]), ["a", "b"])
        self.assertIn("外星人", merged[0]["snippet"])            # 摘要取全的那条

    def test_relevant_result_beats_an_offtopic_one(self):
        ranked = self.rank([("a", [{"title": "费米悖论：为什么我们还没见到外星人",
                                    "url": "https://zh.wikipedia.org/wiki/费米悖论",
                                    "snippet": "费米悖论讨论的是宇宙尺度上生命罕见的问题"},
                                   {"title": "相关推荐：十大未解之谜排行榜",
                                    "url": "https://junk.example/list",
                                    "snippet": "推荐阅读"}] )])
        self.assertIn("费米悖论", ranked[0]["title"])

    def test_authoritative_site_gets_a_bonus(self):
        good = {"title": "费米悖论", "url": "https://arxiv.org/abs/1234", "snippet": "费米悖论讨论"}
        meh = {"title": "费米悖论", "url": "https://someblog.example/x", "snippet": "费米悖论讨论"}
        ranked = self.rank([("a", [meh, good])])
        self.assertIn("arxiv", ranked[0]["url"])

    def test_date_is_picked_up(self):
        self.assertEqual(web_search.date_of({"title": "2026-09-01 发布了新版本"}), "2026-09-01")
        self.assertEqual(web_search.date_of({"snippet": "3 小时前 更新"}), "3 小时前")
        self.assertEqual(web_search.date_of({"title": "没有日期"}), "")


class PageTextTests(unittest.TestCase):
    def test_page_text_goes_into_the_evidence(self):
        saved = web_search.read_web_page
        web_search.read_web_page = lambda url, limit=4000: "费米悖论的正文第一段，讲了宇宙尺度与生命概率的问题。"
        try:
            found = web_search.search("费米悖论", sources=[("假源", lambda q: [
                {"title": "费米悖论 - 百度百科", "url": "https://baike.baidu.com/item/x",
                 "snippet": "导航 登录 首页"}])], fetch=True)
        finally:
            web_search.read_web_page = saved
        self.assertIn("宇宙尺度", found["results"][0]["text"])
        block = web_search.format_evidence(found, "费米悖论")
        self.assertIn("宇宙尺度", block)          # 正文（不是导航摘要）进了资料块
        self.assertIn("以资料为准", block)        # 明确要求以资料为依据，不靠自己的旧知识
        self.assertIn("baike.baidu.com", block)

    def test_extract_text_drops_nav_and_scripts(self):
        page = ("<html><head><title>x</title><style>body{}</style></head><body>"
                "<nav>首页 登录 注册</nav><script>var a=1;</script>"
                "<article><p>费米悖论讨论的是宇宙尺度上文明稀少的可能性问题。</p>"
                "<p>这一段的第二句补足长度，保证不被短句过滤掉。</p></article>"
                "<footer>版权所有 联系我们</footer></body></html>")
        text = web_search.extract_text(page, limit=1000)
        self.assertIn("费米悖论", text)
        self.assertNotIn("登录", text)
        self.assertNotIn("版权所有", text)
        self.assertNotIn("var a", text)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "search-cache.json"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _sources(self):
        def source(query):
            return [{"title": "同一个问题 的结果", "url": "https://x.com/a", "snippet": "同一个问题 内容"}]
        return [("假源", source)]

    def test_second_identical_query_hits_the_cache(self):
        first = web_search.search_cached("同一个问题", self.path, sources=self._sources(), counter=self.calls)
        self.assertFalse(first.get("cached"))
        second = web_search.search_cached("同一个问题", self.path, sources=self._sources(), counter=self.calls)
        self.assertTrue(second.get("cached"))
        self.assertEqual(len(self.calls), 1)          # 只真的搜了一次
        self.assertEqual(second["results"][0]["title"], "同一个问题 的结果")

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
