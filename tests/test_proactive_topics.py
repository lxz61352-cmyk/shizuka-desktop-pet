"""Topic mix, current-time evidence and sourced news; no live message delivery."""
from pathlib import Path
import json
import sys
import threading
import time
import unittest
from collections import Counter
from email.utils import formatdate
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import proactive_chat as pro
import proactive_topics as topics
import proactive_news as news


class Pick:
    def __init__(self, roll, focus=None): self.roll, self.focus = roll, focus
    def random(self): return self.roll
    def choice(self, options): return next((r for r in options if r.get('focus') == self.focus), options[0])


class TopicsTests(unittest.TestCase):
    def setUp(self):
        self.now = time.mktime((2026,9,29,18,0,0,0,0,-1))
        self.memory = [{'id':'puzzle','content':'用户喜欢拼图'}]
        self.anecdote = dict(id='joke',role='user',kind='weixin',created=self.now-7200,text='笑死，朋友把两只不一样的袜子穿出门了')
        self.news = dict(topic='news:synthetic',title='博物馆举办植物展览',url='https://www.chinanews.com.cn/test.shtml')

    def pick(self, roll, **kwargs):
        return topics.pick_topic(kwargs.pop('memories',self.memory),kwargs.pop('rows',[self.anecdote]),
                                 kwargs.pop('history',[]),self.now,Pick(roll),**kwargs)

    def test_weights_not_accidentally_raised_by_pool_sizes(self):
        counts=Counter()
        for n in range(100):
            counts[self.pick((n+.5)/100,news_loader=lambda **_: [self.news])['category']]+=1
        self.assertEqual(counts,dict(daily=70,interest=20,association=5,news=5))

    def test_news_only_fetched_in_rare_slot_and_capped(self):
        loader=Mock(return_value=[self.news])
        for n in (.2,.8,.92):self.pick(n,news_loader=loader)
        loader.assert_not_called()
        self.assertEqual(self.pick(.98,news_loader=loader)['category'],'news')
        self.assertEqual(loader.call_count,1)
        self.assertEqual(self.pick(.98,history=[dict(category='news',at=self.now-3600)],news_loader=loader)['category'],'daily')
        self.assertEqual(loader.call_count,1)

    def test_missing_rare_sources_fall_back_without_resampling(self):
        self.assertEqual(self.pick(.92,rows=[])['category'],'daily')
        self.assertEqual(self.pick(.99,news_loader=Mock(side_effect=TimeoutError))['category'],'daily')
        self.assertEqual(self.pick(.8,memories=[])['category'],'daily')

    def test_no_memory_still_has_daily_topics_not_fiction(self):
        self.assertEqual(self.pick(.1,memories=[],rows=[])['category'],'daily')
        choices=topics.daily_candidates([],[],[],self.now)
        self.assertEqual({r['focus'] for r in choices},{'plans','leisure','meal-evening'})

    def test_identity_and_meal_time_are_not_guessed(self):
        noon=self.now-6*3600
        old=[dict(self.anecdote,text='昨天上课没带书',created=self.now-86400)]
        self.assertNotIn('course',{r['focus'] for r in topics.daily_candidates([],old,[],noon)})
        memory=[dict(id='student',content='用户是大学生'),dict(id='worker',content='用户在公司工作',status='completed')]
        focuses={r['focus'] for r in topics.daily_candidates(memory,[],[],noon)}
        self.assertIn('course',focuses);self.assertNotIn('work',focuses)
        self.assertTrue(next(r for r in topics.daily_candidates(memory,[],[],noon) if r['focus']=='course')['evidence'])
        self.assertIn('meal-lunch',focuses);self.assertNotIn('meal-evening',focuses)
        saturday=time.mktime((2026,10,3,12,0,0,0,0,-1))
        self.assertNotIn('course',{r['focus'] for r in topics.daily_candidates(memory,[],[],saturday)})

    def test_known_current_answer_and_refusal_are_respected(self):
        answered=[dict(self.anecdote,text='晚饭准备吃面',created=self.now-3600)]
        self.assertNotIn('meal-evening',{r['focus'] for r in topics.daily_candidates([],answered,[],self.now)})
        implicit=[dict(self.anecdote,text='刚吃了炒饭，挺香',created=self.now-60)]
        self.assertNotIn('meal-evening',{r['focus'] for r in topics.daily_candidates([],implicit,[],self.now)})
        refused=[dict(self.anecdote,text='别问吃饭的事情了',created=self.now-86400)]
        self.assertNotIn('meal-evening',{r['focus'] for r in topics.daily_candidates([],refused,[],self.now)})
        loader=Mock(return_value=[self.news])
        self.assertEqual(self.pick(.99,rows=[dict(self.anecdote,text='不要聊新闻')],news_loader=loader)['category'],'daily')
        loader.assert_not_called()

    def test_used_daily_direction_and_story_cooldown(self):
        all_daily=[dict(topic='daily:'+r['focus'],at=self.now-3600) for r in topics.daily_candidates([],[],[],self.now)]
        self.assertIsNone(self.pick(.1,memories=[],rows=[],history=all_daily))
        self.assertEqual(self.pick(.92,history=[dict(category='association',at=self.now-86400)])['category'],'daily')
        rows=topics.daily_candidates([dict(id='w',content='用户在公司工作')],[],
                                     [dict(topic='daily:plans',at=self.now-3600)],self.now)
        self.assertNotIn('work',{r['focus'] for r in rows})

    def test_cancelled_selection_does_not_fetch(self):
        loader=Mock(return_value=[self.news])
        self.assertIsNone(self.pick(.99,news_loader=loader,cancelled=lambda:True));loader.assert_not_called()

    def test_questions_not_mistaken_for_invented_experiences(self):
        for text in ('今天晚上想吃什么啊？','今天忙不忙？','下午课多吗？'):
            self.assertTrue(pro.acceptable(text,[]));self.assertFalse(pro.invented_observation(text))
        for text in ('我今天去吃面了。','刚才看到有人在唱歌。','我刚刚买了杯奶茶。','今天课多吗？我这边刚忙完一段，脑子有点空。','我这边有点闲。'):
            self.assertTrue(pro.invented_observation(text))
        self.assertFalse(pro.acceptable('在吗？怎么不回我',[]))
        for text in ('我正琢磨吃什么呢。','我这儿正纠结呢。','你今天在公司忙不忙？','今天上班怎么样，忙吗？'):
            self.assertTrue(topics.local_problem(text,{'category':'daily'}))
        self.assertFalse(topics.local_problem('今天忙不忙？',{'category':'daily'}))


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.now=time.time();news._cache.clear()
    def feed(self,**kwargs):
        fields=dict(title='植物博物馆举办科普展览',link='https://www.chinanews.com.cn/culture/test.shtml',
                    description='展览介绍植物多样性。',pubDate=formatdate(self.now-60,usegmt=True))
        fields.update(kwargs)
        return '<rss><channel><item>'+''.join('<'+k+'>'+v+'</'+k+'>' for k,v in fields.items())+'</item></channel></rss>'
    def parse(self,body):return news.parse_feed(body,'中国新闻网','www.chinanews.com.cn',self.now)

    def test_dated_linked_light_news_only(self):
        rows=self.parse(self.feed());self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url'],'https://www.chinanews.com.cn/culture/test.shtml')
        for fields in (dict(pubDate=''),dict(pubDate=formatdate(self.now-37*3600,usegmt=True)),
                       dict(pubDate=formatdate(self.now+120,usegmt=True)),dict(link='https://evil.test/a'),
                       dict(link='https://www.chinanews.com.cn:bad/a'),dict(link='http://www.chinanews.com.cn/a'),
                       dict(title='最新手机限时优惠券'),dict(description='展览发生爆炸')):
            self.assertEqual(self.parse(self.feed(**fields)),[],fields)
        self.assertEqual(self.parse('<!DOCTYPE rss>'+self.feed()),[])

    def test_cache_is_revalidated_for_age_and_cancel(self):
        with patch.object(news,'FEEDS',(('中国新闻网','https://www.chinanews.com.cn/rss/scroll-news.xml','www.chinanews.com.cn'),)),patch('weather.http_get',return_value=self.feed()) as get:
            self.assertEqual(len(news.fresh_items(self.now)),1)
            self.assertEqual(len(news.fresh_items(self.now+30)),1);self.assertEqual(get.call_count,1)
            self.assertEqual(news.fresh_items(self.now,cancelled=lambda:True),[])
            self.assertEqual(news.fresh_items(self.now+37*3600),[])


