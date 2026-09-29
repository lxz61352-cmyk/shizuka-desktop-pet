"""Delivery is tested with synthetic transport only, never the bound WeChat account."""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]
from weixin_segments import (BREAK, MORE, END, SegmentBuffer, clean_control, split_long,
                             ReplyProgress, DeliveredReply, generate)


class FakeClient:
    def __init__(self, *runs):
        self.runs, self.requests = list(runs), []
        self.chat = NS(completions=self)

    @contextmanager
    def create(self, **kwargs):
        self.requests.append(kwargs)
        run = self.runs.pop(0)
        def chunks():
            for item in run:
                if callable(item):
                    item()
                    continue
                if isinstance(item, Exception):
                    raise item
                yield NS(choices=[NS(delta=NS(content=item, reasoning_content='NEVER DISPLAY'))])
        yield chunks()


class SegmentTests(unittest.TestCase):
    def progress(self, send=None):
        return ReplyProgress(lambda v: None, send or (lambda *args: None),
                             threading.Event(), threading.Event(), delay=False)

    def run_reply(self, client, progress=None):
        log = []
        p = progress or self.progress()
        result = generate(client, dict(model='fake', messages=[{'role':'system','content':'角色'},
            {'role':'user','content':'测试'}]), p, lambda v: v, log.append)
        self.assertEqual(log, p.sent)
        return result, p

    def test_markers_across_every_possible_chunk_boundary(self):
        source = '先吃饭吧。'+BREAK+'这家土豆挺好吃的。'+MORE
        for step in range(1, len(source)):
            buf, out = SegmentBuffer(), []
            for at in range(0, len(source), step):
                out.extend(buf.feed(source[at:at+step]))
            tail, more = buf.finish()
            self.assertTrue(more)
            self.assertEqual([clean_control(v) for v in out+[tail]], ['先吃饭吧。','这家土豆挺好吃的。'])

    def test_code_is_not_control_and_extra_breaks_become_paragraphs(self):
        code = '```python\nprint("'+BREAK+'")\n```'
        buf = SegmentBuffer()
        self.assertEqual(buf.feed(code+BREAK+'第二'+BREAK+'第三'+BREAK+'第四'), [code,'第二'])
        tail, more = buf.finish()
        self.assertEqual(clean_control(tail), '第三\n\n第四')
        self.assertFalse(more)
        self.assertEqual(clean_control('`'+MORE+'`'), '`'+MORE+'`')
        self.assertEqual(clean_control('[[1, 2], [3, 4]]'), '[[1, 2], [3, 4]]')
        self.assertEqual(clean_control('说完了[[WX_MOR'), '说完了')

    def test_long_math_and_code_are_not_truncated(self):
        value = ('这是完整的推导步骤。\n'*200)+'```python\n'+('print(1)\n'*1300)+'```\n最后结论。'
        parts = list(split_long(value))
        self.assertTrue(all(len(part)<=1400 for part in parts))
        self.assertEqual(''.join(parts), value)

    def test_first_segment_is_delivered_before_stream_finishes(self):
        p = self.progress()
        client = FakeClient(['行啊。'+BREAK, lambda:self.assertEqual(p.sent,['行啊。']), '哪一家？'])
        result, p = self.run_reply(client,p)
        self.assertEqual(p.sent,['行啊。','哪一家？'])
        self.assertEqual(result.status,'complete')
        self.assertEqual(len(client.requests),1)

    def test_one_bounded_continuation_with_sent_context(self):
        client = FakeClient(['好啊。'+MORE],['你上次说那家还开着吗？'+MORE])
        result,p = self.run_reply(client)
        self.assertEqual(p.sent,['好啊。','你上次说那家还开着吗？'])
        self.assertEqual(len(client.requests),2)
        self.assertEqual(client.requests[1]['messages'][-2],{'role':'assistant','content':'好啊。'})
        self.assertNotIn('NEVER DISPLAY',result.text)

    def test_question_or_long_reply_does_not_request_continuation(self):
        for value in ('哪一家？','哪家啊，这么离谱。','诶，快说快说。','完整解答。'*240):
            client=FakeClient([value+MORE])
            result,p=self.run_reply(client)
            self.assertEqual(len(client.requests),1)
            self.assertNotIn(MORE,result.text)

    def test_empty_or_repeated_followup_is_not_sent(self):
        for extra in (END,'好啊。','好啊！'):
            result,p=self.run_reply(FakeClient(['好啊。'+MORE],[extra]))
            self.assertEqual(p.sent,['好啊。'])

    def test_new_message_cancels_unsent_tail(self):
        p=self.progress()
        result,p=self.run_reply(FakeClient(['第一条'+BREAK,p.superseded.set,'第二条'+MORE]),p)
        self.assertEqual(p.sent,['第一条'])
        self.assertEqual(result.status,'interrupted')

    def test_cancellation_during_optional_generation(self):
        p=self.progress()
        client=FakeClient(['第一条'+MORE],['还想说',p.cancel.set,'额外内容'])
        result,p=self.run_reply(client,p)
        self.assertEqual(p.sent,['第一条'])
        self.assertEqual(result.status,'interrupted')

    def test_generation_and_transport_errors_do_not_duplicate_or_log_unsent(self):
        result,p=self.run_reply(FakeClient(['第一条'+BREAK,TimeoutError()]))
        self.assertEqual(p.sent,['第一条'])
        self.assertEqual(result.status,'generation_failed')
        send=Mock(side_effect=[None,ConnectionError()])
        result,p=self.run_reply(FakeClient(['第一条'+BREAK+'第二条']), self.progress(send))
        self.assertEqual(p.sent,['第一条'])
        self.assertEqual(send.call_count,2)
        self.assertEqual(result.status,'delivery_failed')

    def test_grouped_replies_remain_one_memory_turn_and_not_proactive(self):
        import conversation_memory as cm
        rows=[dict(id='u',role='user',text='好饿',kind='weixin',created=100)]
        rows += [dict(id='a'+str(n),role='assistant',text=t,kind='weixin',created=101+n,
                      turn_id='wxreply:g') for n,t in enumerate(['先吃饭吧。','想吃什么？'])]
        from sync_store import stable_rows
        rows = stable_rows('chats', rows)
        turns=cm.recent_turns(rows)
        self.assertEqual(len(turns),1)
        self.assertEqual(turns[0]['assistant'],'先吃饭吧。\n\n想吃什么？')
        self.assertEqual(turns[0]['ids'],('u','a0','a1'))
        self.assertNotIn('此前主动消息',str(cm.recent_messages(rows,dated=True)))
        self.assertEqual(cm.recent_messages(rows,limit=1),[])

    def test_real_adapter_uses_segments_and_switch_can_disable_it(self):
        import pet
        import desktop_dialogue_profile
        from test_weixin_prompt_offline import _WeixinCapture
        recorder=[]
        with patch.multiple(pet, DESKTOP_DIALOGUE_PROFILE=desktop_dialogue_profile.PROFILE,
                ENHANCED_MODE=True, DIALOGUE_V2=False, TONE_MODE=0, api_model=lambda:'fake',
                has_api_key=lambda:True, load_settings=lambda:{}):
            for enabled in (True,False):
                app=_WeixinCapture(recorder)
                app._weixin_store=NS(data={'segmented_replies':enabled})
                app._weixin_remember_reply=Mock()
                app._log_chat=Mock()
                client=FakeClient(['第一条'+(BREAK+'第二条' if enabled else '')])
                with patch.object(pet,'get_client',return_value=client):
                    result=app._weixin_reply('测试',threading.Event(),self.progress())
                self.assertEqual(isinstance(result,DeliveredReply),enabled)
                assistants=[c for c in app._log_chat.call_args_list if c.args[0]=='assistant']
                self.assertEqual(len(assistants),2 if enabled else 1)
                if enabled:
                    self.assertEqual(assistants[0].kwargs['reply_group'],assistants[1].kwargs['reply_group'])


if __name__=='__main__': unittest.main()
