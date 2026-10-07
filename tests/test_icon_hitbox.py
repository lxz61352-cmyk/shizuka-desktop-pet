"""Native Windows hit tests for the todo icon's transparent gaps."""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest

from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


@unittest.skipUnless(sys.platform == 'win32', 'Windows layered window hit testing')
class IconHitboxTests(unittest.TestCase):
    def setUp(self):
        from layered_window import set_image
        tree = ast.parse((ROOT / 'src/pet.py').read_text('utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeskPet')
        names = {'set_window_transparent', '_create_icon_button', '_set_icon_hitbox', '_resize_buttons'}
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        scope = dict(tk=tk, Image=Image, ImageTk=ImageTk, TRANS_COLOR='#000001',
                     GEAR_SIZE=30, set_layered_image=set_image)
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'icon methods', 'exec'), scope)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = SimpleNamespace(root=self.root)
        for name in names:
            setattr(self.app, name, scope[name].__get__(self.app))
        with Image.open(ROOT / 'assets/todo_icon.png') as image:
            self.source = image.convert('RGBA')
        self.user32 = ctypes.windll.user32
        self.user32.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user32.WindowFromPoint.restype = wintypes.HWND
        self.clicks = []

    def show_button(self, fill_hitbox):
        win, label = self.app._create_icon_button(
            self.source, '☑', lambda e: self.clicks.append((e.x, e.y)), fill_hitbox=fill_hitbox)
        win.geometry('+200+200')
        win.deiconify()
        win.lift()
        self.root.update()
        return win, label

    def native_hit(self, label, x, y):
        point = wintypes.POINT(label.winfo_rootx() + x, label.winfo_rooty() + y)
        return self.user32.WindowFromPoint(point) == label.winfo_id()

    def test_original_gap_passes_through_but_fixed_gap_catches_click(self):
        old, label = self.show_button(False)
        pixels = self.source.resize((30, 30), Image.Resampling.LANCZOS)
        # Interior gap between the second and third bars, rather than exterior padding.
        gap = next((x, y) for y in range(15, 25) for x in range(15, 25)
                   if pixels.getpixel((x, y))[3] == 0)
        inset = (label.winfo_width() - 30) // 2
        self.assertFalse(self.native_hit(label, gap[0] + inset, gap[1] + inset))
        old.destroy()
        _, label = self.show_button(True)
        self.assertTrue(self.native_hit(label, *gap))
        label.event_generate('<Button-1>', x=gap[0], y=gap[1])
        self.root.update()
        self.assertEqual(self.clicks, [gap])

    def test_entire_click_rectangle_survives_pet_resizing_and_reshow(self):
        win, label = self.show_button(True)
        self.app.gear_label = self.app.chatbtn_label = self.app.pomobtn_label = None
        self.app.todobtn_label = label
        self.app._pm_todo = object()
        for size in (20, 30, 59, 30):
            with self.subTest(size=size):
                self.app.pet = SimpleNamespace(winfo_height=lambda: 280 * (size + .1) / 30)
                self.app._resize_buttons()
                win.withdraw()
                win.deiconify()
                win.lift()
                self.root.update()
                self.assertEqual((label.winfo_width(), label.winfo_height()), (size, size))
                for y in range(size):
                    for x in range(size):
                        self.assertTrue(self.native_hit(label, x, y), (size, x, y))
                label.event_generate('<Button-1>', x=size // 2, y=size // 2)
                self.root.update()
        self.assertEqual(len(self.clicks), 4)


if __name__ == '__main__':
    unittest.main()
