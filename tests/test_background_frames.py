"""Real Tk frame commits, resize geometry and native redraw recovery."""
from concurrent.futures import Future
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageTk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import window_art
from window_opening import dialog_window
from ui_theme import install,page_header
from backdrop_frame import frame_update,fit_image
from art_table import ArtTable
from glass_button import GlassButton,button_bitmap


class BackgroundFramesTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();install(self.root)
        self.errors=[]
        self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))

    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])

    def pump(self,seconds=.1):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.root.update();time.sleep(.002)

    def settled(self,win):
        deadline=time.monotonic()+5
        while getattr(win,'_opening_pending',True) and time.monotonic()<deadline:self.pump(.01)
        self.assertEqual(win._opening_result,'ready')
        self.assertTrue(win._art_backdrop.ready())

    def window(self,size='620x430'):
        win=dialog_window(self.root);win.geometry(size+'+70+70')
        page_header(win,'统一背景').pack(fill='x')
        return win

    def test_small_dialog_uses_the_same_canvas_and_ready_frame(self):
        win=self.window('320x160');ttk.Label(win,text='小窗口同样铺满').pack()
        self.settled(win)
        self.assertIsInstance(win._art_backdrop.canvas,tk.Canvas)
        self.assertEqual(win._art_backdrop.image.size,(320,160))

    def test_slow_resize_worker_never_leaves_mixed_child_crops(self):
        win=self.window();body=ttk.Frame(win,padding=12);body.pack(fill='both',expand=True)
        entry=ttk.Entry(body);entry.pack(fill='x');entry.insert(0,'保留输入')
        button=GlassButton(body,'保留按钮',lambda:None);button.pack(fill='x')
        table=ArtTable(body,('one',));table.pack(fill='both',expand=True)
        table.heading('one','标题');table.insert('','end',iid='a',values=('内容',))
        self.settled(win);art=win._art_backdrop
        waiting=Future()
        with patch.object(window_art._WORKER,'submit',return_value=waiting):
            for size in ('850x340','510x580','780x420'):
                win.geometry(size+'+70+70');self.pump(.025)
                self.assertEqual(art.image.size,(win.winfo_width(),win.winfo_height()))
                for widget in (body,entry,button,table):
                    self.assertIs(widget._backdrop_source,art.image)
                    self.assertEqual(widget._backdrop_bounds,(widget.winfo_rootx()-win.winfo_rootx(),
                        widget.winfo_rooty()-win.winfo_rooty(),widget.winfo_rootx()-win.winfo_rootx()+widget.winfo_width(),
                        widget.winfo_rooty()-win.winfo_rooty()+widget.winfo_height()))
                self.assertIsNone(button.pending)
                expected=button_bitmap(art.crop(button),button.primary,button.hover,
                    button.focus_get() is button,dark=True)
                self.assertEqual(ImageTk.getimage(button._photo).convert('RGB').tobytes(),expected.tobytes())
                self.assertEqual(entry.get(),'保留输入')
        waiting.cancel()

    def test_table_uses_transcript_proportions_and_reuses_one_image_item(self):
        win=self.window('700x240');table=ArtTable(win,('one',));table.pack(fill='both',expand=True)
        self.settled(win)
        source=Image.new('RGB',(400,400),'black')
        ImageDraw.Draw(source).ellipse((170,170,230,230),fill='white')
        table.set_backdrop(source)
        pixels=ImageTk.getimage(table.photo).convert('L').point(lambda n:255 if n>127 else 0)
        a,b,c,d=pixels.getbbox();self.assertLessEqual(abs(c-a-(d-b)),1)
        item=table.find_withtag('art');photo=table.photo
        for n in range(4):table.paint()
        self.assertEqual(table.find_withtag('art'),item);self.assertIs(table.photo,photo)

    def test_native_redraw_is_restored_on_error_without_showing_hidden_widgets(self):
        win=self.window();shown=ttk.Label(win,text='可见');shown.pack()
        hidden=ttk.Label(win,text='隐藏');self.settled(win)
        api=ctypes.WinDLL('user32');api.IsWindowVisible.argtypes=(wintypes.HWND,)
        api.IsWindowVisible.restype=wintypes.BOOL
        api.GetPropW.argtypes=(wintypes.HWND,wintypes.LPCWSTR);api.GetPropW.restype=wintypes.HANDLE
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with frame_update(win):
                self.assertTrue(api.IsWindowVisible(win.winfo_id()),'Frame commit hid the client surface')
                self.assertFalse(api.GetPropW(win.winfo_id(),'SysSetRedraw'))
                raise RuntimeError('synthetic paint failure')
        self.assertTrue(api.IsWindowVisible(win.winfo_id()))
        self.assertTrue(api.IsWindowVisible(shown.winfo_id()))
        self.assertFalse(api.IsWindowVisible(hidden.winfo_id()))
        self.assertFalse(api.GetPropW(win.winfo_id(),'SysSetRedraw'))
        win.withdraw()
        with frame_update(win):pass
        self.assertFalse(api.IsWindowVisible(win.winfo_id()))

    def test_maximize_surface_is_covered_before_idle_with_worker_pending(self):
        win=self.window();body=ttk.Frame(win);body.pack(fill='both',expand=True)
        entry=ttk.Entry(body);entry.pack(fill='x');entry.insert(0,'保留最大化前的文字')
        self.settled(win);art=win._art_backdrop;waiting=Future();samples=[]
        def configured(event):
            if event.widget is win:
                samples.append((art.image.size,(win.winfo_width(),win.winfo_height())))
        win.bind('<Configure>',configured,add='+')
        with patch.object(window_art._WORKER,'submit',return_value=waiting):
            for state in ('zoomed','normal','zoomed','normal'):
                win.state(state);self.pump(.04)
                self.assertEqual(art.image.size,(win.winfo_width(),win.winfo_height()))
                self.assertEqual(entry.get(),'保留最大化前的文字')
                self.assertTrue(win.winfo_ismapped())
        waiting.cancel()
        self.assertGreaterEqual(len(samples),4)
        self.assertTrue(all(image==client for image,client in samples),samples)

    def test_dialog_native_transition_policy_is_applied(self):
        win=self.window();self.settled(win)
        self.assertTrue(win._chrome_attributes[3])
        api=ctypes.WinDLL('user32');api.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
        api.GetAncestor.restype=wintypes.HWND
        self.assertEqual(win._chrome_handle,api.GetAncestor(win.winfo_id(),2))
        self.assertNotEqual(win._chrome_handle,api.GetAncestor(self.root.winfo_id(),2))

    def test_opening_fade_does_not_leave_the_opaque_wrapper_layered(self):
        win=self.window();editor=tk.Text(win,height=2);editor.pack(fill='x')
        editor.insert('1.0','透明输入仍可编辑')
        self.settled(win)
        api=ctypes.WinDLL('user32')
        api.GetWindowLongW.argtypes=(wintypes.HWND,ctypes.c_int);api.GetWindowLongW.restype=ctypes.c_long
        for state in ('zoomed','normal','zoomed','normal'):
            win.state(state);self.pump(.04)
            self.assertEqual(float(win.attributes('-alpha')),1)
            self.assertFalse(api.GetWindowLongW(win._chrome_handle,-20)&0x80000)
            self.assertTrue(api.GetWindowLongW(editor.winfo_id(),-20)&0x80000)
            self.assertEqual(editor.get('1.0','end-1c'),'透明输入仍可编辑')

    def test_frame_commit_drains_tk_display_work(self):
        win=self.window();self.settled(win);called=[]
        with frame_update(win):
            win.after_idle(lambda:called.append('display-ready'))
        self.assertEqual(called,['display-ready'])

    def test_real_window_transparency_is_preserved(self):
        from window_composition import restore_opaque
        win=self.window();self.settled(win)
        win.attributes('-alpha',.8);self.pump(.01)
        self.assertFalse(restore_opaque(win))
        self.assertAlmostEqual(float(win.attributes('-alpha')),.8)
        win.attributes('-alpha',1);win.attributes('-transparentcolor','#ff00ff');self.pump(.01)
        self.assertFalse(restore_opaque(win))
        self.assertEqual(str(win.attributes('-transparentcolor')),'#ff00ff')

    def test_background_commit_finishes_button_paints_synchronously(self):
        win=self.window();button=GlassButton(win,'按钮',lambda:None);button.pack()
        self.settled(win);button.queue();self.assertIsNotNone(button.pending)
        win._art_backdrop.present(win._art_backdrop.size,win._art_backdrop.layout_signature(),True)
        self.assertIsNone(button.pending);self.assertTrue(win._art_backdrop.ready())

    def test_native_text_fields_are_transparent_and_fonts_are_bold(self):
        win=self.window('700x620')
        widgets=[tk.Text(win,height=2),ScrolledText(win,height=2),tk.Entry(win),
                 tk.Listbox(win,height=2),ttk.Treeview(win,height=2)]
        for widget in widgets:widget.pack(fill='x')
        widgets[0].insert('1.0','原始内容');widgets[2].insert(0,'路径文字')
        self.settled(win)
        api=ctypes.WinDLL('user32')
        api.GetLayeredWindowAttributes.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.COLORREF),
            ctypes.POINTER(ctypes.c_ubyte),ctypes.POINTER(wintypes.DWORD))
        for widget in widgets:
            key,alpha,flags=wintypes.COLORREF(),ctypes.c_ubyte(),wintypes.DWORD()
            self.assertTrue(api.GetLayeredWindowAttributes(widget.winfo_id(),ctypes.byref(key),ctypes.byref(alpha),ctypes.byref(flags)))
            self.assertEqual(flags.value,1)  # Colour key only; alpha is ignored.
            if not isinstance(widget,ttk.Widget):self.assertEqual(tkfont.Font(root=widget,font=widget.cget('font')).actual()['weight'],'bold')
        self.assertEqual(widgets[0].get('1.0','end-1c'),'原始内容')
        self.assertEqual(widgets[2].get(),'路径文字')

    def test_clicks_and_drags_on_clear_text_background_reach_the_native_editor(self):
        win=self.window();editor=tk.Text(win,height=4);editor.pack(fill='x')
        editor.insert('1.0','透明编辑器仍可选择这段文字')
        self.settled(win);win.focus_force();self.pump(.02)
        target=win._art_backdrop.canvas
        x,y=editor.winfo_rootx()+16,editor.winfo_rooty()+15
        target.event_generate('<Button-1>',x=x-target.winfo_rootx(),y=y-target.winfo_rooty(),rootx=x,rooty=y)
        self.assertIs(editor.focus_get(),editor)
        self.assertEqual(editor.index('insert'),editor.index('@16,15'))
        target.event_generate('<B1-Motion>',state=256,x=x+90-target.winfo_rootx(),y=y-target.winfo_rooty(),rootx=x+90,rooty=y)
        target.event_generate('<ButtonRelease-1>',x=x+90-target.winfo_rootx(),y=y-target.winfo_rooty(),rootx=x+90,rooty=y)
        self.assertTrue(editor.tag_ranges('sel'))
        editor.tag_remove('sel','1.0','end');editor.mark_set('insert','end-1c')
        editor.event_generate('<KeyPress>',keysym='A');self.pump(.02)
        self.assertTrue(editor.get('1.0','end-1c').endswith('A'))

    def test_later_created_editors_get_the_same_transparency(self):
        win=self.window();self.settled(win)
        editor=tk.Entry(win);editor.pack(fill='x');self.pump(.15)
        self.assertEqual(editor._glass_text_parameters[2],1)
        self.assertEqual(tkfont.Font(root=editor,font=editor.cget('font')).actual()['weight'],'bold')


if __name__=='__main__':unittest.main()
