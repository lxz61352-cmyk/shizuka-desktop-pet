"""First visible frame must already have settled geometry and artwork."""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from concurrent.futures import Future
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from ui_theme import install, page_header, apply
from window_opening import prepare, dialog_window
import window_opening
import window_art


class WindowOpeningTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk(); self.root.withdraw(); install(self.root)
        self.errors=[]; self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))

    def tearDown(self):
        self.root.destroy(); self.assertEqual(self.errors,[])

    def pump(self, seconds=.1):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.root.update(); time.sleep(.002)

    def visible(self, win):
        end=time.monotonic()+4
        while getattr(win,'_opening_pending',False) and time.monotonic()<end:self.pump(.01)
        self.assertFalse(win._opening_pending)
        self.assertEqual(float(win.attributes('-alpha')),1)

    def window(self):
        win=tk.Toplevel(self.root); prepare(win); win.geometry('700x500+50+50')
        page_header(win,'一次显示完整布局').pack(fill='x')
        return win

    def test_factory_prepares_before_early_constructor_measurement(self):
        win=dialog_window(self.root); win.geometry('700x500+50+50')
        ttk.Label(win,text='先测量、后创建标题').pack()
        win.update_idletasks()
        self.assertEqual(float(win.attributes('-alpha')),0)
        page_header(win,'统一打开').pack(fill='x')
        self.visible(win)
        self.assertEqual(win._opening_result,'ready')

    def test_constructor_measurements_cannot_expose_incomplete_layout(self):
        win=self.window(); win.update_idletasks()
        self.assertEqual(float(win.attributes('-alpha')),0)
        body=ttk.Frame(win,padding=22); body.pack(fill='both',expand=True)
        entry=ttk.Entry(body); entry.pack(fill='x')
        button=tk.Button(body,text='布局会由主题调整的按钮',font=('Arial',20)); button.pack()
        apply(win)
        samples=[]; deadline=time.monotonic()+4
        while win._opening_pending and time.monotonic()<deadline:
            self.pump(.003)
            if float(win.attributes('-alpha'))>0:
                samples.append((win.winfo_geometry(),entry.winfo_width(),entry.winfo_height(),entry.winfo_y(),
                                button.winfo_width(),button.winfo_height(),id(win._art_backdrop.image)))
        self.visible(win)
        self.assertTrue(samples)
        self.assertEqual(len(set(samples)),1,'Layout or artwork changed during the fade')
        self.assertEqual(win._opening_result,'ready')
        art=win._art_backdrop
        self.assertIsNotNone(art.image)
        geometry=lambda:(win.winfo_geometry(),entry.winfo_width(),entry.winfo_height(),
                         button.winfo_width(),button.winfo_height())
        first=geometry(); self.pump(.25)
        self.assertEqual(geometry(),first)
        self.assertEqual(art.signature,art.layout_signature())

    def test_slow_art_does_not_block_event_loop_or_reveal_early(self):
        future=Future(); ticks=[]
        with patch.object(window_art._WORKER,'submit',return_value=future):
            win=self.window(); ttk.Label(win,text='在后台准备').pack()
            self.root.after(10,lambda:ticks.append(True)); self.pump(.15)
            self.assertTrue(ticks); self.assertEqual(float(win.attributes('-alpha')),0)
            request=win._art_backdrop.request
            future.set_result(window_art._prepare(request)); self.visible(win)
            self.assertEqual(win._opening_result,'ready')

    def test_late_ready_frame_still_settles_and_fades(self):
        win=self.window(); ttk.Entry(win).pack(fill='x')
        offset=[0]
        def clock():
            art=getattr(win,'_art_backdrop',None)
            if art and art.image is not None and art.pending is None and art.signature==art.layout_signature():
                # Simulate a busy UI loop delivering the first usable frame
                # just after the preparation deadline.
                offset[0]=window_opening.MAX_PREPARE_SECONDS+1
            return time.monotonic()+offset[0]
        with patch.object(window_opening,'time',SimpleNamespace(monotonic=clock)):
            self.visible(win)
        self.assertEqual(offset[0],window_opening.MAX_PREPARE_SECONDS+1)
        self.assertEqual(win._opening_result,'ready')
        self.assertGreaterEqual(win._opening_ms-win._opening_prepare_ms,150)

    def test_close_while_preparing_and_timeout_do_not_leave_hidden_windows(self):
        future=Future()
        with patch.object(window_art._WORKER,'submit',return_value=future):
            win=self.window(); self.pump(.04); win.destroy(); self.pump(.1)
        with patch.object(window_art._WORKER,'submit',return_value=Future()),patch.object(window_opening,'MAX_PREPARE_SECONDS',.08):
            win=self.window(); self.visible(win)
            self.assertEqual(win._opening_result,'timeout')

    def test_reopening_and_compact_surfaces_are_not_hidden_again(self):
        win=self.window(); self.visible(win)
        prepare(win); self.assertEqual(float(win.attributes('-alpha')),1)
        win.withdraw(); prepare(win); win.deiconify()
        self.assertEqual(float(win.attributes('-alpha')),1)
        compact=tk.Toplevel(self.root); compact.overrideredirect(True); prepare(compact)
        self.assertFalse(getattr(compact,'_opening_pending',False))


if __name__=='__main__':unittest.main()
