from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys,threading,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from todo_model import command,fallback_items
from todo_features import reminder_expired

class NaturalReminderTests(unittest.TestCase):
    def test_request_has_real_local_schedule(self):
        text='提醒我20分钟后开始看书'
        now=datetime(2026,10,7,13,33,41)
        specs=fallback_items(command(text),now)
        self.assertEqual(specs[0]['text'],'开始看书')
        self.assertEqual(specs[0]['due'],now.timestamp()+1200)
    def test_actual_time_first_request(self):
        text='1分钟之后提醒我来看看你有没有提醒我'
        now=datetime(2026,10,7,14,0)
        self.assertEqual(command(text),text)
        spec=fallback_items(command(text),now)[0]
        self.assertEqual(spec['due'],now.timestamp()+60)
        self.assertEqual(spec['text'],'来看看你有没有提醒我')
    def test_time_first_request_does_not_merge_with_chat(self):
        import queue
        from weixin_channel import WeixinChannel
        row=dict(key='a',context='ctx',text='1分钟之后提醒我看书')
        jobs=queue.Queue();jobs.put(dict(key='b',context='ctx',text='顺便聊点别的'))
        app=SimpleNamespace(store=SimpleNamespace(data={}),jobs=jobs,
                            stopped=threading.Event())
        result=WeixinChannel._collect_burst(app,row,threading.Event())
        self.assertEqual(result['text'],row['text']);self.assertEqual(jobs.qsize(),1)
    def test_common_connectors_and_word_order(self):
        now=datetime(2026,10,7,14,0)
        for text in ('一分钟后再来提醒我看书','一分钟后再提醒我看书',
                     '一分钟之后来提醒我看书','请你在一分钟后提醒我看书',
                     '你一分钟以后叫我看书','过一分钟提醒我看书',
                     '再过一分钟再来提醒我看书','提醒我过一分钟看书',
                     '一分钟后提醒我一下看书','一分钟后，提醒我看书',
                     '等一分钟再提醒我看书','你一分钟后，提醒我看书'):
            with self.subTest(text=text):
                self.assertEqual(command(text),text)
                row=fallback_items(text,now)[0]
                self.assertEqual(row['due'],now.timestamp()+60)
                self.assertEqual(row['text'],'看书')
    def test_saved_reminder_reaches_scheduler_and_send(self):
        import json,tempfile
        import pet
        from todo_features import TodoFeaturesMixin
        from weixin_ui import WeixinMixin
        from unittest.mock import patch
        now=datetime(2026,10,7,14,0)
        text='一分钟后再来提醒我看你有没有提醒我'
        class App(TodoFeaturesMixin):
            add_todo=pet.DeskPet.add_todo
            _save_todos=pet.DeskPet._save_todos
            def _todo_init(self):pass
            def _ui(self,callback):
                callback()
                if any(v.get('notice',{}).get('weixin')=='sent' for v in self._todo_details.values()):
                    self.finished.set()
        with tempfile.TemporaryDirectory() as folder:
            app=App();app.todos=[];app._todo_details={};app._todo_sending=set()
            app._todo_details_path=Path(folder)/'todo-details.json'
            app.finished=threading.Event()
            for name in ('_refresh_todo_view','_todo_queue_routine','_todo_start_memory_review',
                         '_todo_prepare_phrase','_record_notice','_log_chat','_fire_reminder'):
                setattr(app,name,Mock())
            for name in ('_weixin_quick_todo','_weixin_complete_reply','_weixin_todo_done'):
                setattr(app,name,Mock(return_value=None))
            channel=Mock();channel.reminder_ready.return_value=True;app._weixin_channel=channel
            core=Path(folder)/'todos.json'
            with patch.object(pet,'TODO_FILE',str(core)),patch.object(pet,'_sync_runtime',return_value=None),patch('todo_features.datetime') as clock:
                clock.now.return_value=now
                WeixinMixin._weixin_reply(app,text,threading.Event(),Mock())
                saved=json.loads(core.read_text('utf-8'))['items'][0]
                self.assertEqual(saved['due'],now.timestamp()+60)
                app._todo_check_reminders(now=now.timestamp()+59)
                channel.notify_owner.assert_not_called()
                with patch('todo_features.time.time',return_value=now.timestamp()+61):
                    app._todo_check_reminders(now=now.timestamp()+61)
                    self.assertTrue(app.finished.wait(3),'Reminder never reached confirmed-send state')
                    app._todo_check_reminders(now=now.timestamp()+62)
                channel.notify_owner.assert_called_once()
                app._fire_reminder.assert_called_once()
                details=json.loads(app._todo_details_path.read_text('utf-8'))['items']
                self.assertEqual(details[saved['id']]['notice']['weixin'],'sent')
    def test_only_explicit_request(self):
        for text in ('请提醒我20分钟后开始看书','麻烦你提醒我明天9点看书'):
            self.assertEqual(command(text),text)
        for text in ('我20分钟后看书','她说提醒我20分钟后看书','不要提醒我看书','提醒我是什么意思'):
            self.assertIsNone(command(text),text)
    def test_weixin_request_does_not_reach_chat_model(self):
        from weixin_ui import WeixinMixin
        app=SimpleNamespace(_weixin_quick_todo=Mock(return_value=None),
            _weixin_complete_reply=Mock(return_value=None),_weixin_todo_done=Mock(return_value=None),
            _log_chat=Mock(),_weixin_todo_command=Mock(return_value='已保存提醒'))
        text='提醒我20分钟后开始看书';cancel=threading.Event()
        self.assertEqual(WeixinMixin._weixin_reply(app,text,cancel,Mock()),'已保存提醒')
        app._weixin_todo_command.assert_called_once_with(text,cancel)
    def test_due_event_still_sends_during_grace(self):
        row=dict(id='a',text='开会',due=1000)
        options=dict(source_text='1000点开会',schedule=dict(event_at=1000))
        self.assertFalse(reminder_expired(row,options,1001))
        self.assertFalse(reminder_expired(row,options,1600))
        self.assertTrue(reminder_expired(row,options,1601))
        row['due']=900
        self.assertTrue(reminder_expired(row,options,1600))

if __name__=='__main__':unittest.main()
