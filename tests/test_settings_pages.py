"""Check persistent page switching, background reuse and keyboard navigation."""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from settings_pages import SettingsPages
from ui_theme import install, apply
import backdrop_widgets


class SettingsPagesTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk(); self.root.withdraw(); install(self.root)
        self.errors=[]; self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))
        self.win=tk.Toplevel(self.root); self.win.geometry('850x600+40+40')
        self.pages=SettingsPages(self.win,('一','二','三')); self.pages.pack(fill='both',expand=True)
        self.entries={}
        for title,body in self.pages.bodies.items():
            entry=ttk.Entry(body); entry.pack(fill='x'); self.entries[title]=entry
            for i in range(25):ttk.Label(body,text=f'{title} · 设置 {i}').pack(anchor='w',pady=4)
        self.pages.select('一'); apply(self.win)
        end=time.monotonic()+4
        while time.monotonic()<end:
            self.pump(.05)
            if hasattr(self.entries['一'],'_backdrop_photo'):break
        self.assertFalse(hasattr(self.entries['二'],'_backdrop_photo'))
        for title in ('二','三','一'):self.pages.select(title);self.pump(.1)
        self.assertTrue(all(hasattr(e,'_backdrop_photo') for e in self.entries.values()))
        self.pump(.1)

    def pump(self, seconds=.05):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.root.update(); time.sleep(.002)

    def tearDown(self):
        self.root.destroy(); self.assertEqual(self.errors,[])

    def test_switch_maps_only_selected_page_and_reuses_cached_background(self):
        art=self.win._art_backdrop; photo=art.photo; image=art.image
        with patch.object(backdrop_widgets,'update_photo',wraps=backdrop_widgets.update_photo) as upload:
            for title in ('二','三','一')*3:
                self.pages.select(title);self.pump()
                self.assertEqual([name for name,page in self.pages.pages.items() if page.winfo_ismapped()],[title])
            self.assertEqual(upload.call_count,0)
        self.assertIs(art.photo,photo); self.assertIs(art.image,image)

    def test_inputs_and_each_scroll_position_survive_switches(self):
        self.entries['二'].insert(0,'尚未保存 37')
        self.pages.select('二'); self.pages.canvases['二'].yview_moveto(.6); self.pump()
        offset=self.pages.canvases['二'].yview()
        self.pages.select('三'); self.pump(); self.pages.select('二'); self.pump()
        self.assertEqual(self.entries['二'].get(),'尚未保存 37')
        self.assertEqual(self.pages.canvases['二'].yview(),offset)
        self.pages.canvases['二'].yview_moveto(1); self.pump()
        self.assertGreater(self.pages.canvases['二'].yview()[1],.99)

    def test_inactive_pages_do_not_receive_keyboard_tab_focus(self):
        self.entries['一'].focus_force(); self.pump()
        self.pages.select('二'); self.pump()
        self.assertEqual(str(self.entries['一'].cget('takefocus')),'0')
        self.assertNotEqual(str(self.entries['二'].cget('takefocus')),'0')
        self.assertEqual(str(self.entries['三'].cget('takefocus')),'0')
        self.assertIsNot(self.root.focus_get(),self.entries['一'])


if __name__=='__main__':unittest.main()
