from pathlib import Path
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
os.environ.setdefault('SHIZUKA_DATA_DIR',tempfile.mkdtemp(prefix='context-tests-'))
import conversation_memory as cm
import dialogue_context as dc


def row(i,text,role='user',kind='weixin',at=None):
    return dict(id=str(i),text=text,role=role,kind=kind,created=at if at is not None else 1000000000+i)


class ContextTests(unittest.TestCase):
    def test_channel_and_session_selection_is_read_only(self):
        rows=[row(1,'旧问题',at=100),row(2,'旧口吻','assistant',at=101),
              row(3,'研究报告','assistant','proactive',at=5000),
              row(4,'电脑上的消息',kind='chat',at=5001),row(5,'晚饭吃面',at=5002)]
        before=copy.deepcopy(rows)
        self.assertEqual([r['id'] for r in dc.select_rows(rows,'晚饭吃面','weixin','5')],['5'])
        self.assertEqual(rows,before)

    def test_recent_correction_and_multiple_reply_parts_survive(self):
        rows=[row(1,'我只能周末去'),row(2,'那就周末。','assistant'),row(3,'提前约一下。','assistant'),row(4,'周六呢')]
        rows[1]['turn_id']=rows[2]['turn_id']='wxreply:a'
        selected=dc.select_rows(rows,'周六呢','weixin','4')
        self.assertEqual(len(cm.recent_messages(selected,current_user_id='4')),3)

    def test_explicit_reference_bridges_gap(self):
        rows=[row(1,'这题是积分换元',at=100),row(2,'先设u。','assistant',at=101),row(3,'继续刚才那题',at=10000)]
        self.assertEqual(len(dc.select_rows(rows,rows[-1]['text'],'weixin','3')),3)

    def test_desktop_direct_reference_keeps_one_proactive_message(self):
        rows=[row(1,'论文报告','assistant','proactive',at=100),row(2,'那篇论文说的什么',kind='chat',at=101)]
        self.assertEqual(len(dc.select_rows(rows,rows[-1]['text'],'desktop','2')),2)
        rows[-1]['text']='午饭吃面了'
        self.assertEqual(len(dc.select_rows(rows,rows[-1]['text'],'desktop','2')),1)

    def test_new_channel_does_not_inherit_desktop_reports(self):
        rows=[row(1,'论文报告','assistant','proactive'),row(2,'你好',kind='weixin')]
        self.assertEqual(len(dc.select_rows(rows,'你好','weixin','2')),1)

    def test_feedback_retains_quotes_not_assistant_style(self):
        rows=[row(1,'别老拿复习的事情套我了'),row(2,'我偏要催你。','assistant'),row(3,'今天吃饭了')]
        text=dc.feedback_context(rows,['3'])
        self.assertIn(rows[0]['text'],text)
        self.assertNotIn(rows[1]['text'],text)
        self.assertNotIn(rows[2]['text'],text)

    def test_relevance_can_return_no_records(self):
        self.assertEqual(dc.relevance('国庆去哪玩','用户不会链式求导'),0)
        self.assertEqual(dc.relevance('嗯嗯','用户正在准备考试'),0)
        self.assertGreater(dc.relevance('学校门口的牛肉店','用户喜欢学校门口的牛肉店'),0)
        self.assertGreater(dc.relevance('我在哪个城市','用户所在城市是青岛'),0)

    def test_old_summary_cannot_turn_joke_into_open_problem(self):
        rows=[row(1,'用户未说明曼波的具体意图','assistant','memory_summary'),row(2,'曼波曼波')]
        self.assertEqual(cm.recall(rows,'曼波曼波',0),[])

    def test_grounded_summary_rejects_fabrication_and_assistant(self):
        batch=[row(1,'我只能周末去'),row(2,'那你周六去。','assistant')]
        record=cm.grounded_summary_record(batch,{'notes':[
            {'source_id':'1','quote':'我只能周末去'},
            {'source_id':'1','quote':'用户需要被持续督促'},
            {'source_id':'2','quote':'那你周六去。'}]},1000000100)
        self.assertEqual(record['source_quotes'],[{'source_id':'1','quote':'我只能周末去'}])
        self.assertEqual(record['context_revision'],2)
        recalled=cm.recall(batch+[record,row(3,'周末去')],'周末去',0)
        self.assertEqual(len(recalled),1)
        self.assertEqual(recalled[0]['role'],'user')

    def test_missing_or_deleted_summary_source_is_not_replayed(self):
        record=cm.grounded_summary_record([row(1,'只能周末去')],{'notes':[{'source_id':'1','quote':'只能周末去'}]},99)
        self.assertEqual(cm.recall([record],'周末去',0),[])

    def test_memory_no_fill_and_superseded_excluded(self):
        import pet
        with tempfile.TemporaryDirectory() as folder:
            store=pet.MemoryStore(str(Path(folder)/'memory.json'))
            store.items=[dict(id='1',content='用户喜欢吃牛肉',status='active'),
                         dict(id='2',content='用户只在工作日吃牛肉',status='superseded')]
            with patch.object(pet,'_embed_texts',side_effect=AssertionError('offline')):
                self.assertEqual(store.injectable('准备去图书馆',relevant_only=True),[])
                self.assertEqual(store.injectable('',relevant_only=True),[])
                self.assertEqual([x['id'] for x in store.injectable('吃牛肉',relevant_only=True)],['1'])

    def test_profile_real_adapter_preserves_feedback_beyond_gap(self):
        import pet
        from memory_maintenance import MemoryFeaturesMixin
        rows=[row(1,'别老拿复习的事情套我了',at=100),row(2,'好的。','assistant',at=101),
              row(3,'论文报告','assistant','proactive',at=5000),row(4,'午饭吃面',at=5001)]
        app=SimpleNamespace(_chat_log=rows,_chat_lock=threading.RLock(),_settings={})
        with patch.object(pet,'DESKTOP_DIALOGUE_PROFILE','s31r-o1b'):
            history,system=MemoryFeaturesMixin._recent_messages(app,'午饭吃面','weixin')
        self.assertEqual(history,[])
        self.assertIn(rows[0]['text'],system)
        self.assertNotIn('论文报告',system)


if __name__=='__main__':unittest.main()
