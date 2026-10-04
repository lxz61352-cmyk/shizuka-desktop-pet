"""360/搜狗的解析：标题和链接不能读反；缓存分档不能反。

**为什么有这一组**：2026-10-03 的审查发现两个已有问题——
  · `_html_results` 按位置取组（1 当标题、2 当链接），而两个调用处的正则里
    href 在前、标题在后 → **标题字段一直是网址、url 字段一直是标题文字**；
    `_site_of(url)` 跟着算错，模型看到的"标题"是网址。
  · 「帮我搜一下最新的 X」的 reason 是"你让我查的"，**不在快档名单里**，
    于是拿到 6 小时缓存；而随口一问的时事查询是 45 分钟——**正好反了**。

**全部离线**：HTML 是样例字符串，不联网。
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import web_search


SO360_HTML = '''
<html><body><ul>
<li class="res-list">
  <h3><a href="https://www.so.com/link?m=abc" target="_blank">DeepSeek 官方文档</a></h3>
  <p class="res-desc">这是摘要文字。</p>
</li>
<li class="res-list">
  <h3><a href="https://example.com/news">某条新闻标题</a></h3>
  <p>另一段摘要。</p>
</li>
</ul></body></html>
'''

SOGOU_HTML = '''
<html><body>
<div class="vrwrap">
  <h3><a href="https://www.sogou.com/link?url=xyz">搜狗结果标题</a></h3>
  <div class="text-layout">摘要内容在这里。</div>
</div>
<div class="vrwrap">
  <h3><a href="https://another.example/a">第二条标题</a></h3>
</div>
</body></html>
'''

BLOCK_360 = r'(?is)<li[^>]*class="[^"]*res-list[^"]*".*?</li>'
LINK_360 = r'<h3[^>]*>\s*<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
BLOCK_SOGOU = r'(?is)<div[^>]*class="[^"]*vrwrap[^"]*".*?</div>'
LINK_SOGOU = r'<h3[^>]*>\s*<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'


class ParserTests(unittest.TestCase):
    def check(self, results, expect_first_title, expect_first_url):
        self.assertTrue(results, '一条都没解析出来')
        first = results[0]
        self.assertEqual(first['title'], expect_first_title,
                         '标题字段拿到的应该是标题，不是网址')
        self.assertEqual(first['url'], expect_first_url,
                         'url 字段拿到的应该是链接，不是标题')

    def test_so360_title_and_url_are_not_swapped(self):
        out = web_search._html_results(SO360_HTML, BLOCK_360, LINK_360)
        self.check(out, 'DeepSeek 官方文档', 'https://www.so.com/link?m=abc')

    def test_sogou_title_and_url_are_not_swapped(self):
        out = web_search._html_results(SOGOU_HTML, BLOCK_SOGOU, LINK_SOGOU)
        self.check(out, '搜狗结果标题', 'https://www.sogou.com/link?url=xyz')

    def test_it_parses_every_block(self):
        out = web_search._html_results(SO360_HTML, BLOCK_360, LINK_360)
        self.assertEqual([r['title'] for r in out],
                         ['DeepSeek 官方文档', '某条新闻标题'])

    def test_url_never_looks_like_prose_and_title_never_looks_like_a_url(self):
        # 读反的典型症状：标题长成 http…、url 是一句中文
        for results in (web_search._html_results(SO360_HTML, BLOCK_360, LINK_360),
                        web_search._html_results(SOGOU_HTML, BLOCK_SOGOU, LINK_SOGOU)):
            for row in results:
                self.assertFalse(row['title'].startswith('http'),
                                 '标题不该是网址：%r' % row['title'])
                self.assertFalse(re.search(r'[\u4e00-\u9fff]', row['url'] or ''),
                                 'url 不该是中文标题：%r' % row['url'])

    def test_a_pattern_without_named_groups_is_skipped(self):
        # 没给命名组就跳过——**不去猜位置**，免得又读反
        out = web_search._html_results(SO360_HTML, BLOCK_360,
                                       r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>')
        self.assertEqual(out, [])

    def test_site_of_gets_a_real_host(self):
        out = web_search._html_results(SO360_HTML, BLOCK_360, LINK_360)
        self.assertIn('so.com', web_search._site_of(out[0]['url']))


class CacheTtlTests(unittest.TestCase):
    def test_explicit_request_gets_the_shortest_ttl(self):
        # 用户明确说要查 → 最不该拿到旧缓存
        self.assertEqual(web_search.cache_ttl_for('你让我查的'),
                         web_search.CACHE_TTL_EXPLICIT)
        self.assertEqual(web_search.cache_ttl_for('她判断需要查'),
                         web_search.CACHE_TTL_EXPLICIT)

    def test_explicit_is_shorter_than_timely_and_default(self):
        self.assertLess(web_search.CACHE_TTL_EXPLICIT, web_search.CACHE_TTL_FAST)
        self.assertLess(web_search.CACHE_TTL_FAST, web_search.CACHE_TTL)

    def test_timely_still_uses_the_fast_tier(self):
        for reason in ('时事', '版本', '数字', '日期'):
            self.assertEqual(web_search.cache_ttl_for(reason),
                             web_search.CACHE_TTL_FAST, reason)

    def test_unknown_reason_uses_the_default(self):
        self.assertEqual(web_search.cache_ttl_for(''), web_search.CACHE_TTL)
        self.assertEqual(web_search.cache_ttl_for('随便什么'), web_search.CACHE_TTL)


if __name__ == '__main__':
    unittest.main()
