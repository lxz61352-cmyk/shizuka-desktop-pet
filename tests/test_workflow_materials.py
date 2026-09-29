"""State transitions and attachment routing, with synthetic local data only."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys,tempfile,time,threading,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from workflow_store import WorkflowStore,surrounding
from attachment_files import AttachmentShelf,load_material,page_numbers,pdf_count,pdf_page,message_content,image_attachment
from todo_quick import snooze_time
from PIL import Image


class WorkflowTests(unittest.TestCase):
    def test_resume_keeps_remaining_and_does_not_count_offline_time(self):
        with tempfile.TemporaryDirectory() as folder:
            store=WorkflowStore(folder);store.begin('focus',1500,{'id':'t1','text':'fixture'})
            store.checkpoint(1200)
            with patch('workflow_store.time.time',return_value=time.time()+86400):
                reopened=WorkflowStore(folder)
                self.assertEqual(reopened.data['focus']['remaining'],1200)
                reopened.checkpoint(1100);reopened.finish('主动结束')
            self.assertEqual(reopened.total('t1'),400)
            self.assertIsNone(reopened.finish('再次结束'))
            self.assertEqual(len(WorkflowStore(folder).data['sessions']),1)
            reopened.begin('break',300,{'id':'t1'});reopened.checkpoint(0);reopened.finish('结束')
            self.assertEqual(reopened.total('t1'),400)

    def test_notification_read_and_dedup_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            s=WorkflowStore(folder);s.notice('due','待办',key='one',todo_id='t1')
            ident=s.notices()[0]['id'];s.read([ident]);s.notice('due again','待办',key='one')
            rows=WorkflowStore(folder).notices()
            self.assertEqual(len(rows),1);self.assertTrue(rows[0]['read']);self.assertEqual(rows[0]['todo_id'],'t1')

    def test_context_restores_nonmatching_neighbors_without_other_channels(self):
        rows=[]
        for i in range(30):
            rows += [dict(id=f'd{i}',role='user',kind='user',text='match' if i==15 else 'neighbor'),
                     dict(id=f'w{i}',role='assistant',kind='weixin',text='other')]
        rows.insert(15,dict(id='summary',role='assistant',kind='memory_summary',text='summary'))
        found,older,newer=surrounding(rows,'d15',2,2)
        self.assertEqual([r['id'] for r in found],['d13','d14','d15','d16','d17'])
        self.assertTrue(older and newer)
        self.assertEqual(surrounding(rows,'deleted'),([],False,False))


class TodoQuickTests(unittest.TestCase):
    def setUp(self):
        import pet
        self.app=pet.DeskPet.__new__(pet.DeskPet)
        self.app.todos=[dict(id='t1',text='fixture',due=time.time()-3600,on_boot=False,done=False)]
        self.app._todo_details={'t1':{'desktop':True,'weixin':False,'schedule':{}}}
        self.app._todo_sending=set();self.app._pending_reminders=[]
        for name in ('_save_todo_details','_refresh_todo_view','_save_todos','_todo_start_memory_review','_todo_queue_routine'):
            setattr(self.app,name,Mock())

    def test_snooze_changes_only_effective_due_and_rejects_stale_action(self):
        row=self.app.todos[0];prior=deepcopy(row);signature=self.app._todo_notice_signature(row)
        at=time.time()+600;self.app._todo_snooze('t1',at,signature)
        self.assertEqual(row,prior);self.assertEqual(self.app._todo_effective_due(row),at)
        self.assertIn('已变化',self.app._todo_snooze('t1',at+600,signature))
        self.app._todo_complete_or_restore(row,True)
        self.assertNotIn('snooze_until',self.app._todo_details['t1'])
        self.assertFalse(self.app._todo_notice_current('t1',at))

    def test_crossed_recurrence_waits_for_snoozed_reminder_then_advances(self):
        row=self.app.todos[0];options=self.app._todo_details['t1']
        options['schedule']={'rule':{'frequency':'daily'},'reminder_at':row['due']}
        at=time.time()+600;self.app._todo_snooze('t1',at)
        with patch('todo_recurrence.latest_due_schedule',return_value=({},at-100)) as latest,patch.object(self.app,'_todo_transition') as transition:
            self.app._todo_prepare_occurrence(row,at+1);latest.assert_not_called()
            options['notice']={'signature':self.app._todo_notice_signature(row),'desktop':True}
            self.app._todo_prepare_occurrence(row,at+2);transition.assert_called_once()

    def test_ambiguous_chat_choice_is_channel_and_signature_bound(self):
        self.app.todos.append(dict(id='t2',text='other',due=None,done=False))
        self.assertIn('哪一条',self.app._todo_quick_from_chat('/稍后 10分钟','weixin'))
        self.assertIsNone(self.app._todo_quick_from_chat('1','desktop'))
        self.app.todos[1]['due']=time.time()+3600
        self.assertIn('已变化',self.app._todo_quick_from_chat('2','weixin'))
        self.assertNotIn('snooze_until',self.app._todo_options(self.app.todos[1]))

    def test_canceled_wechat_request_does_not_mutate(self):
        self.app._ui=lambda fn:fn();cancel=threading.Event();cancel.set()
        self.assertIsNone(self.app._weixin_quick_todo('/稍后',cancel))
        self.assertNotIn('snooze_until',self.app._todo_details['t1'])

    def test_parser_requires_explicit_reminder_intent(self):
        now=datetime(2026,9,29,12).timestamp()
        for phrase in ('稍后提醒','晚点再提醒我','10分钟后再提醒我','/稍后 10分钟'):
            self.assertEqual(snooze_time(phrase,now),now+600)
        for phrase in ('10分钟','10分钟后','她说晚点再提醒我','我想晚点再说','晚上吃什么'):
            self.assertIsNone(snooze_time(phrase,now))
        self.assertEqual(snooze_time('/稍后 今晚',now),now+8*3600)
        with self.assertRaises(ValueError):snooze_time('/稍后 今晚',now+9*3600)


class MaterialTests(unittest.TestCase):
    def test_pdf_pages_are_bounded_and_render_scanned_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.pdf'
            first=Image.new('RGB',(160,220),'red');second=Image.new('RGB',(160,220),'blue')
            first.save(path,save_all=True,append_images=[second])
            self.assertEqual(pdf_count(path),2)
            self.assertEqual(page_numbers('2,1-2',2),[2,1])
            for selection in ('0','1-3','2-1','bad'):
                with self.assertRaises(ValueError):page_numbers(selection,2)
            with self.assertRaises(ValueError):page_numbers('1,2',2,1)
            att=pdf_page(path,2)
            self.assertIn('第2页',att['name']);self.assertIn('扫描页',att['note'])
            self.assertGreater(att['image'].getpixel((50,50))[2],200)
            blocks=message_content('讲题',[att])
            self.assertEqual(sum(b['type']=='image_url' for b in blocks),1)

    def test_reused_pdf_keeps_page_text_and_name(self):
        with tempfile.TemporaryDirectory() as folder:
            att=image_attachment(Image.new('RGB',(100,100),'white'),'fixture.pdf · 第2页')
            att.update(text='Synthetic extracted text',note='PDF第2页 · 页面图像＋可提取文字')
            shelf=AttachmentShelf(folder);shelf.remember([att,att]);self.assertEqual(len(shelf.rows()),1)
            reused=shelf.get(shelf.rows()[0]);blocks=message_content('总结',[reused])
            self.assertEqual(reused['text'],att['text']);self.assertEqual(reused['note'],att['note'])
            self.assertTrue(any(b.get('text')==att['text'] for b in blocks))
            self.assertTrue(any(b['type']=='image_url' for b in blocks))

    def test_text_truncation_and_unsupported_formats_are_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'long.txt';path.write_text('a'*13000,'utf-8')
            material=load_material(path);self.assertTrue(material['truncated']);self.assertEqual(len(material['text']),12000)
            binary=Path(folder)/'binary.txt';binary.write_bytes(b'a\x00b')
            with self.assertRaises(ValueError):load_material(binary)
            docx=Path(folder)/'x.docx';docx.write_bytes(b'PK')
            with self.assertRaises(ValueError):load_material(docx)

    def test_cache_eviction_does_not_remove_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            shelf=AttachmentShelf(folder);keep=shelf.root/'unrelated.jpg';keep.write_bytes(b'keep')
            shelf.remember([image_attachment(Image.new('RGB',(8,8)),str(i)) for i in range(32)])
            self.assertEqual(len(shelf.rows()),30);self.assertEqual(len(list(shelf.root.glob('*.jpg'))),31)
            self.assertTrue(keep.exists())
            shelf.forget({shelf.rows()[0]['id']})
            self.assertEqual(len(shelf.rows()),29);self.assertTrue(keep.exists())


if __name__=='__main__':unittest.main()
