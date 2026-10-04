"""Unsolicited openings avoid commerce and private probes across both channels."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import proactive_chat as pro
import proactive_topics as topics
from proactive_content import product_topic,private_topic,prior_openings
from dialogue_features import DialogueFeaturesMixin


class ProactiveContentTests(unittest.TestCase):
    def test_products_and_promotional_wording_are_not_openings(self):
        for text in ('你平时会看这类耳机吗','这款相机的配色真不错','最近出了个新品，挺好看的',
                     'iPhone 这个颜色怎么样','这个配件699元，挺值的','你想买哪款？'):
            with self.subTest(text=text):
                self.assertTrue(product_topic(text));self.assertFalse(pro.acceptable(text,[]))
                self.assertFalse(DialogueFeaturesMixin()._proactive_text_ok(text,{'id':'company'}))

    def test_light_questions_and_noncommercial_interests_survive(self):
        for text in ('晚上吃什么呀？','今天忙不忙？','你喜欢怎样的电影结尾？','拼图最后一块拼上去还挺有成就感。','苹果派好像很适合配热茶。'):
            with self.subTest(text=text):
                self.assertFalse(product_topic(text));self.assertFalse(private_topic(text));self.assertTrue(pro.acceptable(text,[]))

    def test_old_product_openings_are_excluded_from_generation_material(self):
        rows=[dict(text='出了新品耳机。'),dict(text='喜欢怎样的电影结尾？'),dict(text='你现在在哪？')]
        self.assertEqual(prior_openings(rows),['喜欢怎样的电影结尾？'])

    def test_product_interests_never_become_unsolicited_candidates(self):
        memories=[dict(id='a',content='用户喜欢耳机'),dict(id='b',content='用户喜欢拼图')]
        result=pro.candidates(memories,[],[],now=1791000000)
        self.assertEqual([r['id'] for r in result],['memory:b'])

    def test_user_requested_product_question_reaches_both_reply_adapters(self):
        from test_weixin_prompt_offline import _DesktopCapture,_WeixinCapture,_Client,_Cancel,pet
        import weixin_ui
        import todo_model
        desktop_log=[];phone_log=[];question='帮我比较一下耳机型号和价格'
        with patch.multiple(pet,DESKTOP_DIALOGUE_PROFILE='',ENHANCED_MODE=False,DIALOGUE_V2=False,TONE_MODE=0,
                            has_api_key=lambda:True,api_model=lambda:'offline',load_persona=lambda:'合成角色',
                            get_memory=lambda:NS(save=lambda:None),get_client=lambda:_Client(desktop_log)), \
             patch('reply_turn.evidence',return_value=''), \
             patch.object(weixin_ui,'computer_command',return_value=None), \
             patch.object(todo_model,'command',return_value=None), \
             patch.object(weixin_ui,'weixin_image_paths',return_value=[]), \
             patch('socket.create_connection',side_effect=AssertionError('Network forbidden')), \
             patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            desktop=_DesktopCapture([]);desktop._ask_model(question,my_conv=1)
            with patch.object(pet,'get_client',return_value=_Client(phone_log)):
                reply=_WeixinCapture([])._weixin_reply(question,_Cancel(),lambda *a:None)
        self.assertTrue(reply)
        for log in (desktop_log,phone_log):
            self.assertTrue(log);self.assertEqual(log[-1][-1]['content'],question)


if __name__=='__main__':unittest.main()
