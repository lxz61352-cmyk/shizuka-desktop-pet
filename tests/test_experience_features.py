"""Synthetic state, delivery, restore and diagnostics integration checks."""
import json,os,sys,tempfile,threading,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
os.environ.setdefault('SHIZUKA_DATA_DIR',tempfile.mkdtemp(prefix='experience-tests-'))
import proactive_chat as pro
import memory_lifecycle as life
from weixin_channel import ProtectedStore,WeixinChannel


class ProactiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=time.mktime((2026,9,29,12,0,0,0,0,-1))
        self.store=ProtectedStore(self.tmp.name,lambda b,protect:b)
        self.store.update(enabled=True,session={'owner':'owner','bot_id':'bot','token':'synthetic','base':'https://ilinkai.weixin.qq.com','bound_at':1},
                          notification_context={'owner':'owner','bot':'bot','context':'synthetic'},chat_merge_seconds=.1)
        self.client=Mock();self.generate=Mock(return_value={'text':'你上次提的那个拼图，看着就很考验耐心啊。','topic':'puzzle','category':'interest'})
        self.channel=WeixinChannel(self.store,Mock(return_value='reply'),client=self.client,proactive=self.generate)
        self.addCleanup(self.channel.stop)
        self.value=pro.state({});self.value.update(enabled=True,last_user=self.now-3600)
        self.store.update(proactive_chat=self.value)

    def msg(self,text,ident='1',**extra):
        return dict(from_user_id='owner',to_user_id='bot',message_type=1,message_state=2,
                    message_id=ident,context_token='synthetic',create_time_ms=100000,
                    item_list=[{'type':1,'text_item':{'text':text}}],**extra)

    def test_default_off_and_exact_commands(self):
        self.assertFalse(pro.state({})['enabled'])
        self.assertIsNone(pro.command('他说 /主动 开启',{}))
        value,reply=pro.command('/主动 开启',{},self.now)
        self.assertTrue(value['enabled']);self.assertEqual(value['last_user'],self.now)
        for bad in ('25:00-22:00','10:80-22:00','10:00-10:00'):
            new,_=pro.command('/主动 时间 '+bad,{'proactive_chat':value},self.now)
            self.assertEqual(new['start'],600)

    def test_gates_time_cap_cooldown_unanswered(self):
        self.assertTrue(pro.eligible(self.value,self.now)[0])
        for changes in ({'enabled':False},{'awaiting':True},{'paused_until':self.now+1},
                        {'last_user':self.now-10},{'last_sent':self.now-60},
                        {'start':13*60,'end':14*60},
                        {'history':[{'at':self.now-3600},{'at':self.now-4000}]}):
            self.assertFalse(pro.eligible(dict(self.value,**changes),self.now)[0],changes)
        self.assertTrue(pro.eligible(dict(self.value,start=22*60,end=8*60,last_user=self.now-11*3600),self.now-10*3600)[0])

    def test_unanswered_persists_and_normal_user_resumes(self):
        with patch('time.time',return_value=self.now):
            self.assertTrue(self.channel.proactive_tick());self.assertFalse(self.channel.proactive_tick())
        restored=ProtectedStore(self.tmp.name,lambda b,p:b)
        self.assertTrue(pro.state(restored.data)['awaiting'])
        self.assertEqual(pro.state(restored.data)['history'][-1]['category'],'interest')
        self.channel.receive(self.msg('刚看到了'))
        self.assertFalse(pro.state(self.store.data)['awaiting'])
        self.assertEqual(self.client.send.call_count,1)

    def test_controls_authorized_owner_only_and_do_not_call_model(self):
        raw=self.msg('/主动 关闭');raw['from_user_id']='stranger';self.channel.receive(raw)
        self.assertTrue(pro.state(self.store.data)['enabled'])
        self.channel.receive(self.msg('/主动 关闭'))
        self.assertFalse(pro.state(self.store.data)['enabled']);self.generate.assert_not_called()
        self.assertTrue(self.channel.jobs.empty())

    def test_turning_off_during_generation_prevents_send(self):
        def generate(value,cancel):
            self.channel.receive(self.msg('/主动 关闭'))
            return {'text':'想起一件事了。','topic':'x'}
        self.channel.proactive=generate
        with patch('time.time',return_value=self.now):self.assertFalse(self.channel.proactive_tick())
        self.assertEqual(self.client.send.call_count,1) # only explicit command acknowledgement
        self.assertIn('主动搭话：关闭',self.client.send.call_args.args[2])

    def test_delivery_uncertain_never_automatically_retries(self):
        self.client.send.side_effect=TimeoutError('synthetic')
        with patch('time.time',return_value=self.now):
            with self.assertRaises(TimeoutError):self.channel.proactive_tick()
            self.assertFalse(self.channel.proactive_tick())
        self.assertTrue(pro.state(self.store.data)['awaiting'])
        self.assertEqual(self.client.send.call_count,1)

    def test_skip_and_busy_make_no_delivery(self):
        self.channel.active=True
        with patch('time.time',return_value=self.now):self.assertFalse(self.channel.proactive_tick())
        self.generate.assert_not_called();self.channel.active=False
        self.channel.proactive=Mock(return_value=None)
        with patch('time.time',return_value=self.now):self.assertFalse(self.channel.proactive_tick())
        self.client.send.assert_not_called()

    def test_preference_changed_during_send_is_not_overwritten(self):
        def changed(*args):
            value=pro.state(self.store.data);value['enabled']=False
            self.store.update(proactive_chat=value)
        self.client.send.side_effect=changed
        with patch('time.time',return_value=self.now):self.assertTrue(self.channel.proactive_tick())
        self.assertFalse(pro.state(self.store.data)['enabled'])

    def test_new_desktop_activity_after_generation_stops_send(self):
        allowed=[True]
        self.channel.proactive_guard=lambda:allowed[0]
        def generate(value,cancel):allowed[0]=False;return {'text':'想起了拼图。','topic':'p'}
        self.channel.proactive=generate
        with patch('time.time',return_value=self.now):self.assertFalse(self.channel.proactive_tick())
        self.client.send.assert_not_called()

    def test_expired_sensitive_and_used_topics_excluded(self):
        rows=[{'id':'a','content':'用户喜欢拼图'},{'id':'b','content':'用户喜欢复习'},
              {'id':'c','content':'用户喜欢音乐','status':'completed'}]
        found=pro.candidates(rows,[],[],self.now);self.assertEqual(len(found),1)
        self.assertEqual(pro.candidates(rows,[],[{'topic':found[0]['topic'],'at':self.now}],self.now),[])
        self.assertFalse(pro.acceptable('在吗，怎么不回我',[]))
        self.assertTrue(pro.invented_observation('刚才窗外开始下雨了，想到你喜欢雨声，我就没关窗。'))
        self.assertTrue(pro.invented_observation('上次有人做了一桌菜，我吃到一半才发现全是土豆。'))
        self.assertTrue(pro.invented_observation('刚才看到有人说专门录雨声听。'))

    def test_merge_burst_preserves_commands_and_order(self):
        first={'key':'a','context':'first','text':'今天吃了炒饭'}
        self.channel.queue_job({'key':'b','context':'second'},'还不错')
        self.channel.queue_job({'key':'c','context':'third'},'/电脑 看文件')
        merged=self.channel._collect_burst(first,threading.Event())
        self.assertEqual(merged['text'],'今天吃了炒饭\n还不错')
        self.assertEqual(merged['context'],'second')
        self.assertEqual(self.channel.jobs.get_nowait()['text'],'/电脑 看文件')

    def test_reply_to_proactive_has_its_actual_context(self):
        from dialogue_context import select_rows
        rows=[{'id':'p','role':'assistant','kind':'weixin_proactive','created':self.now-3600,'text':'拼图又出新图案了'},
              {'id':'u','role':'user','kind':'weixin','created':self.now,'text':'哪一款？'}]
        self.assertEqual(select_rows(rows,'哪一款？','weixin','u'),rows)


