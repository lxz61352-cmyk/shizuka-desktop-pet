from pathlib import Path
import json,os,sys,tempfile,threading,unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools'),str(ROOT/'tests')]
os.environ.setdefault('SHIZUKA_DATA_DIR',tempfile.mkdtemp(prefix='topic-tests-'))
import sensitive_topics as topic


class SensitiveTopicTests(unittest.TestCase):
    def test_explicit_boolean_only(self):
        for value in (None,False,0,1,'true','false',[],{}):
            self.assertFalse(topic.enabled(NS(_settings={topic.SETTING:value})))
        self.assertTrue(topic.enabled(NS(_settings={topic.SETTING:True})))
        self.assertFalse(topic.enabled(NS(_sensitive_topics_on=False,_settings={topic.SETTING:True})))

    def test_settings_read_defaults_and_invalid_data(self):
        import pet
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            with patch.object(pet,'SETTINGS_FILE',str(path)):
                self.assertFalse(pet.load_settings()[topic.SETTING])
                for value in (False,True,'true','false',1):
                    path.write_text(json.dumps({topic.SETTING:value}),'utf-8')
                    self.assertEqual(pet.load_settings()[topic.SETTING],value is True)

    def test_both_actual_channel_requests_follow_toggle_each_turn(self):
        import pet
        import run_shizuka_phase_s0 as s0
        from test_weixin_prompt_offline import _WeixinCapture, _Client, _Cancel
        with tempfile.TemporaryDirectory() as folder,patch.multiple(pet,
                DESKTOP_DIALOGUE_PROFILE='s31r-o1b',ENHANCED_MODE=True,DIALOGUE_V2=False,
                TONE_MODE=0,DATA_DIR=folder,has_api_key=lambda:True,api_model=lambda:'fake'):
            desktop_requests=[];wechat_requests=[]
            Desktop=s0._build_capture_class(pet)
            desktop=Desktop(desktop_requests,history=[],time_block='',memory_block='')
            wechat=_WeixinCapture(wechat_requests)
            for value in (False,True,False):
                desktop._sensitive_topics_on=wechat._sensitive_topics_on=value
                with patch.object(pet,'get_client',lambda:s0._Client(desktop_requests)):
                    desktop._ask_model('今天吃了面')
                with patch.object(pet,'get_client',lambda:_Client(wechat_requests)):
                    wechat._weixin_reply('今天吃了面',_Cancel(),lambda *args:None)
                for messages in (desktop_requests[-1]['messages'],wechat_requests[-1]):
                    self.assertEqual(messages[0]['content'].count(topic.policy(value)),1)
                    self.assertNotIn(topic.policy(not value),messages[0]['content'])
                    self.assertEqual(messages[-1]['content'],'今天吃了面')

    def test_shared_composer_retains_mode_in_followup_context(self):
        from enhanced_dialogue import compose_messages
        from weixin_segments import generate,ReplyProgress,MORE
        from test_weixin_segments import FakeClient
        client=FakeClient(['这句先到这里。'+MORE],['补充一句。'])
        messages=compose_messages('角色','你好',[],sensitive_topics=False)
        progress=ReplyProgress(lambda _:None,lambda *args:None,threading.Event(),threading.Event(),delay=False)
        generate(client,dict(model='fake',messages=messages),progress,lambda value:value,lambda _:None)
        self.assertEqual(len(client.requests),2)
        for call in client.requests:self.assertIn(topic.policy(False),call['messages'][0]['content'])


if __name__=='__main__':unittest.main()
