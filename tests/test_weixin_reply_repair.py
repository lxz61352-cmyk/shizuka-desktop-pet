import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from weixin_reply_repair import explicit_repair,repair_context


def row(ident,role,text,group=None,kind='weixin'):
    return dict(id=ident,role=role,text=text,turn_id=group,kind=kind,created=100)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.rows=[row('u','user','我今天去那家店了'),
                   row('a','assistant','你和朋友去的。','wxreply:one'),
                   row('b','assistant','那家店很好。','wxreply:one')]

    def test_explicit_only(self):
        for text in ('你刚才说的是编的','你刚才第二条不对','上一条回复理解错了','重新回答刚才那个问题'):
            self.assertTrue(explicit_repair(text),text)
        for text in ('不是这个意思','你又编了','第二条是什么','你刚才说得很好','重新回答','不是明天，是后天','“你刚才说错了”这句话怎么翻译','如果你刚才说错了','/电脑 你刚才说错了'):
            self.assertFalse(explicit_repair(text),text)

    def test_second_delivered_part(self):
        note=repair_context(self.rows,'你刚才第二条不对')
        self.assertIn('那家店很好',note)
        self.assertNotIn('你和朋友去的',note)
        self.assertIn('我今天去那家店了',note)

    def test_exact_quote_can_target_earlier_reply(self):
        note=repair_context(self.rows,'你前面说“你和朋友去的”是编的')
        self.assertIn('你和朋友去的',note)
        self.assertNotIn('那家店很好',note)

    def test_missing_and_ambiguous_never_fall_back(self):
        for rows,text in ((self.rows,'你刚才第三条不对'),([], '你刚才说错了'),
                          (self.rows,'你前面说“没有这句话”是编的')):
            self.assertIn('未定位',repair_context(rows,text))
        rows=self.rows+[row('c','assistant','你和朋友去的。')]
        self.assertIn('未定位',repair_context(rows,'你前面说“你和朋友去的”是编的'))

    def test_other_channels_and_tool_results_excluded(self):
        for kind in ('chat','weixin_file','weixin_todo','weixin_proactive'):
            rows=[row('a','assistant','你和朋友去的。',kind=kind)]
            self.assertIn('未定位',repair_context(rows,'你刚才说错了'))

    def test_future_messages_not_used(self):
        rows=self.rows+[row('current','user','你刚才说错了'),row('future','assistant','未来内容')]
        note=repair_context(rows,'你刚才说错了','current')
        self.assertNotIn('未来内容',note)

    def test_no_request_means_no_added_prompt(self):
        self.assertEqual(repair_context(self.rows,'天气很好'),'')

    def test_no_style_directives(self):
        note=repair_context(self.rows,'你刚才说错了')
        for word in ('简短回复','一两句','道歉','口语化','改变语气'):
            self.assertNotIn(word,note)

    def test_adapter_no_longer_injects_special_repair(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch
        from memory_maintenance import MemoryFeaturesMixin
        text='你刚才第二条不对'
        app=SimpleNamespace(_chat_log=self.rows+[row('current','user',text)],_chat_lock=threading.RLock(),_settings={})
        with patch.dict(sys.modules,{'pet':SimpleNamespace(DESKTOP_DIALOGUE_PROFILE='daily-examples-v1')}):
            _,context=MemoryFeaturesMixin._recent_messages(app,text,'weixin')
        self.assertNotIn('明确回复修正',context)

    def test_reference_bypasses_implicit_tool_routes(self):
        source=(Path(__file__).resolve().parents[1]/'src/weixin_ui.py').read_text('utf-8')
        self.assertIn('if not referencing and task is None',source)
        self.assertIn("notes='' if referencing else",source)
        self.assertIn('todo_text=None if referencing else',source)
