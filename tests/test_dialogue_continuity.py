import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dialogue_continuity import continuity_context
from conversation_state import ConversationState


def row(text, ident, kind='chat', role='user', at=100):
    return dict(text=text, id=ident, kind=kind, role=role, created=at)


class ContinuityTests(unittest.TestCase):
    def test_actual_correction_replaces_fixed_example(self):
        state=ConversationState()
        state.observe_user('不是明天，是后天')
        state.observe_user('几点呢')
        note=state.correction_followup_note()
        self.assertIn('不是明天，是后天',note)
        self.assertNotIn('甜食',note)
        for _ in range(2):state.observe_user('别的事')
        self.assertEqual(state.correction_followup_note(),'')
        state.reset()
        self.assertIsNone(state.last_correction_text)

    def test_pause_and_resume_latest_state(self):
        rows=[row('先不聊纸模型', '1'),row('纸模型呢','2')]
        self.assertIn('话题暂停',continuity_context(rows,'纸模型呢',current_id='2'))
        rows += [row('继续聊纸模型','3')]
        note=continuity_context(rows,'继续聊纸模型',current_id='3')
        self.assertIn('话题恢复',note)
        self.assertNotIn('话题暂停',note)

    def test_progress_is_replaced_only_by_user_completion(self):
        rows=[row('纸模型还没做完','1'),row('纸模型已经做完了','a',role='assistant'),row('纸模型呢','2')]
        self.assertIn('尚未完成',continuity_context(rows,'纸模型呢'))
        rows.append(row('纸模型已经做完了','3'))
        note=continuity_context(rows,'纸模型呢')
        self.assertIn('已明确完成',note)
        self.assertNotIn('尚未完成',note)

    def test_channels_and_topics_are_isolated(self):
        rows=[row('纸模型还没做完','1',kind='weixin'),row('纸模型呢','2')]
        self.assertEqual(continuity_context(rows,'纸模型呢'),'')
        self.assertEqual(continuity_context([row('先不聊纸模型','1')],'天气怎么样'),'')

    def test_no_future_message_leak(self):
        rows=[row('纸模型还没做完','1'),row('纸模型呢','2'),row('纸模型已经做完了','3')]
        note=continuity_context(rows,'纸模型呢',current_id='2')
        self.assertIn('尚未完成',note)
        self.assertNotIn('已明确完成',note)

    def test_session_gap_resets(self):
        rows=[row('先不聊纸模型','1'),row('纸模型呢','2',at=4000)]
        self.assertEqual(continuity_context(rows,'纸模型呢',current_id='2'),'')

    def test_ambiguous_questions_and_hypotheticals_are_not_facts(self):
        for text in ('纸模型还没做完吗','如果纸模型还没做完','他说纸模型还没做完','先不聊这个'):
            self.assertEqual(continuity_context([row(text,'1')],'纸模型'),'')

    def test_source_and_quote_are_preserved(self):
        note=continuity_context([row('纸模型还没做完','source-1')],'纸模型')
        self.assertIn('source-1',note)
        self.assertIn('纸模型还没做完',note)
        self.assertIn('不写入长期记忆或修改待办',note)

    def test_correction_survives_intervening_topic_when_related(self):
        rows=[row('我上次说纸模型完成了，其实还没有','1')]
        rows += [row('天气很好',str(i)) for i in range(2,7)]
        self.assertIn('事实纠正',continuity_context(rows,'纸模型完成了吗'))

    def test_reports_are_excluded(self):
        self.assertEqual(continuity_context([row('纸模型还没做完','1',kind='report')],'纸模型'),'')


class SharedAdapterTests(unittest.TestCase):
    def test_both_channels_receive_source_context(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch
        from memory_maintenance import MemoryFeaturesMixin
        for channel,kind in (('desktop','chat'),('weixin','weixin')):
            rows=[row('纸模型还没做完','1',kind=kind),row('纸模型呢','2',kind=kind)]
            app=SimpleNamespace(_chat_log=rows,_chat_lock=threading.RLock(),_settings={})
            with patch.dict(sys.modules,{'pet':SimpleNamespace(DESKTOP_DIALOGUE_PROFILE='daily-examples-v1')}):
                history,context=MemoryFeaturesMixin._recent_messages(app,'纸模型呢',channel)
            self.assertIn('尚未完成',context)
            self.assertIn('来源消息',context)
            self.assertTrue(history)

    def test_runtime_paths_use_shared_context_block(self):
        root=Path(__file__).resolve().parents[1]
        for file in ('pet.py','weixin_ui.py'):
            source=(root/'src'/file).read_text('utf-8')
            self.assertIn('self._recent_messages(',source)
            self.assertIn('if time_block:',source)
