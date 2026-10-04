"""Compare real desktop/WeChat adapters using identical fictional inputs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_daily_profile_runtime as fixtures
FakeClient, PLAN, USER = fixtures.FakeClient, fixtures.PLAN, fixtures.USER
import reply_turn
import persona_relaxed_trial as relaxed
from weixin_segments import DeliveredReply


class RetryClient(FakeClient):
    def create(self, **kwargs):
        if kwargs.get('stream'):
            return super().create(**kwargs)
        self.requests.append(deepcopy(kwargs))
        return NS(choices=[NS(message=NS(content=self.runs.pop(0)))])


class ChannelParityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DailyProfileIntegrationTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine=self.fixture.pet
        self.history=[dict(role='user',content='我喜欢推理故事'),dict(role='assistant',content='破案那种？')]
        self.notes='【应用回执】待办备注已保存'
        self.memory='【相关记忆】用户喜欢推理故事'
        self.source='【联网查到的资料】这是公开检索的虚构测试材料'
        self.fixture.stack.enter_context(patch('reply_turn.evidence',return_value=self.source))
        self.fixture.stack.enter_context(patch('pre_reply_fit.should_assess_fit',return_value=True))
        self.fit=self.fixture.stack.enter_context(patch('pre_reply_fit.guidance_block',return_value='【接话判断】只接当前这句'))

    def reset_state(self):
        if self.fixture.path.exists():
            self.fixture.path.unlink()

    def app(self, channel, segmented=False):
        cls=self.fixture.DesktopCapture if channel=='desktop' else self.fixture.WeixinCapture
        app=cls([])
        app._recent_messages=lambda **kwargs:(deepcopy(self.history),'【时间】固定测试时间')
        app._todo_note_context=lambda *args,**kwargs:self.notes
        app._get_memory_block=lambda *args,**kwargs:self.memory
        if channel=='desktop':
            app._web_evidence=lambda *args,**kwargs:self.source
            app.finished=[]
            app._ui=lambda fn:fn()
            app._stream_update=lambda *args:None
            app._stream_finish=lambda text,*args:app.finished.append(text)
        else:
            app._weixin_store=NS(data={'segmented_replies':segmented})
            app._log_chat=Mock()
            app._weixin_remember_reply=Mock()
        return app

    def run_adapter(self, channel, body='这回真拿到了！', segmented=False, client=None):
        self.reset_state()
        app=self.app(channel,segmented)
        client=client or FakeClient([PLAN],[body])
        progress=self.fixture.progress()
        with patch.object(self.engine,'get_client',return_value=client) as get_client:
            if channel=='desktop':
                app._ask_model(USER,my_conv=1)
                result=app.finished[-1]
            else:
                result=app._weixin_reply(USER,progress.cancel,progress)
                if isinstance(result,DeliveredReply):result=result.text
                else:progress.finish_delivery(True)
        app.client_lookups=get_client.call_count
        return result,client,app

    def normalized(self, request, channel, segmented):
        result=deepcopy(request)
        system=result['messages'][0]['content']
        system=system.replace(reply_turn.CAPABILITIES[channel],reply_turn.CAPABILITIES['desktop'])
        if segmented:
            suffix='\n\n'+relaxed.INSTRUCTION
            self.assertTrue(system.endswith(suffix))
            system=system[:-len(suffix)]
        result['messages'][0]['content']=system
        return result

    def test_identical_assessment_core_context_fit_and_body_parameters(self):
        desktop,dc,_=self.run_adapter('desktop')
        for segmented in (False,True):
            with self.subTest(segmented=segmented):
                weixin,wc,_=self.run_adapter('weixin',segmented=segmented)
                self.assertEqual(dc.requests[0],wc.requests[0])
                self.assertEqual(self.normalized(dc.requests[1],'desktop',False),
                                 self.normalized(wc.requests[1],'weixin',segmented))
                self.assertEqual(desktop,weixin)
                self.assertEqual(self.fixture.saved()['state']['mood'],71)

    def test_light_fit_guidance_reaches_both_channels_without_forcing_one_sentence(self):
        import response_fit
        self.fit.side_effect=lambda *args,**kwargs: response_fit.render(dict(
            acts=['play'], emotion='happy', weight='light', focus_quote='x',
            extension='optional_interest', extension_quote='x'))
        requests=[]
        for channel,segmented in (('desktop',False),('weixin',False),('weixin',True)):
            _,client,_=self.run_adapter(channel,segmented=segmented)
            request=self.normalized(client.requests[1],channel,segmented)
            system=request['messages'][0]['content']
            self.assertIn('有具体、尚未知的地方可自然好奇',system)
            self.assertIn('小事轻巧地接住',system)
            self.assertNotIn('回一句短的就好',system)
            self.assertNotIn('不要补充、不要追问、不要铺开',system)
            requests.append(request)
        self.assertEqual(requests[0],requests[1])
        self.assertEqual(requests[0],requests[2])

    def test_same_self_history_guard_applies_to_every_transport(self):
        bad='我昨天去图书馆学习了。这个我可以解释。'
        with patch('self_history_guard.guard',return_value=('这个我可以解释。',['我昨天去图书馆学习了。'])) as guard:
            for channel,segmented in (('desktop',False),('weixin',False),('weixin',True)):
                result,_,_=self.run_adapter(channel,bad,segmented)
                self.assertEqual(result,'这个我可以解释')
        self.assertEqual(guard.call_count,3)

    def test_published_profile_overrides_old_channel_gray_flags(self):
        desktop,dc,_=self.run_adapter('desktop')
        with patch.object(self.engine,'ENHANCED_MODE',False),patch.object(self.engine,'ENHANCED_DESKTOP_ONLY',True,create=True):
            for channel,segmented in (('desktop',False),('weixin',False),('weixin',True)):
                result,client,_=self.run_adapter(channel,segmented=segmented)
                self.assertEqual(result,desktop)
                self.assertEqual(self.normalized(dc.requests[1],'desktop',False),
                                 self.normalized(client.requests[1],channel,segmented))

    def test_empty_retry_is_checked_and_uses_same_parameters(self):
        replies=[];retry_requests=[]
        bad='我昨天去图书馆学习了。这个我可以解释。'
        with patch('self_history_guard.guard',return_value=('这个我可以解释。',['我昨天去图书馆学习了。'])):
            for channel,segmented in (('desktop',False),('weixin',False),('weixin',True)):
                client=RetryClient([PLAN],[],bad)
                result,client,app=self.run_adapter(channel,segmented=segmented,client=client)
                replies.append(result)
                self.assertEqual(len(client.requests),3)
                self.assertEqual(app.client_lookups,1)
                request=self.normalized(client.requests[2],channel,segmented)
                retry_requests.append(request)
                self.assertEqual(self.fixture.saved()['state']['mood'],71)
        self.assertEqual(replies,['这个我可以解释']*3)
        self.assertEqual(retry_requests[0],retry_requests[1])
        self.assertEqual(retry_requests[0],retry_requests[2])
        self.assertNotIn('stream',retry_requests[0])

    def test_visible_source_material_is_the_same_for_output_checks(self):
        cleaner=reply_turn.ReplyCleaner(self.engine,object(),{},lambda:False,USER,self.history,
            notes=self.notes,memory=self.memory,source=self.source)
        for item in (self.notes,self.memory,self.source,USER):self.assertIn(item,cleaner.facts)
        cleaner.include_content([dict(type='text',text='附件里的明确原话'),
                                 dict(type='image_url',image_url={'url':'NEVER_INCLUDE_IMAGE_URL'})])
        self.assertIn('附件里的明确原话',cleaner.facts)
        self.assertNotIn('NEVER_INCLUDE_IMAGE_URL',cleaner.facts)
        self.assertNotIn('persona',cleaner.facts)

    def test_empty_stream_does_not_turn_the_first_retry_segment_into_a_tail(self):
        from reply_trim import trim_reply
        client=RetryClient([PLAN],[], '第一条回复。')
        with patch('reply_trim.trim_reply',wraps=trim_reply) as trim:
            result,_,_=self.run_adapter('weixin',segmented=True,client=client)
        self.assertEqual(result,'第一条回复')
        self.assertEqual([call.args[3] for call in trim.call_args_list],['first'])

    def test_explicit_memory_channel_does_not_anchor_on_same_text_from_other_channel(self):
        from dialogue_context import select_rows
        rows=[dict(id='d1',role='user',text='相同输入',kind='chat',created=100),
              dict(id='w1',role='user',text='相同输入',kind='weixin',created=101)]
        app=NS(_chat_lock=threading.RLock(),_chat_log=rows)
        memory=NS(injectable=lambda *args,**kwargs:[])
        with patch.object(self.engine,'get_memory',return_value=memory),patch('dialogue_context.select_rows',wraps=select_rows) as selector,patch('conversation_memory.recall',return_value=[]):
            self.engine.DeskPet._get_memory_block(app,'相同输入',channel='desktop')
            self.engine.DeskPet._get_memory_block(app,'相同输入',channel='weixin')
        self.assertEqual([(c.args[2],c.args[3]) for c in selector.call_args_list],[('desktop','d1'),('weixin','w1')])

    def test_partial_delivery_never_retries_a_whole_reply(self):
        self.reset_state()
        app=self.app('weixin',True)
        client=RetryClient([PLAN],['第一条已经写好\n[[WX_BREAK]]\n',RuntimeError('synthetic stream error')], '不该重发')
        progress=self.fixture.progress()
        with patch.object(self.engine,'get_client',return_value=client):
            result=app._weixin_reply(USER,progress.cancel,progress)
        self.assertEqual(result.status,'generation_failed')
        self.assertEqual(len(client.requests),2)
        self.assertFalse(self.fixture.path.exists())


if __name__=='__main__':unittest.main()