class GenerationTests(unittest.TestCase):
    def run_generation(self,topic,text,verdict=True):
        from test_weixin_prompt_offline import _WeixinCapture,pet
        app=_WeixinCapture([]);app._last_user_dialogue_at=time.monotonic()-7200
        app._chat_lock=threading.RLock();app._chat_log=[]
        client=Mock();client.with_options.return_value=client
        completion=lambda value:NS(choices=[NS(message=NS(content=json.dumps(value,ensure_ascii=False)))])
        client.chat.completions.create.side_effect=[completion({'text':text}),completion({'ok':verdict,'reason':'synthetic'})]
        with patch.multiple(pet,has_api_key=lambda:True,get_memory=lambda:NS(snapshot=lambda:[]),
                            get_client=lambda:client,_disable_thinking=lambda x:x,load_settings=lambda:{},
                            api_model=lambda:'synthetic'),patch('provider_limiter.acquire'),patch.object(topics,'pick_topic',return_value=topic):
            result=app._weixin_proactive_generate(pro.state({}),threading.Event())
        return result,client

    def test_news_source_is_appended_by_code_not_model(self):
        topic=dict(category='news',topic='news:test',title='植物展览',text='博物馆植物展览开幕',source='中国新闻网',url='https://www.chinanews.com.cn/test.shtml')
        result,client=self.run_generation(topic,'博物馆新开了个植物展，看起来还挺有意思的。')
        self.assertEqual(result['category'],'news');self.assertTrue(result['text'].endswith(topic['url']))
        self.assertEqual(client.chat.completions.create.call_count,2)
        self.assertIsNone(self.run_generation(topic,'看看 https://invented.test/a')[0])
        self.assertIsNone(self.run_generation(topic,'有新展览了。',False)[0])

    def test_daily_question_can_pass_without_memory(self):
        topic=dict(category='daily',focus='meal-evening',topic='daily:meal-evening',text='晚饭话题')
        result,_=self.run_generation(topic,'晚上吃什么呀？')
        self.assertEqual(result['text'],'晚上吃什么呀？')
        rejected,client=self.run_generation(topic,'晚上吃什么呀？我这边刚忙完一段。')
        self.assertIsNone(rejected);self.assertEqual(client.chat.completions.create.call_count,1)


if __name__=='__main__':unittest.main()
