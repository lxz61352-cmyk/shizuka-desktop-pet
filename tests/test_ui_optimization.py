"""Offline checks for long transcript reflow and incremental task output."""
from pathlib import Path
import sys
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from display_dpi import DISPLAY_DPI
from art_transcript import ArtTranscript
from text_output import adaptive_label,update_output
from ui_theme import install
from computer_agent import load_config,save_config
import tempfile


class UIOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();install(self.root);self.root.geometry('760x400+80+80')
        self.errors=[];self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))

    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])

    def pump(self,seconds=.2):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.root.update();time.sleep(.002)

    def output(self):
        box=tk.Text(self.root,wrap='word',state='disabled');box.pack(fill='both',expand=True)
        self.pump(.04);return box

    def test_append_preserves_selection_and_view_while_reading_old_output(self):
        box=self.output();old=''.join(f'第 {n} 行中文输出\n' for n in range(200))
        update_output(box,'',old);box.yview('20.0');box.tag_add('sel','20.0','20.5');self.root.update_idletasks()
        top=box.index('@0,0');selection=box.get('sel.first','sel.last')
        with patch.object(box,'delete',wraps=box.delete) as delete:
            update_output(box,old,old+'新增输出\n');delete.assert_not_called()
        self.assertEqual(box.index('@0,0'),top)
        self.assertEqual(box.get('sel.first','sel.last'),selection)
        self.assertEqual(box.cget('state'),'disabled')
        self.assertLess(box.yview()[1],.5)

    def test_append_follows_bottom_and_replacement_handles_emoji(self):
        box=self.output();old='😀已处理\n'+('输出\n'*120)
        update_output(box,'',old);self.root.update_idletasks();box.see('end')
        update_output(box,old,old+'尾行');self.root.update_idletasks()
        self.assertGreater(box.yview()[1],.999)
        changed='😀已处理\n新任务'
        update_output(box,old+'尾行',changed)
        self.assertEqual(box.get('1.0','end-1c'),changed)

    def test_labels_follow_available_width(self):
        label=adaptive_label(self.root,text='长说明文字'*80,padx=12);label.pack(fill='x')
        self.pump(.08);wide=int(label.cget('wraplength'))
        self.root.geometry('540x400');self.pump(.08)
        self.assertLess(int(label.cget('wraplength')),wide)
        self.assertEqual(int(label.cget('wraplength')),label.winfo_width()-24-2*int(label.cget('borderwidth')))

    def test_transcript_reuses_items_and_copies_all_rows_after_reflow(self):
        view=ArtTranscript(self.root);view.pack(fill='both',expand=True);self.root.update_idletasks()
        rows=[dict(id=str(n),role='assistant',text='合成对话内容。'*10,created=0) for n in range(180)]
        view.set_rows(rows);self.pump(.6);view.render()
        self.assertGreater(len(view.find_withtag('message')),0)
        self.assertLess(len(view.find_withtag('message')),40)
        view.select_all();self.assertIn(rows[-1]['text'],view.get('sel.first'))
        self.root.geometry('540x400');self.pump(1)
        self.assertIsNone(view._layout_job);self.assertLess(len(view.hit_rows),40)
        self.assertEqual(len(view.rows),len(rows))
        self.assertTrue(view.all_selected)
        view.set_rows(rows[:3]);self.assertEqual(len(view.find_withtag('message')),3)
        self.assertFalse(view.all_selected)

    def test_large_initial_layout_bounds_widgets_and_focuses_requested_row(self):
        view=ArtTranscript(self.root);view.pack(fill='both',expand=True);self.pump(.04)
        rows=[dict(id=str(n),role='assistant',text='合成较长对话。'*40,created=0) for n in range(180)]
        view.set_rows(rows);view.focus_row('20')
        self.pump(.02)
        self.assertIsNone(view._layout_job)
        self.assertLess(view.yview()[0],.2)
        self.assertLess(len(view.hit_rows),40)
        self.assertIn('20',[row['id'] for _,_,row in view.hit_rows])
        self.assertEqual(len(view.rows),180)

    def test_transcript_coalesces_configure_events_and_cancels_on_destroy(self):
        view=ArtTranscript(self.root);view.pack(fill='both',expand=True);self.root.update_idletasks()
        with patch.object(view,'render',wraps=view.render) as render:
            for width in (600,610,620,630):view._resized(SimpleNamespace(width=width))
            self.assertEqual(render.call_count,0);self.pump(.15)
            self.assertEqual(render.call_count,1)
        view._resized(SimpleNamespace(width=700));view.destroy();self.pump(.12)

    def test_opacity_setting_survives_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=load_config(root/'data')
            config.update(workspace=str(root/'workspace'),text_opacity=.85)
            save_config(root/'data',config)
            self.assertEqual(load_config(root/'data')['text_opacity'],.85)
            config['text_opacity']=float('nan')
            with self.assertRaises(ValueError):save_config(root/'data',config)


if __name__=='__main__':unittest.main()
