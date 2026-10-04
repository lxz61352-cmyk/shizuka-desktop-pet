"""空行分条：够长才拆。

两条实测教训：
1. 167 条微信回复里没有一条写过 [[WX_BREAK]]——模型一直用空行分段，而分条器只认标记，
   分条从来没生效过。所以空行也要当边界。
2. 但**没有门槛会拆过头**：拆成多条的比率从 14% 涨到 76%，一条十几字的回复被拆成两三条送达。
   所以空行只在"这一段已经攒够 SPLIT_MIN_CHARS 字"时才算边界。
"""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from weixin_segments import (BREAK, MORE, SPLIT_MIN_CHARS, SegmentBuffer, blank_breaks,
                             clean_control, ReplyProgress, generate)

# 一段够长的正文（≥ SPLIT_MIN_CHARS 字），用来测"该拆"的情形
LONG = ('线性轴就是直上直下，没有段落感，按到底顺滑，声音偏闷，打字快的人爱用。'
        '青轴段落感最强，按下去有咔哒一声，声音也很大，反馈清楚但是吵人。')
# 两段都不止一两个字——按现在的规则就该拆（用户 2026-10-01 的要求）
TWO_LINES = '哦，是搬快递搬哭了。'
# 极短的开头：并进后一条，不单独成一个气泡
TINY = '嗯。'
assert len(LONG) > SPLIT_MIN_CHARS, 'LONG 必须超过门槛，否则这些测试测不到"该拆"的情形'
assert len(TINY) < SPLIT_MIN_CHARS < len(TWO_LINES), '这两个样例必须卡在门槛两侧'


def segments(source, step=None):
    buf, out = SegmentBuffer(), []
    if step is None:
        out.extend(buf.feed(source))
    else:
        for at in range(0, len(source), step):
            out.extend(buf.feed(source[at:at + step]))
    tail, _more = buf.finish()
    return [clean_control(v).strip() for v in out] + [clean_control(tail).strip()]


class ThresholdTests(unittest.TestCase):
    def test_long_paragraphs_still_split(self):
        self.assertGreater(len(LONG), SPLIT_MIN_CHARS)
        self.assertEqual(segments(LONG + '\n\n' + LONG), [LONG, LONG])

    def test_two_short_but_real_lines_are_split(self):
        """用户 2026-10-01 的反馈：「前面还是有消息没分气泡，一个气泡里两行」。

        那三条都是两段都不短（10+10、8+16、14+18 字），却被并成一个气泡。
        门槛从 50 降到 6 之后就该拆开。
        """
        for first, second in (('哦，是搬快递搬哭了。', '几个啊，多到这种程度'),
                              ('哈哈哈，裂开了。', '那也得搬，不然它们不会自己上楼。'),
                              ('这我哪知道，我又没在那儿。', '长裤没干就穿短的，晒着晒着也就热了。')):
            self.assertEqual(segments(first + '\n\n' + second), [first, second],
                             '%s / %s 应该分成两个气泡' % (first, second))

    def test_a_tiny_opening_line_is_not_its_own_bubble(self):
        # 「嗯。」这种一两个字的开头并进后一条——这才是该合并的情形
        self.assertEqual(segments(TINY + '\n\n看什么书呢？'),
                         ['嗯。\n\n看什么书呢？'])

    def test_a_long_first_paragraph_before_a_short_one_still_splits(self):
        self.assertEqual(segments(LONG + '\n\n' + TINY), [LONG, TINY])

    def test_a_tiny_first_paragraph_with_a_long_second_does_not_split_early(self):
        # 第一段太短：那处空行不算边界；整条照样发出。
        self.assertEqual(segments(TINY + '\n\n' + LONG), [TINY + '\n\n' + LONG])

    def test_the_threshold_counts_non_space_characters(self):
        pad = '　' * 80          # 全角空格，不该把字数凑够
        self.assertEqual(segments(TINY + pad + '\n\n' + TINY),
                         [TINY + pad + '\n\n' + TINY])


class MarkerTests(unittest.TestCase):
    def test_an_explicit_break_splits_regardless_of_length(self):
        # [[WX_BREAK]] 是模型明确要求分条，不看长短。
        self.assertEqual(segments(TINY + BREAK + '看什么书呢？'), [TINY, '看什么书呢？'])

    def test_marker_and_blank_line_take_the_earlier_one(self):
        self.assertEqual(segments('甲' + BREAK + LONG + '\n\n' + LONG), ['甲', LONG, LONG])

    def test_at_most_two_breaks_keep_the_rest_together(self):
        out = segments(LONG + '\n\n' + LONG + '\n\n' + LONG + '\n\n' + LONG)
        self.assertEqual(len(out), 3)
        self.assertIn('\n\n', out[-1])

    def test_leading_and_trailing_blank_lines_do_not_make_empty_messages(self):
        self.assertEqual([s for s in segments('\n\n' + LONG + '\n\n') if s], [LONG])


class StreamTests(unittest.TestCase):
    def test_splits_across_every_possible_chunk_boundary(self):
        source = LONG + '\n\n' + LONG
        for step in range(1, len(source)):
            self.assertEqual(segments(source, step), [LONG, LONG], 'step=%d' % step)

    def test_blank_lines_inside_a_fence_are_not_boundaries(self):
        code = '```python\n' + '\n'.join('print(%d)' % i for i in range(12)) + '\n\nprint(99)\n```'
        self.assertGreater(len(code), SPLIT_MIN_CHARS)
        # 围栏里的那个空行不算边界，所以整块代码是一条。
        self.assertEqual(blank_breaks(code), [])
        self.assertEqual(segments(code + '\n\n' + LONG), [code, LONG])

    def test_an_unclosed_fence_still_swallows_later_blank_lines(self):
        buf = SegmentBuffer()
        self.assertEqual(buf.feed('```python\nprint(1)\n\n'), [])


class FakeClient:
    def __init__(self, *runs):
        self.runs, self.requests = list(runs), []
        self.chat = NS(completions=self)

    @contextmanager
    def create(self, **kwargs):
        self.requests.append(kwargs)
        run = self.runs.pop(0)

        def chunks():
            for item in run:
                yield NS(choices=[NS(delta=NS(content=item, reasoning_content='NO'))])
        yield chunks()


class DeliveryTests(unittest.TestCase):
    def progress(self, send=None):
        return ReplyProgress(lambda v: None, send or (lambda *args: None),
                             threading.Event(), threading.Event(), delay=False)

    def run_one(self, reply, pieces=None):
        sent = []
        progress = self.progress(lambda piece, index, cancel: sent.append(piece))
        client = FakeClient(pieces or [reply])
        generate(client, dict(model='fake', messages=[
            {'role': 'system', 'content': '角色'}, {'role': 'user', 'content': '测试'}]),
            progress, lambda v: v, lambda *a: None)
        return sent

    def test_a_long_reply_is_delivered_in_two_messages(self):
        self.assertEqual(self.run_one(LONG + '\n\n' + LONG), [LONG, LONG])

    def test_a_tiny_opening_line_is_delivered_once(self):
        # 「嗯。」这种一两个字的开头并进后一条，不单独成一个气泡
        self.assertEqual(self.run_one(TINY + '\n\n看什么书呢？'), ['嗯。\n\n看什么书呢？'])

    def test_a_streamed_blank_line_in_a_long_reply_still_sends_twice(self):
        self.assertEqual(self.run_one(None, pieces=[LONG, '\n', '\n' + LONG]), [LONG, LONG])


if __name__ == '__main__':
    unittest.main()
