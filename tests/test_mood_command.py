"""`/心情` 指令：只看状态、不进历史。

两条要求都来自用户：
  1. 能快捷查看当前心情
  2. **不进对话历史**——否则会影响她之后说话

所以这里盯两件事：
  · 命令必须走 `reply()`（它不写对话记录），而且**在命令分支里就返回**，
    不能落到正常回复路径上；
  · 读状态必须只读，不能动账本文件。
"""
import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import weixin_channel as wc  # noqa: E402


def source():
    return (ROOT / 'src/weixin_channel.py').read_text('utf-8')


def function(name):
    tree = ast.parse(source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('没找到 ' + name)


class CommandTests(unittest.TestCase):
    def test_both_spellings_are_recognised(self):
        text = source()
        self.assertIn('"/心情", "/mood"', text)

    def test_the_command_uses_reply_which_does_not_write_history(self):
        seg = ast.get_source_segment(source(), function('mood_text'))
        self.assertIn('mood_text', source())
        # reply() 不写记录（它只发送）；命令分支里也用 reply
        branch = source()[source().index('"/心情", "/mood"'):][:400]
        self.assertIn('self.reply(message', branch)
        self.assertNotIn('_log_chat', branch)
        self.assertNotIn('queue_job', branch, '不能落到正常回复路径上')

    def test_it_is_read_only(self):
        seg = ast.get_source_segment(source(), function('mood_text'))
        self.assertIn('read_text', seg)
        for forbidden in ('write_text', 'update(', 'commit(', 'save('):
            self.assertNotIn(forbidden, seg, '/心情 只该读，不该写')

    def test_the_state_wrapper_is_unwrapped(self):
        """账本文件外层是 {schema, state, version}，真正的状态在 state 里。

        第一版直接读顶层，mood 拿到 None，算精力时抛 TypeError。
        """
        seg = ast.get_source_segment(source(), function('mood_text'))
        self.assertIn("blob.get('state')", seg)

    def test_a_missing_file_says_so_instead_of_crashing(self):
        seg = ast.get_source_segment(source(), function('mood_text'))
        self.assertIn('还没有心情记录', seg)
        self.assertIn('except Exception', seg)

    def test_the_help_text_lists_it(self):
        self.assertIn('/心情', source())
        self.assertIn('不进对话记录', source())


class RealStateTests(unittest.TestCase):
    def test_it_reads_the_real_ledger_without_touching_it(self):
        paths = list((ROOT / 'data').glob('pre-reply-affect-*.json'))
        if not paths:
            self.skipTest('还没有心情账本')
        path = paths[0]
        before = path.read_bytes()

        class Store:
            class path:
                parent = ROOT / 'data'

        channel = wc.WeixinChannel.__new__(wc.WeixinChannel)
        channel.store = Store()
        text = channel.mood_text()

        self.assertEqual(path.read_bytes(), before, '不许改账本文件')
        self.assertNotIn('读心情失败', text)
        self.assertIn('心情', text)
        self.assertIn('精力', text)
        self.assertIn('不进她的对话记录', text)


if __name__ == '__main__':
    unittest.main()
