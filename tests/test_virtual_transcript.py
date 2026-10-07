"""Long history behaviour, bounded canvas work and row-height corrections."""
import random,time,tkinter as tk,unittest
from art_transcript import ArtTranscript
from virtual_transcript import RowHeights

class RowHeightTests(unittest.TestCase):
    def test_prefix_and_pixel_lookup_after_many_height_corrections(self):
        rng=random.Random(7);values=[rng.randrange(80,800) for _ in range(5000)];index=RowHeights(values)
        for _ in range(100):
            row=rng.randrange(len(values));values[row]=rng.randrange(80,1200);index.set(row,values[row])
            count=rng.randrange(len(values));self.assertEqual(index.prefix(count),sum(values[:count]))
            self.assertEqual(index.index_at(sum(values[:count])+values[count]-1),count)
        self.assertEqual(index.index_at(0),0);self.assertEqual(index.index_at(sum(values)),4999)

class VirtualTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('700x430');self.errors=[]
        self.root.report_callback_exception=lambda *exc:self.errors.append(str(exc[1]))
        self.view=ArtTranscript(self.root);self.view.pack(fill='both',expand=True);self.root.update()
        self.rows=[dict(id=str(index),created=0,role='assistant',text=f'消息 {index} 中文 English\n'+('正文 '*((index%8)+1))) for index in range(5000)]
        self.view.set_rows(self.rows);self.root.update()
    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])
    def bounded(self):self.assertLess(len(self.view.find_all()),160)
    def test_scroll_recycles_items_and_preserves_full_text(self):
        self.bounded();self.assertIn('消息 4999',self.view.get())
        for fraction in (0,.1,.9,.4,1):
            self.view.yview_moveto(fraction);self.root.update();self.bounded()
            top=self.view.canvasy(0);end=top+self.view.winfo_height()
            self.assertTrue(any(a<end and b>top for a,b,row in self.view.hit_rows))
        self.assertIn('4999',[row['id'] for a,b,row in self.view.hit_rows])
    def test_focus_row_selection_and_context_use_actual_message(self):
        self.view.focus_row('2437');self.root.update();self.bounded()
        top,bottom,row=next((a,b,row) for a,b,row in self.view.hit_rows if row['id']=='2437')
        self.assertLess(top,self.view.canvasy(0)+self.view.winfo_height())
        item=next(item for item,text in self.view.texts.items() if text==row['text'])
        self.view.select_from(item,0);self.view.select_to(item,6)
        self.assertEqual(self.view.get('sel.first','sel.last'),row['text'][:7])
        received=[];self.view.on_context=received.append
        from types import SimpleNamespace
        self.view.open_row(SimpleNamespace(y=top-self.view.canvasy(0)+35))
        self.assertEqual(received,[row])
    def test_width_reflow_keeps_anchor_and_small_history_replaces_pool(self):
        self.view.focus_row('2000');self.root.update()
        self.root.geometry('450x430')
        end=time.monotonic()+.3
        while time.monotonic()<end:self.root.update();time.sleep(.002)
        self.bounded();self.assertIn('2000',[row['id'] for a,b,row in self.view.hit_rows])
        self.view.set_rows(self.rows[:2]);self.root.update()
        self.assertIsNone(self.view._virtual);self.assertLess(len(self.view.find_all()),15)
        self.assertNotIn('消息 2000',self.view.get())
