import sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from memory_lifecycle import edit_content,undo_edit
from todo_quick import snooze_time
from todo_reply import TodoReplyMixin,completion_ack
from copy import deepcopy

class MemoryEditTests(unittest.TestCase):
    def test_multiline_source_and_undo(self):
        before=[dict(id='a',content='旧内容',source_quote='原话',created=1)]
        after=deepcopy(before)
        self.assertTrue(edit_content(after[0],'新内容\n第二行','旧内容',10))
        self.assertEqual(after[0]['original_source_quote'],'原话')
        self.assertEqual(after[0]['source_quote'],'新内容\n第二行')
        restored,conflicts=undo_edit(after,before,after)
        self.assertEqual(restored,before);self.assertEqual(conflicts,0)
    def test_blank_and_conflicting_edit_do_not_mutate(self):
        row=dict(id='a',content='新版本')
        for text,expected in [(' ','新版本'),('改写','旧版本')]:
            with self.assertRaises(ValueError):edit_content(row,text,expected)
        self.assertEqual(row,dict(id='a',content='新版本'))

class FollowupTests(unittest.TestCase):
    def test_delay_phrases(self):
        for phrase in ('再晚半小时','晚半小时','推迟30分钟','延后半小时','半小时后再提醒我'):
            self.assertEqual(snooze_time(phrase,1000),2800,phrase)
        for phrase in ('半小时','我半小时后出去','不想晚半小时','晚半小时吗'):
            self.assertIsNone(snooze_time(phrase,1000),phrase)
    def test_ack(self):
        for phrase in ('搞定了','我做完了','弄好了','已经做好了'):
            self.assertTrue(completion_ack(phrase),phrase)
        for phrase in ('还没做完了','做完了吗','我准备做好了','报告做好了'):
            self.assertFalse(completion_ack(phrase),phrase)
    def test_unrelated_chat_keeps_recent_target_and_stale_signature_rejected(self):
        class App(TodoReplyMixin):
            todos=[dict(id='a',text='喝水',done=False)]
            def _todo_notice_signature(self,row):return 'new'
        app=App();app._todo_reply_targets={'desktop':dict(at=time.monotonic(),items=[dict(id='a',title='喝水',signature='old')])}
        self.assertIsNone(app._todo_complete_reply('聊点别的'))
        self.assertIn('desktop',app._todo_reply_targets)
        self.assertIsNone(app._todo_done_recent())
        self.assertIn('时间已经变了',app._todo_complete_reply('搞定了'))

if __name__=='__main__':unittest.main()
