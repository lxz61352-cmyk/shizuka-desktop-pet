"""联网证据共用层：通道边界必须守住。

**为什么要有这些测试**：
2026-10-02 我把桌面的搜索直接搬到微信，害她的动作差分卡在"低头看手机"上不下来
（换回来要靠 `_reporting_now`，微信不触发它）。所以这里的重点是——
**channel='weixin' 时绝不能碰桌面的演出**。

全部离线：web_search 用假的替换掉，不联网。
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import reply_turn


class FakeWebSearch(types.ModuleType):
    """假的 web_search：记录被调了什么，不联网。"""

    def __init__(self, *, results=True, boom=False):
        super().__init__('web_search')
        import re
        self.EXPLICIT_RE = re.compile(r'帮我搜|搜一下|查一下|查资料')
        self.calls = []
        self._results = results
        self._boom = boom

    def needs_search(self, text):
        self.calls.append(('needs_search', text))
        return bool(self.EXPLICIT_RE.search(text or '')), '测试'

    def search_query(self, text, reason):
        self.calls.append(('search_query', text))
        return '测试检索词'

    def search_cached(self, query, path, ttl=0):
        self.calls.append(('search_cached', query))
        if self._boom:
            raise RuntimeError('boom')
        return {'query': query, 'results': ([{'title': 't', 'url': 'https://e.com',
                                              'text': '正文'}] if self._results else []),
                'source': 'fake', 'seconds': 0.1}

    def cache_ttl_for(self, reason):
        return 0

    def format_evidence(self, found, query=''):
        self.calls.append(('format_evidence', query))
        return '【联网查到的资料】测试证据块'

    def format_failure(self, found):
        self.calls.append(('format_failure', None))
        return '【联网】没搜到'


class FakeEngine:
    def __init__(self):
        self._web_search_on = True
        self._voice_on = False
        self._conv_id = 'conv-1'
        self.announced = []
        self.done = 0
        self.bubbles = 0
        self.probes = []

    def _search_probe(self, note):
        self.probes.append(note)

    def _announce_search(self, reason):
        self.announced.append(reason)

    def _search_done(self):
        self.done += 1

    def _ui(self, fn):
        self.bubbles += 1

    def _close_loading_bubble(self):
        pass


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.saved = sys.modules.get('web_search')

    def tearDown(self):
        if self.saved is not None:
            sys.modules['web_search'] = self.saved
        else:
            sys.modules.pop('web_search', None)

    def use(self, **kw):
        fake = FakeWebSearch(**kw)
        sys.modules['web_search'] = fake
        return fake

    # ---------- 通道边界（这一组最重要）----------
    def test_weixin_never_touches_desktop_acting(self):
        self.use()
        out = reply_turn.evidence(self.engine, '帮我搜一下新闻', channel='weixin')
        self.assertTrue(out.startswith('【联网查到的资料】'))
        self.assertEqual(self.engine.announced, [], '微信不该触发桌面气泡')
        self.assertEqual(self.engine.done, 0, '微信不该触发差分计时')
        self.assertEqual(self.engine.bubbles, 0, '微信不该碰桌面气泡')

    def test_desktop_does_announce(self):
        self.use()
        reply_turn.evidence(self.engine, '帮我搜一下新闻', channel='desktop')
        self.assertEqual(len(self.engine.announced), 1)
        self.assertEqual(self.engine.done, 1)

    # ---------- 闸门 ----------
    def test_setting_off_means_no_search(self):
        fake = self.use()
        self.engine._web_search_on = False
        self.assertEqual(reply_turn.evidence(self.engine, '帮我搜一下新闻'), '')
        self.assertEqual(fake.calls, [], '关着就不该调用搜索')

    def test_not_an_explicit_request_means_no_search(self):
        fake = self.use()
        self.assertEqual(reply_turn.evidence(self.engine, '今天有点累'), '')
        self.assertEqual([c for c in fake.calls if c[0] == 'search_cached'], [])

    def test_explicit_request_searches(self):
        fake = self.use()
        out = reply_turn.evidence(self.engine, '帮我搜一下新闻')
        self.assertIn('测试证据块', out)
        self.assertIn(('search_cached', '测试检索词'), fake.calls)

    # ---------- 失败一律不搜 ----------
    def test_search_error_falls_back_to_the_failure_note(self):
        # 这是**原有行为**（照搬过来的）：搜索抛异常时返回"没搜到"的说明，
        # 让她可以如实说没查到，而不是假装有资料。重构不改语义。
        self.use(boom=True)
        out = reply_turn.evidence(self.engine, '帮我搜一下新闻')
        self.assertIn('没搜到', out)

    def test_no_results_returns_the_failure_note(self):
        self.use(results=False)
        out = reply_turn.evidence(self.engine, '帮我搜一下新闻')
        self.assertIn('没搜到', out)

    # ---------- 探针 ----------
    def test_it_leaves_a_trace_each_step(self):
        self.use()
        reply_turn.evidence(self.engine, '帮我搜一下新闻')
        joined = ' | '.join(self.engine.probes)
        self.assertIn('入口', joined)
        self.assertIn('开搜', joined)
        self.assertIn('搜到', joined)

    def test_it_records_the_channel(self):
        self.use()
        reply_turn.evidence(self.engine, '帮我搜一下新闻', channel='weixin')
        self.assertIn('channel=weixin', self.engine.probes[0])


if __name__ == '__main__':
    unittest.main()
