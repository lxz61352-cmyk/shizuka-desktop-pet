"""Artwork integrity and real Tk geometry/scrolling regression checks, offline."""
import hashlib
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import window_art
from ui_theme import apply,install
from art_transcript import ArtTranscript
from dialogue_bubble import make_bubble


class DesktopArtworkTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *error:self.errors.append(error)
        install(self.root)

    def pump(self):
        # Native theme layout and the debounced backdrop each need a GUI pass.
        until=time.monotonic()+.5
        while time.monotonic()<until:
            self.root.update();time.sleep(.01)

    def tearDown(self):
        self.root.destroy()
        self.assertEqual(self.errors,[])

    def test_all_catalogued_cards_are_present_and_intact(self):
        rows=window_art.catalog();self.assertEqual(len(rows),34)
        self.assertEqual(len({row['file'] for row in rows}),34)
        for row in rows:
            self.assertEqual(hashlib.sha256((window_art.ART_DIR/row['file']).read_bytes()).hexdigest(),row['sha256'])
            self.assertTrue(row['file_page'].startswith('https://world-dai-star.fandom.com/wiki/File:'))

    def test_resize_preserves_card_and_explicit_shuffle_changes_it(self):
        win=tk.Toplevel(self.root);win.geometry('620x430')
        frame=ttk.Frame(win);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='背景要铺满窗口').pack()
        self.pump();art=win._art_backdrop;first=art.card['file']
        win.geometry('780x510');self.pump()
        self.assertEqual(art.card['file'],first);self.assertEqual(art.image.size,(780,510))
        art.shuffle();self.pump();self.assertNotEqual(art.card['file'],first)

    def test_decoration_does_not_enter_application_child_lists(self):
        win=tk.Toplevel(self.root);win.geometry('600x400')
        frame=tk.Frame(win);frame.pack(fill='both',expand=True)
        label=tk.Label(frame,text='动态内容');label.pack()
        self.pump();self.assertEqual(frame.winfo_children(),[label])
        for child in frame.winfo_children():child.destroy()
        new=tk.Label(frame,text='刷新后');new.pack();self.pump()
        self.assertEqual(frame.winfo_children(),[new])

    def test_long_transcript_preserves_text_and_bounds_image_cache(self):
        win=tk.Toplevel(self.root);win.geometry('680x420')
        view=ArtTranscript(win);view.pack(fill='both',expand=True)
        rows=[dict(role='assistant' if i%2 else 'user',text=f'第{i}条：中文与 English。',created=0) for i in range(500)]
        view.set_rows(rows);self.pump()
        self.assertIn(rows[-1]['text'],view.get())
        self.assertLess(len(view.photos),15)
        view.yview('moveto',0);view.paint();self.assertLess(len(view.photos),15)
        self.assertEqual(len(view.rows),500)

    def test_canvas_selection_returns_only_selected_text(self):
        win=tk.Toplevel(self.root);win.geometry('600x400')
        view=ArtTranscript(win);view.pack(fill='both',expand=True)
        view.set_rows([dict(role='assistant',text='中文选择 English',created=0)]);self.pump()
        item=next(iter(view.texts));view.select_from(item,0);view.select_to(item,3)
        self.assertEqual(view.get('sel.first','sel.last'),'中文选择')

    def test_padded_container_and_search_use_the_same_exact_image(self):
        win=tk.Toplevel(self.root);win.geometry('620x430')
        frame=ttk.Frame(win,padding=(22,18,22,12));frame.pack(fill='x')
        frame._glass_panel='header'
        label=ttk.Label(frame,text='不盖住卡面的标题');label.pack(side='left')
        entry=ttk.Entry(frame);entry.pack(side='left',fill='x',expand=True)
        entry.insert(0,'保留编辑、选择和搜索')
        self.pump();art=win._art_backdrop
        self.assertNotEqual(art.image.getpixel((25,10)),art.base_image.getpixel((25,10)))
        for widget in (frame,label,entry):
            photo=widget._backdrop_photo
            self.assertEqual((photo.width(),photo.height()),(widget.winfo_width(),widget.winfo_height()))
            # Includes the outer padding that the old child-label method missed.
            points=((3,3),(photo.width()//2,photo.height()//2))
            expected=art.crop(widget)
            for x,y in points:self.assertEqual(photo.get(x,y),expected.getpixel((x,y)))
        self.assertEqual(entry.get(),'保留编辑、选择和搜索')
        first_style=frame.cget('style')
        win.geometry('790x500');self.pump();art.shuffle();self.pump()
        self.assertEqual(frame.cget('style'),first_style)
        self.assertEqual(frame._backdrop_photo.get(3,3),art.crop(frame).getpixel((3,3)))

    def test_generated_skins_keep_alpha_and_corner_scale(self):
        from desktop_surface import skin,skin_bitmap
        for kind in ('composer','reply'):
            original=skin(kind)
            self.assertEqual(original.mode,'RGBA')
            self.assertEqual(original.getpixel((0,0))[3],0)
            short=skin_bitmap(kind,440,250);long=skin_bitmap(kind,440,600)
            self.assertEqual(short.crop((0,0,88,90)).tobytes(),long.crop((0,0,88,90)).tobytes())
            self.assertEqual(short.crop((350,180,440,250)).tobytes(),long.crop((350,530,440,600)).tobytes())

    def test_native_controls_keep_size_commands_and_canvas_scroll_bounds(self):
        win=tk.Toplevel(self.root);win.geometry('620x430');clicked=[]
        button=tk.Button(win,text='刷新',command=lambda:clicked.append(True));button.pack()
        canvas=tk.Canvas(win);canvas.pack(fill='both',expand=True)
        content=canvas.create_rectangle(4,5,80,90);bounds=canvas.bbox('all')
        self.pump();size=(button.winfo_reqwidth(),button.winfo_reqheight())
        self.assertEqual(canvas.bbox('all'),bounds)
        win.geometry('720x470');self.pump();win._art_backdrop.shuffle();self.pump()
        self.assertEqual((button.winfo_reqwidth(),button.winfo_reqheight()),size)
        self.assertEqual(canvas.bbox('all'),canvas.bbox(content))
        canvas.configure(scrollregion=(0,0,600,1600));canvas.yview_moveto(.65);self.pump()
        self.assertEqual(canvas.coords('window-backdrop'),[canvas.canvasx(0),canvas.canvasy(0)])
        self.assertEqual(canvas.bbox('all'),bounds)
        button.invoke();self.assertEqual(clicked,[True])

    def test_bubble_long_reply_stays_bounded_without_discarding_tail(self):
        win,set_text=make_bubble(self.root);win.deiconify();set_text('短句。');self.pump()
        for child in win.winfo_children():
            if isinstance(child,tk.Canvas) and getattr(child,'_art_decoration',False):
                self.assertFalse(any(child.type(item)=='text' for item in child.find_withtag('decoration')))
        short=win.winfo_height();text='这是第几段？\n\n'*180+'最后一行仍可复制。'
        set_text(text);self.pump()
        self.assertEqual(win._text_box.get(),text)
        self.assertGreater(win.winfo_height(),short)
        self.assertLess(win.winfo_height(),self.root.winfo_screenheight()-40)
        self.assertIsNone(getattr(win,'_frame_win',None))
        win._text_box.yview('moveto',1);self.pump()
        self.assertGreater(win._text_box.yview()[1],.99)
        win.destroy();self.pump()


if __name__=='__main__':unittest.main()