class DataTests(unittest.TestCase):
    def test_temporary_expiry_pin_and_explicit_long_term(self):
        at=time.mktime((2026,9,28,12,0,0,0,0,-1))
        row={'content':'用户今天复习','created':at,'pinned':True}
        self.assertFalse(life.active(row,at+86400))
        self.assertTrue(life.active(dict(row,expires_at=0),at+86400))
        self.assertTrue(life.active({'content':'用户喜欢《明天》这首歌','created':at},at+86400))
        self.assertFalse(life.active(dict(row,status='completed'),at))

    def test_undo_preserves_background_changes(self):
        before=[{'id':'a','content':'old','last_used':0}];after=[{'id':'a','content':'new','last_used':0}]
        current=[{'id':'a','content':'new','last_used':3},{'id':'b','content':'fresh'}]
        rows,conflicts=life.undo_edit(current,before,after)
        self.assertEqual(rows[0],{'id':'a','content':'old','last_used':3});self.assertEqual(rows[1],current[1]);self.assertFalse(conflicts)
        current[0]['content']='newer';rows,conflicts=life.undo_edit(current,before,after)
        self.assertEqual(rows[0]['content'],'newer');self.assertEqual(conflicts,1)

    def test_backup_subset_restore_and_key_exclusion(self):
        from personal_backup import create,inspect,stage_restore,apply_pending
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'characters/shizuka').mkdir(parents=True)
            memory=root/'characters/shizuka/memory.json';memory.write_text('{"items":[{"id":"a"}]}')
            (root/'settings.json').write_text('{"sensitive_topics":true,"api_key":"synthetic-secret"}')
            (root/'weixin-state.json').write_text('{"protected":"secret"}')
            archive=create(root);items=inspect(archive)
            self.assertNotIn('weixin-state.json',items);self.assertNotIn('api_key',items['settings.json'])
            memory.write_text('{"items":[]}');stage_restore(root,archive,['记忆'])
            self.assertEqual(json.loads(memory.read_text()),{'items':[]})
            self.assertTrue(apply_pending(root));self.assertEqual(json.loads(memory.read_text())['items'][0]['id'],'a')
            self.assertFalse(apply_pending(root))

    def test_tampered_backup_rejected_before_writes(self):
        from personal_backup import inspect
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('backup-manifest.json',json.dumps({'schema':1,'files':{'../settings.json':'bad'}}))
                z.writestr('../settings.json','{}')
            with self.assertRaises(ValueError):inspect(path)

    def test_feedback_export_only_selected_and_trace_survives_normalization(self):
        from dialogue_feedback import FeedbackStore
        from sync_store import stable_rows
        with tempfile.TemporaryDirectory() as folder:
            store=FeedbackStore(folder);row={'id':'r','role':'assistant','text':'答复','kind':'chat','created':1,'trace_id':'a'*32}
            self.assertEqual(stable_rows('chats',[row])[0]['trace_id'],'a'*32)
            chosen=store.mark(row,'太像台词','具体备注');store.mark(dict(row,id='other'),'这句不错')
            payload=json.loads(store.export([chosen['id']]))
            self.assertEqual(len(payload['items']),1);self.assertIsNone(payload['items'][0]['trace'])

    def test_trace_carries_to_post_memory_thread(self):
        from dialogue_feedback import post_with_trace,trace_for
        app=NS(_request_traces=threading.local())
        seen=[];app._post_memory=lambda u,a:seen.append(trace_for(app,'chat'))
        t=threading.Thread(target=post_with_trace,args=(app,'u','a','trace'));t.start();t.join()
        self.assertEqual(seen,['trace'])


if __name__=='__main__':unittest.main()
