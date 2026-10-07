"""Native editor interaction and source proportions during unfinished resizes."""
from concurrent.futures import Future
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest.mock import patch
import unittest
from PIL import Image, ImageDraw, ImageOps, ImageTk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import window_art
from ui_theme import install
from art_transcript import ArtTranscript
from display_dpi import DISPLAY_DPI


class GlassSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();install(self.root)
        self.errors=[]
        self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))

    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])

    def pump(self,seconds=.6):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.root.update();time.sleep(.002)

    def test_native_translucent_editor_keeps_content_selection_and_mouse_target(self):
        win=tk.Toplevel(self.root);win.geometry('600x400+120+100');win.attributes('-topmost',True)
        entry=tk.Text(win,wrap='word');entry._glass_text_opacity=.70
        entry.pack(fill='both',expand=True,padx=20,pady=20)
        entry.insert('1.0','中文任务\nEnglish and a second line')
        self.pump()
        self.assertEqual(entry._glass_text_handle,entry.winfo_id())
        user32=ctypes.WinDLL('user32')
        user32.GetLayeredWindowAttributes.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.COLORREF),ctypes.POINTER(ctypes.c_ubyte),ctypes.POINTER(wintypes.DWORD))
        key=wintypes.COLORREF();alpha=ctypes.c_ubyte();flags=wintypes.DWORD()
        self.assertTrue(user32.GetLayeredWindowAttributes(entry.winfo_id(),ctypes.byref(key),ctypes.byref(alpha),ctypes.byref(flags)))
        self.assertEqual(alpha.value,round(.70*255));self.assertEqual(flags.value,2)
        user32.WindowFromPoint.argtypes=(wintypes.POINT,);user32.WindowFromPoint.restype=wintypes.HWND
        point=wintypes.POINT(entry.winfo_rootx()+50,entry.winfo_rooty()+100)
        hit=user32.WindowFromPoint(point)
        user32.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
        process=wintypes.DWORD();user32.GetWindowThreadProcessId(hit,ctypes.byref(process))
        # A locked desktop hit-tests the lock screen, not this test window.
        available=process.value==__import__('os').getpid()
        if available:self.assertEqual(hit,entry.winfo_id())
        if available:
            # Check Tk's editor binding separately from native hit testing.
            # Synthetic Windows mouse messages are not reliable Tk input and
            # moving the user's mouse races foreground activation.
            win.focus_force();self.pump(.08)
            entry.event_generate('<Button-1>',x=50,y=100)
            entry.event_generate('<ButtonRelease-1>',x=50,y=100)
            self.pump(.05)
        self.pump(.05)
        if available:self.assertIs(entry.focus_get(),entry)
        entry.tag_add('sel','1.0','1.4');self.assertEqual(entry.get('sel.first','sel.last'),'中文任务')
        entry.insert('end','\n追加');entry.configure(state='disabled')
        self.assertIn('追加',entry.get('1.0','end-1c'))
        entry.insert('end','不能插入');self.assertNotIn('不能插入',entry.get('1.0','end-1c'))

    def test_resize_has_correct_original_crop_before_worker_finishes(self):
        source=Image.new('RGB',(800,800),'#183040')
        ImageDraw.Draw(source).ellipse((320,320,480,480),fill='white')
        settings={'blur':0,'darkness':0}
        with patch.dict(window_art.PREFERENCES,settings),patch.object(window_art,'artwork',return_value=source):
            win=tk.Toplevel(self.root);win.geometry('600x400+120+100')
            win.update_idletasks()
            window_art.attach(win);art=win._art_backdrop;art.card={'file':'glass-test-shape'}
            self.pump()
            self.assertEqual(art.image.size,(600,400))
            unfinished=Future()
            with patch.object(window_art._WORKER,'submit',return_value=unfinished):
                win.geometry('900x360+120+100');self.pump(.08)
                self.assertFalse(unfinished.done())
                self.assertEqual(art.image.size,(900,360))
                expected=ImageOps.fit(source,(900,360),centering=(.5,.5))
                self.assertEqual(art.image.tobytes(),expected.tobytes())
                self.assertEqual((art.photo.width(),art.photo.height()),(900,360))
                unfinished.set_result(window_art._prepare(art.request));self.pump(.08)
                self.assertEqual(art.image.tobytes(),expected.tobytes())
                with patch.object(window_art._WORKER,'submit',return_value=Future()):
                    win.geometry('600x400+120+100');self.pump(.04)
                    self.assertEqual(art.image.size,(600,400))
                    win.geometry('900x360+120+100');self.pump(.04)
                    self.assertEqual(art.image.tobytes(),expected.tobytes(),'Returning to a cached size must discard the intermediate crop')

    def test_transcript_intermediate_resize_keeps_round_shapes_round(self):
        self.root.geometry('700x200+120+100');self.root.deiconify()
        view=ArtTranscript(self.root,plain=True);view.pack(fill='both',expand=True)
        self.pump(.05)
        source=Image.new('RGB',(400,400),'black')
        ImageDraw.Draw(source).ellipse((180,180,220,220),fill='white')
        view.set_backdrop(source)
        pixels=ImageTk.getimage(view.photos[0]).convert('L').point(lambda n:255 if n>127 else 0)
        left,top,right,bottom=pixels.getbbox()
        self.assertLessEqual(abs((right-left)-(bottom-top)),1,'The intermediate crop must not squash the circle')


if __name__=='__main__':unittest.main()
