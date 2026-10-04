"""微信表情包：挑图、门槛、概率、以及不抛错的发送。

用户 2026-10-01 决定门槛先定 `clear`——实测（测试记录/震惊判定验证-2026-10-01/）
20 条里没有一条判到 `strong`，把表情包绑死在 strong 上等于功能不存在。
"""
import base64
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import weixin_stickers as stickers  # noqa: E402


def book(tmp, rows, *, chance=1.0, policy=None, rng=None):
    """建一个测试用登记表。

    `rng` 默认返回 0.0——**总是过概率那一关**，这样阈值类测试才是确定的。
    （2026-10-01 加了概率上限 MAX_CHANCE=0.5，`chance=1.0` 也会被压到 0.5，
    用真随机源的话"该发就该发"这类断言会时好时坏。）
    """
    tmp.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (tmp / row['file']).write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 32)
    (tmp / 'index.json').write_text(json.dumps(
        {'version': 1, 'policy': policy or {'min_intensity': 'clear', 'chance': chance},
         'stickers': rows}, ensure_ascii=False), 'utf-8')
    return stickers.StickerBook(tmp, chance=chance, rng=rng or (lambda: 0.0))


SHOCK = {'file': '震惊_强烈_shocked.png', 'name': '震惊', 'aliases': ['震惊', '惊讶'],
         'emotion': 'surprised', 'min_intensity': 'clear'}


class PickTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_fires_at_the_registered_threshold(self):
        b = book(self.tmp, [SHOCK])
        self.assertIsNotNone(b.pick('surprised', 'clear'))
        self.assertIsNotNone(b.pick('surprised', 'strong'))

    def test_does_not_fire_below_the_threshold(self):
        b = book(self.tmp, [SHOCK])
        self.assertIsNone(b.pick('surprised', 'light'))
        self.assertIsNone(b.pick('surprised', 'none'))

    def test_unrelated_emotions_never_fire_it(self):
        b = book(self.tmp, [SHOCK])
        for emotion in ('neutral', 'pleased', 'amused', 'excited', 'annoyed', 'sad',
                        'concerned', 'embarrassed', 'puzzled', 'speechless', ''):
            self.assertIsNone(b.pick(emotion, 'strong'), emotion)

    def test_neutral_never_fires_even_at_strong(self):
        b = book(self.tmp, [dict(SHOCK, min_intensity='light')])
        self.assertIsNone(b.pick('neutral', 'strong'))

    def test_chance_is_an_extra_gate(self):
        b = book(self.tmp, [SHOCK], chance=0.0)
        self.assertIsNone(b.pick('surprised', 'strong'), '概率为 0 时即使判到也不发')

    def test_the_same_sticker_is_not_sent_twice_in_a_row(self):
        b = book(self.tmp, [SHOCK])
        self.assertIsNone(b.pick('surprised', 'strong', exclude=SHOCK['file']))

    def test_a_missing_file_is_skipped_not_crashed(self):
        b = book(self.tmp, [SHOCK])
        (self.tmp / SHOCK['file']).unlink()
        self.assertIsNone(b.pick('surprised', 'strong'))

    def test_a_missing_or_broken_index_is_not_fatal(self):
        b = stickers.StickerBook(self.tmp / 'nope', chance=1.0)
        self.assertEqual(b.load(), [])
        self.assertIsNone(b.pick('surprised', 'strong'))
        (self.tmp / 'index.json').write_text('not json', 'utf-8')
        self.assertIsNone(stickers.StickerBook(self.tmp, chance=1.0).pick('surprised', 'strong'))


class SendTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / 'a.png'
        self.image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'y' * 200)

    def client(self, *, upload=None, status=200, header='PARAM'):
        seen = []

        class Completions:
            pass

        class C:
            def __init__(inner):
                inner.seen = seen

            def call(inner, endpoint, payload, timeout=20):
                seen.append((endpoint, payload))
                if endpoint == 'getuploadurl':
                    if upload is not None:
                        return upload
                    return {'upload_full_url': 'https://novac2c.cdn.weixin.qq.com/c2c/upload?x=1'}
                # sendmessage 要回 message_id——调用方拿它写引用缓存
                return {'message_id': '7511' + '0' * 14}

        return C()

    def test_a_successful_send_returns_the_message_id_for_the_quote_cache(self):
        """返回 message_id 而不是 True——调用方要拿它写引用缓存。

        不写的话，用户引用这张表情包再问时查不到原文，
        会回「这条引用的原消息没有保存在本机」（实测就是这个原因）。
        """
        client = self.client()
        original = stickers.request.urlopen
        stickers.request.urlopen = self.fake_urlopen([])
        try:
            result = stickers.send_image(client, 'peer', 'ctx', self.image, 'cid')
        finally:
            stickers.request.urlopen = original
        self.assertTrue(result, '成功时要返回 message_id（真值）')
        self.assertEqual(result, '7511' + '0' * 14)

    def fake_urlopen(self, record, *, status=200, header='PARAM'):
        @contextmanager
        def fake(req, timeout=None):
            record.append(req)
            yield NS(status=status, headers={'x-encrypted-param': header},
                     read=lambda *a: b'', __enter__=lambda s: s)
        return fake

    def test_the_aes_key_field_matches_the_official_encoding(self):
        """这一步错了图就显示不出来——不是格式偏好问题。

        实测（2026-10-01，同一张图连发两条）：
          24 字符（base64 原始 16 字节）→ 微信显示「图片已过期或已被清理」
          44 字符（base64 hex 字符串）  → 正常显示
        官方 SDK 发的是后者，我们原来写成前者，所以之前的表情包一张都没成功过。
        """
        key = bytes(range(16))
        value = stickers.aes_key_field(key)
        self.assertEqual(value, base64.b64encode(key.hex().encode('ascii')).decode('ascii'))
        self.assertEqual(len(value), 44, '必须是 44 字符，不是 24')
        self.assertNotEqual(value, base64.b64encode(key).decode('ascii'))

    def test_a_successful_send_posts_ciphertext_then_sends_an_image_item(self):
        client = self.client()
        posted = []
        original = stickers.request.urlopen
        stickers.request.urlopen = self.fake_urlopen(posted)
        try:
            ok = stickers.send_image(client, 'peer', 'ctx', self.image, 'cid')
        finally:
            stickers.request.urlopen = original
        self.assertTrue(ok)
        self.assertEqual([e for e, _ in client.seen], ['getuploadurl', 'sendmessage'])
        item = client.seen[1][1]['msg']['item_list'][0]
        self.assertEqual(item['type'], 2)
        self.assertEqual(item['image_item']['media']['encrypt_query_param'], 'PARAM')
        self.assertEqual(item['image_item']['media']['encrypt_type'], 1)
        self.assertTrue(item['image_item']['media']['aes_key'])
        # 上传的是密文，且大小是 16 的整数倍（AES-128-ECB + PKCS#7）
        self.assertEqual(len(posted), 1)
        self.assertEqual(len(posted[0].data) % 16, 0)

    def test_missing_upload_url_gives_up_quietly(self):
        client = self.client(upload={})
        self.assertFalse(stickers.send_image(client, 'peer', 'ctx', self.image, 'cid'))

    def test_missing_download_param_gives_up_quietly(self):
        client = self.client()
        original = stickers.request.urlopen
        stickers.request.urlopen = self.fake_urlopen([], header=None)
        try:
            self.assertFalse(stickers.send_image(client, 'peer', 'ctx', self.image, 'cid'))
        finally:
            stickers.request.urlopen = original

    def test_network_failure_never_raises(self):
        client = self.client()

        def boom(req, timeout=None):
            raise OSError('offline')

        original = stickers.request.urlopen
        stickers.request.urlopen = boom
        try:
            self.assertFalse(stickers.send_image(client, 'peer', 'ctx', self.image, 'cid'))
        finally:
            stickers.request.urlopen = original

    def test_a_missing_local_file_never_raises(self):
        self.assertFalse(stickers.send_image(self.client(), 'peer', 'ctx',
                                             self.tmp / 'nope.png', 'cid'))

    def test_no_request_is_made_when_the_file_is_missing(self):
        client = self.client()
        stickers.send_image(client, 'peer', 'ctx', self.tmp / 'nope.png', 'cid')
        self.assertEqual(client.seen, [])


class RegistryTests(unittest.TestCase):
    def test_the_reviewed_sticker_is_registered_with_the_agreed_policy(self):
        path = ROOT / 'data/stickers/index.json'
        if not path.is_file():
            self.skipTest('还没有登记表')
        data = json.loads(path.read_text('utf-8'))
        self.assertEqual(data['policy']['min_intensity'], 'clear')
        row = next(r for r in data['stickers'] if r['name'] == '震惊')
        self.assertEqual(row['emotion'], 'surprised')
        self.assertEqual(row['min_intensity'], 'clear')
        self.assertTrue((path.parent / row['file']).is_file(), row['file'])


