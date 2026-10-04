"""记忆列表的性能与交互（2026-10-01 重写）。

用户反馈的这条链：
  1. 「长期记忆列表上下滑动时特别卡」
  2. 「不是滚动快慢的问题，就是滚动的时候是明显可见的掉帧，而且背景图层也在跟着动」
  3. 问「对话记录这个窗口内容也很多，为什么对话记录窗口就不会卡」
  4. 「不行不行 滚动的时候怎么是全部刷新了一遍 这下更奇怪了」
  5. 「不怎么卡了 但是一抖一抖的」
  6. 「还是卡啊 就是我滚动一次之后每一条都会上下滑动一下，你直接改成跟聊天记录窗口一样的方式呢」

**结论是第 6 条给的**：聊天记录窗口的 `ArtTranscript` 内容是
**Canvas 图形项**（`create_text` 之类），Tk 用 C 代码绘制，滚动纯粹是移动视口。
而记忆列表每行都是**真控件**，滚动时要重新布局绘制。
中途试过的"虚拟滚动 + 控件池"仍然要**在每次滚动重摆位置**，
那本身就表现为"每一条都上下滑动一下"。

现在：89 行 × 约 4 个图形项一次画完，**滚动时一个 item 都不动**。
编辑改成双击就地弹输入框（同时只存在一个 Entry）。
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source():
    return (ROOT / 'src/pet.py').read_text('utf-8')


def function(name):
    tree = ast.parse(source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('没找到 ' + name)


def calls(name):
    """函数体里**实际调用**到的名字。

    比在源码字符串里找关键字可靠：文档字符串和注释里会写"为什么不用 after_idle"，
    按字符串找就会把说明当违规。
    """
    found = []
    for node in ast.walk(function(name)):
        if isinstance(node, ast.Call):
            func = node.func
            found.append(func.attr if isinstance(func, ast.Attribute)
                         else func.id if isinstance(func, ast.Name) else '?')
    return found


class WheelScrollTests(unittest.TestCase):
    def setUp(self):
        self.src = ast.get_source_segment(source(), function('bind_wheel_scroll'))

    def test_the_step_is_no_longer_three_pixels(self):
        """原来 `yview_scroll(int(-delta/120) * 3, 'units')` —— 1 unit 默认就是 1 像素。"""
        self.assertIn('unit_pixels', self.src)
        self.assertIn('yscrollincrement', self.src)
        self.assertNotIn('int(-delta / 120) * 3', self.src)

    def test_events_are_not_coalesced(self):
        """滚轮不做合并。

        中途加过 `after_idle` 合并，用户反馈「一抖一抖的」——
        事件密集时 idle 很稀少，攒下的量会一次性跳出去。
        渲染那边已经便宜到可以直接跟，合并是多余且有害的。
        """
        self.assertNotIn('after_idle', calls('bind_wheel_scroll'))

    def test_it_scrolls_immediately_on_every_notch(self):
        self.assertIn('canvas.yview_scroll(-units if delta > 0 else units, "units")', self.src)

    def test_it_still_returns_break_so_the_parent_does_not_also_scroll(self):
        self.assertIn('return "break"', self.src)

    def test_the_sign_is_still_the_right_way_round(self):
        self.assertIn('-units if delta > 0 else units', self.src)

    def test_the_defaults_are_backwards_compatible_enough(self):
        args = function('bind_wheel_scroll').args
        names = [a.arg for a in args.args]
        self.assertEqual(names[:2], ['win', 'canvas'])
        defaults = [ast.literal_eval(d) for d in args.defaults]
        self.assertEqual(len(names) - len(defaults), 2, '只有 win/canvas 是必填')
        self.assertTrue(all(isinstance(d, int) and d > 0 for d in defaults), defaults)


class MemoryListDrawsItemsTests(unittest.TestCase):
    """行必须是 Canvas 图形项，不是子控件。"""

    def setUp(self):
        self.src = source()
        self.draw = ast.get_source_segment(self.src, function('_mem_draw'))

    def test_rows_are_drawn_as_canvas_items(self):
        for item in ('create_text', 'create_rectangle'):
            self.assertIn(item, self.draw, item)

    def test_no_child_widget_per_row(self):
        """这是整条链的结论：一行一个真控件就是卡的根源。"""
        for widget in ('tk.Frame', 'tk.Label', 'tk.Entry', 'tk.Button'):
            self.assertNotIn(widget, self.draw, widget)

    def test_it_redraws_by_deleting_its_own_tag(self):
        self.assertIn("delete('mem')", self.draw)

    def test_scrolling_does_not_rebuild_rows(self):
        """滚动路径里不许重建/重摆行——这是"每一条都上下滑动"的来源。

        `yscrollcommand` 上只允许挂两件事：滚动条同步、背景图对齐
        （后者是一次 `coords()`，不是重算）。
        """
        window = ast.get_source_segment(self.src, function('show_memory'))
        code = '\n'.join(l for l in window.splitlines() if not l.strip().startswith('#'))
        self.assertIn('canvas.configure(yscrollcommand=vsb.set)', code)
        # 只看 yscrollcommand 那一行：它每次滚动都会跑。
        # （<Configure> 里的 _mem_draw 是窗口缩放时的重画，合理。）
        yscroll = next(l for l in code.splitlines() if 'yscrollcommand=' in l)
        for forbidden in ('_mem_draw', '_mem_render', 'place(', 'coords('):
            self.assertNotIn(forbidden, yscroll, forbidden)

    def test_the_scrollregion_is_set_explicitly(self):
        seg = ast.get_source_segment(self.src, function('_mem_set_scrollregion'))
        self.assertIn('MEM_ROW_HEIGHT', seg)
        self.assertIn('len(items)', seg)
        self.assertNotIn('bbox', calls('_mem_set_scrollregion'))

    def test_rows_go_stale_when_the_content_is_long(self):
        seg = ast.get_source_segment(self.src, function('_mem_text'))
        self.assertIn('…', seg, '图形项不会自动裁切，长内容要截断')

    def test_click_targets_are_bound_per_row(self):
        for tag in ('memdel:', 'memfield:'):
            self.assertIn(tag, self.draw, tag)


class MemoryCanvasPortTests(unittest.TestCase):
    """照对话记录窗口（`ArtTranscript`）的做法搬过来（2026-10-01）。

    用户问：「为什么对话记录窗口就能自己滚动 你直接把对话记录窗口的代码迁移过来不就好了」
    ——**问得对**。`ArtTranscript` 的做法是：

        def scroll(self, amount, units='units'):
            super().yview_scroll(amount, units)   # 原生滚动
            self.paint()                          # ← 同一次调用里把背景挪回去

        def paint(self):
            x, top = self.canvasx(0), self.canvasy(0)
            self.coords('art', x, top)            # ← 只挪位置，不重裁不重算

    它也挂同一套模糊背景、也用原生滚动，却不晃——差别就在对齐是**同步**做的，
    不是窗口背景系统那种 `after(24, draw)` 重算。

    中途走过一次弯路：把画布标成 `_art_decoration` 排除出去（不晃了但看不见背景图），
    又自己裁图贴上去（看不见的问题解决了但又开始晃）。**其实照搬这个类就行。**
    """

    def setUp(self):
        self.src = source()
        self.cls = ast.get_source_segment(self.src, memory_canvas_class())

    def test_there_is_a_memory_canvas_subclass(self):
        self.assertTrue(self.cls)
        self.assertIn('tk.Canvas', self.cls)

    def test_it_aligns_the_backdrop_synchronously_after_scrolling(self):
        for name in ('yview_scroll', 'yview'):
            seg = ast.get_source_segment(self.src, memory_canvas_method(name))
            self.assertIn('super().%s(' % name, seg, name)
            self.assertIn('align_backdrop', seg, name)

    def test_aligning_only_moves_the_item(self):
        """只许挪位置——重裁、重建 PhotoImage、延后重算，这三样都是"晃"的来源。"""
        seg = ast.get_source_segment(self.src, memory_canvas_method('align_backdrop'))
        self.assertIn("coords('window-backdrop'", seg)
        for slow in ('crop', 'PhotoImage', 'after', 'delete'):
            self.assertNotIn(slow, seg, slow)

    def test_the_canvas_participates_in_the_window_backdrop_again(self):
        window = ast.get_source_segment(self.src, function('show_memory'))
        code = '\n'.join(l for l in window.splitlines() if not l.strip().startswith('#'))
        self.assertNotIn('_art_decoration', code, '不能再排除出去了')
        self.assertIn('MemoryCanvas(', code)

    def test_the_tag_matches_what_backdrop_widgets_creates(self):
        widgets = (ROOT / 'src/backdrop_widgets.py').read_text('utf-8')
        self.assertIn("tags='window-backdrop'", widgets)
        self.assertIn("coords('window-backdrop'", widgets, '它自己也走同一条廉价路径')

    def test_rows_no_longer_have_a_solid_fill(self):
        # 文字直接落在背景图上（用户要的"文字背景透明"）
        self.assertNotIn('fill="#3a3a4e"', self.src)


def memory_canvas_class():
    for node in ast.walk(ast.parse(source())):
        if isinstance(node, ast.ClassDef) and node.name == 'MemoryCanvas':
            return node
    raise AssertionError('没找到 MemoryCanvas')


def memory_canvas_method(name):
    for node in memory_canvas_class().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('MemoryCanvas 里没找到 ' + name)


class MemoryEditTests(unittest.TestCase):
    def test_editing_opens_one_entry_at_a_time(self):
        seg = ast.get_source_segment(source(), function('_mem_edit_row'))
        self.assertIn('self._mem_close_editor()', seg, '开新的之前先收旧的')
        self.assertIn("tags='memedit'", seg)
        self.assertIn('create_window', seg)

    def test_leaving_the_box_commits(self):
        seg = ast.get_source_segment(source(), function('_mem_edit_row'))
        self.assertIn('FocusOut', seg)
        self.assertIn('Return', seg)
        self.assertIn('Escape', seg)

    def test_committing_redraws_the_row(self):
        seg = ast.get_source_segment(source(), function('_mem_commit_row'))
        self.assertIn('self._mem_draw()', seg, '输入框挡在图形项上，改完要重画')

    def test_edits_survive_redraws(self):
        """虚拟滚动/重画最容易出事的地方：编辑不能丢。

        StringVar 存在 `_mem_edits`（id → 变量），重画时复用；
        保存时读的也必须是它。
        """
        draw = ast.get_source_segment(source(), function('_mem_draw'))
        self.assertIn('self._mem_edits.get(item["id"])', draw)
        self.assertIn('self._mem_edits[item["id"]] = tk.StringVar', draw)
        save = ast.get_source_segment(source(), function('_save_memory_rows'))
        self.assertIn('_mem_edits', save)
        code = [l for l in save.splitlines() if not l.strip().startswith('#')]
        self.assertNotIn('_mem_rows', '\n'.join(code))

    def test_the_editor_is_cleared_when_the_window_closes(self):
        close = ast.get_source_segment(source(), function('_close_memory_window'))
        for name in ('_mem_edits', '_mem_items', '_mem_close_editor'):
            self.assertIn(name, close, name)


class MemoryBackdropTests(unittest.TestCase):
    def test_the_window_keeps_its_backdrop(self):
        """窗口保留模糊背景（标题栏、按钮那圈），列表画布也参与。"""
        window = ast.get_source_segment(source(), function('show_memory'))
        code = '\n'.join(l for l in window.splitlines() if not l.strip().startswith('#'))
        self.assertNotIn('_compact_surface', code)
        self.assertNotIn('_art_decoration', code)

    def test_the_scroll_offset_really_is_part_of_the_backdrop_key(self):
        """留个证据：说明"背景会跟着滚动偏移走"是设计，以及它为什么需要对齐。

        对齐本身没问题（`ArtTranscript` 就是这么做的，同步做就不晃）；
        有问题的是窗口系统那种 `after(24, draw)` 的**延后**重算。
        """
        art = (ROOT / 'src/window_art.py').read_text('utf-8')
        self.assertIn('canvasx(0)', art)
        self.assertIn('canvasy(0)', art)
        self.assertIn('after(24', art)


class MemoryRowWidgetsTests(unittest.TestCase):
    def test_detail_and_pin_buttons_are_gone(self):
        """用户实测「详情」和「置顶」两个按钮没有作用，已删（2026-10-01）。

        方法本身保留：`show_memory_details` 在 experience_ui 的 mixin 里、
        还被 experience_smoke 调用；`_mem_toggle_pin` 的 `pinned` 字段仍在排序里用。
        """
        draw = ast.get_source_segment(source(), function('_mem_draw'))
        self.assertNotIn('详情', draw)
        self.assertNotIn('置顶', draw)
        self.assertIn('删除', draw)


if __name__ == '__main__':
    unittest.main()