class ChanceTests(unittest.TestCase):
    """概率分两层：单张图可以覆盖；否则 全局 chance × 情绪系数。

    用户 2026-10-01 提的：`amused` 日常出现最多，直接挂表情包会太频繁，
    所以给它一个系数，而不是给每张图硬编码。
    """

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_the_emotion_weight_scales_the_global_chance(self):
        b = book(self.tmp, [SHOCK], chance=0.5,
                 policy={'chance': 0.5, 'emotion_weight': {'surprised': 1.0, 'amused': 0.4}})
        self.assertAlmostEqual(b.chance_for(SHOCK, 'surprised'), 0.5)
        self.assertAlmostEqual(b.chance_for(SHOCK, 'amused'), 0.2)

    def test_an_unlisted_emotion_uses_the_global_chance(self):
        b = book(self.tmp, [SHOCK], chance=0.5,
                 policy={'chance': 0.5, 'emotion_weight': {'amused': 0.4}})
        self.assertAlmostEqual(b.chance_for(SHOCK, 'puzzled'), 0.5)

    def test_a_single_sticker_can_override_its_own_chance(self):
        row = dict(SHOCK, chance=0.05)
        b = book(self.tmp, [row], chance=0.5,
                 policy={'chance': 0.5, 'emotion_weight': {'surprised': 1.0}})
        self.assertAlmostEqual(b.chance_for(row, 'surprised'), 0.05,
                               msg='单张图的概率优先于系数')

    def test_the_result_is_always_a_probability(self):
        b = book(self.tmp, [SHOCK], chance=0.9,
                 policy={'chance': 0.9, 'emotion_weight': {'amused': 5.0, 'sad': -1}})
        for emotion in ('amused', 'sad', 'other'):
            value = b.chance_for(SHOCK, emotion)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_the_common_emotion_is_the_most_restrained(self):
        self.assertLess(stickers.DEFAULT_EMOTION_WEIGHT['amused'], 1.0,
                        '最常见的 amused 必须被压一档')
        # 2026-10-01 起 surprised 也从 1.0 压到 0.70——
        # 写着 1.0 等于没压，和"缺省 1.0"是同一个口子。
        self.assertLess(stickers.DEFAULT_EMOTION_WEIGHT['surprised'], 1.0)
        self.assertLess(stickers.DEFAULT_EMOTION_WEIGHT['amused'],
                        stickers.DEFAULT_EMOTION_WEIGHT['surprised'])


class ChancePolicyTests(unittest.TestCase):
    """发送时机全部走概率（2026-10-01 用户要求）。

    用户：「发送表情包的时机全部改成概率发送，而且现在的概率稍微有一点高 降低一点」。

    改之前有两个口子：
      · `emotion_weight` 只写了 3 个情绪，**其余 8 个走缺省的 1.0**——
        「有没有写」实际决定了概率，缺省那条路等于没设防；
      · `surprised` 明确写着 1.0，和缺省一样，等于没压。
    """

    EMOTIONS = ('neutral', 'pleased', 'amused', 'excited', 'annoyed', 'sad',
                'concerned', 'embarrassed', 'puzzled', 'speechless', 'surprised')

    def book(self):
        return stickers.StickerBook(ROOT / 'data/stickers')

    def test_every_emotion_has_an_explicit_weight(self):
        weights = stickers.DEFAULT_EMOTION_WEIGHT
        for emotion in self.EMOTIONS:
            self.assertIn(emotion, weights, '缺 %s —— 隐含的 1.0 就是没设防' % emotion)
        self.assertEqual(set(weights), set(self.EMOTIONS), '不该有别的键')

    def test_no_emotion_is_deterministic(self):
        book = self.book()
        for emotion in self.EMOTIONS:
            got = book.chance_for({}, emotion)
            self.assertLessEqual(got, stickers.MAX_CHANCE,
                                 '%s 的概率必须低于上限' % emotion)
            self.assertLess(got, 1.0, '%s 不能变成必发' % emotion)

    def test_the_base_chance_came_down(self):
        self.assertLess(stickers.DEFAULT_CHANCE, 0.5, '用户说原来"稍微有一点高"')
        self.assertEqual(self.book().chance, stickers.DEFAULT_CHANCE)

    def test_a_per_row_chance_of_one_is_capped(self):
        """单张图把 chance 写成 1.0 也只会被压到上限——配置写错不该变成必发。"""
        self.assertEqual(self.book().chance_for({'chance': 1.0}, 'surprised'),
                         stickers.MAX_CHANCE)

    def test_the_cap_is_a_real_ceiling_below_one(self):
        self.assertLess(stickers.MAX_CHANCE, 1.0)
        book = self.book()
        # 就算系数拉满，也过不去（chance 是只读属性，改政策字典来模拟）
        book._policy = dict(book.policy(), emotion_weight={e: 1.0 for e in self.EMOTIONS})
        for emotion in self.EMOTIONS:
            self.assertLessEqual(book.chance_for({}, emotion), stickers.MAX_CHANCE)

    def test_the_common_emotions_are_the_most_restrained(self):
        """系数表达"越常见的情绪越克制"。"""
        weights = stickers.DEFAULT_EMOTION_WEIGHT
        self.assertLess(weights['amused'], weights['surprised'])
        self.assertLess(weights['pleased'], weights['surprised'])


if __name__ == '__main__':
    unittest.main()
