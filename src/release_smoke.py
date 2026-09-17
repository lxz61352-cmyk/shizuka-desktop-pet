"""Offline acceptance in a disposable data directory; no real credentials or messages."""
from pathlib import Path
from unittest.mock import patch
import json,sys,time,traceback

def run(pet):
    checks=[];errors=[]
    report=Path(sys.argv[sys.argv.index('--report')+1])
    with patch.object(pet,'read_api_key',return_value=''),patch.object(pet,'_embed_texts',return_value=None),patch.object(pet.DeskPet,'_migrate_api_key'):
        app=pet.DeskPet()
        # 记完整调用栈：只记 str(exc) 时出问题根本查不出是哪个回调炸的。
        app.root.report_callback_exception=lambda *args:errors.append(
            ''.join(traceback.format_exception(*args)))
        try:
            app.root.update();app._motion.reset();app._ground.cancel()
            assert app._character_pack.id=='shizuka-side-motion' and app._character_pack.character_id=='shizuka'
            from character_packs import discover_packs
            packs,issues=discover_packs(pet.CHARACTERS_DIR)
            assert not issues and {p.id for p in packs}=={'shizuka-classic','shizuka-side-motion'}
            from pet_motion import Pose
            for expression in ('neutral','lifted','falling'):
                assert app._animator.frame(420,pose=Pose(expression=expression),color_key=True).size[1]>0
            checks.append('Original character packs, rendering and local expressions')
            app.show_todos();app.root.update();app._todo_new();app.root.update()
            checks.append('Todo list and date/time editor open')
            app._log_chat('assistant','这篇研究发表于《Fixture Journal》。',kind='proactive')
            app._log_chat('user','继续说说这篇研究。',kind='user')
            messages=app._recent_messages(current_text='继续说说这篇研究。',channel='desktop')
            assert any('Fixture Journal' in m['content'] for m in messages)
            assert not any(m['content']=='继续说说这篇研究。' for m in messages)
            app.show_chat_log();app.root.update();checks.append('Conversation history and proactive continuation context')
            app.show_computer_assistant();app.root.update()
            from computer_agent import DshInstallation
            command=DshInstallation('node','bin.js').command('fixture')
            assert Path(command[-2]).is_file() and '--profile' in command and 'headless' in command
            app._computer_open_progress('离线演示',__import__('threading').Event());app.root.update()
            checks.append('File task settings, DSH overlay and read-only progress window')
            app.show_weixin();app.root.update()
            import qrcode
            assert qrcode.make('offline-fixture').size[0]>0
            checks.append('Weixin setup and QR dependency, without sending')
            import tkinter as tk
            menu=tk.Toplevel(app.root);app._menu_marks={};app._submenus=[];app._submenu=None
            app._build_more_settings(menu,1);app.root.update()
            assert app._idle_minutes==5 and app._sound_mode=='todo-files'
            # 免打扰开关与语音新选项：默认「全屏/游戏时安静」，英文音素默认关闭
            import quiet_mode
            assert app._quiet_fullscreen is True and app._quiet_games is True
            assert app._quiet_apps==[] and app._tts_en_phonemes is False
            assert app._quiet_fold is True and app._quiet_active is False
            assert isinstance(app._quiet_now(),str)
            assert quiet_mode.quiet_reason('Overwatch','Overwatch.exe',False)=='Overwatch'
            assert quiet_mode.quiet_reason('Visual Studio Code','Code.exe',False)==''
            # 朗读停顿分级：段落 > 句末 > 逗号/半句，标题前最短
            assert (pet._tts_gap('句子。')==pet.TTS_SENTENCE_GAP_MS
                    and pet._tts_gap('半句，')==pet.TTS_PAUSE_COMMA_MS
                    and pet._tts_gap('没有标点')==pet.TTS_HALF_GAP_MS
                    and pet._tts_gap('这一段的最后一句。',block_end=True)==pet.TTS_PARAGRAPH_GAP_MS
                    and pet._tts_gap('前一句。','《A Title》')==pet.TTS_TITLE_GAP_MS)
            segments=pet._tts_segments('第一段够长的一句话。\n第二段也够长的一句话。')
            assert [block for _piece,block in segments]==[True,False]
            menu.destroy()
            checks.append('Compact settings, five-minute default and notification sound policy')
            app.show_research();app.root.update()
            app._research_init()
            import assistant_features
            assert assistant_features.RESEARCH_ENABLED is True
            # 关注方向：输入框回车确认 → 写进 topics/queries → 落盘；重复加不重复，能删掉。
            assert not app._research.profile['topics']
            assert app._research_entry.bind('<Return>')   # 回车确实绑上了
            app._research_entry.insert(0,'Fixture Topic')
            # Tk 的合成键盘事件只投递到有焦点的窗口（实测：不 focus 就不会触发绑定）。
            app._research_entry.focus_force()
            app._research_entry.event_generate('<Return>',when='now')
            app.root.update()
            if not app._research.profile['topics']:
                app._add_research_keyword()   # 个别环境合成按键不投递时，回退调用同一个处理函数
            assert app._research.profile['topics']==['Fixture Topic'],app._research.profile['topics']
            assert app._research.profile['queries']==['Fixture Topic'],app._research.profile['queries']
            saved=json.loads(app._research.profile_path.read_text('utf-8'))
            assert saved['topics']==['Fixture Topic'],saved
            assert app._add_research_topic('Fixture Topic')
            assert app._add_research_topic('x'*200)
            app._remove_research_topic('Fixture Topic')
            assert app._research.profile['topics']==[] and app._research.profile['queries']==[]
            row={'title':'Synthetic paper','journal':'Fixture Journal','url':'https://example.invalid/paper',
                 'evidence_basis':'title','comment':'可以进一步阅读。','reason':'相关。'}
            text=app._research_notice(row);assert 'Fixture Journal' in text and '题名信息' in text
            assert '主人' not in text   # 静香不喊主人
            # 关注方向标签：长方向名要横向排不下就换行，不能撑出窗口右边
            for topic in ('基于物理信息神经网络与算子学习的偏微分方程数值解法研究及其在湍流模拟中的应用',
                          '机器学习势函数与第一性原理计算结合的缺陷能级预测方法研究'):
                assert not app._add_research_topic(topic),app._add_research_topic(topic)
            app._refresh_research();app.root.update()
            board=app._research_keywords
            limit=app._research_chip_width()
            assert limit>200,limit
            chips=[w for w in board.winfo_children() if isinstance(w,tk.Frame)]
            assert len(chips)>=2,[c.winfo_x() for c in chips]
            assert all(c.winfo_x()+c.winfo_width()<=limit+2 for c in chips),\
                [(c.winfo_x(),c.winfo_width(),limit) for c in chips]
            assert len({c.winfo_y() for c in chips})>=2,[c.winfo_y() for c in chips]   # 确实换了行
            # 聊天里问「最新进展」：先汇报手上的方向
            said=[]
            original_say=app.say
            app.say=lambda text,**kwargs:said.append(text) or True
            routed=[]
            original_report=app._report_research
            app._report_research=lambda question='':routed.append(question)
            try:
                app._route_intent({'action':'research'},'最新进展',app._conv_id)
                assert routed==['最新进展'],routed
                del app._report_research          # 还原成类里的实现
                app._report_research('最新进展')
            finally:
                app.say=original_say
                app._report_research=original_report
            assert said and '方向' in said[0],said
            # 论文网页：判定与讲解资料（离线只查路由和提示词，不联网）
            import paper_reader
            assert paper_reader.looks_like_paper('https://arxiv.org/abs/2310.06825')
            assert not paper_reader.looks_like_paper('https://example.com/x')
            assert pet._clip_route('https://doi.org/10.1038/s41586-021-03819-2')=='paper'
            prompt=app._paper_explain_prompt({'title':'Synthetic paper','abstract':'Fixture abstract'})
            assert 'Synthetic paper' in prompt and '不要念网址' in prompt
            paper_prompt=app._paper_explain_prompt({'title':'T','text':'body excerpt'})
            assert '正文摘录' in paper_prompt
            app._research_check(force=True)   # 没有 API Key：只提示，不联网
            assert not getattr(app,'_research_running',False)
            checks.append('Research keyword input, persistence and notice formatting')
            # 双端共享/同步记忆整体收起来了：开关为假、运行时拿不到传输、两个入口只回一句「开发中」。
            # 这里刻意不建菜单窗（show_menu 会留下 after 轮询，和下面「检查更新」那项互相干扰，
            # 之前就是它偶发让离线验收挂在 _add_menu_update 的回调上）；菜单文案由单测覆盖。
            import sync_runtime, assistant_features
            assert sync_runtime.SYNC_ENABLED is False
            assert sync_runtime.get_runtime(pet.DATA_DIR) is None
            spoken=[]
            original_say=app.say
            app.say=lambda text,**kwargs:spoken.append(text)
            try:
                app.show_sync();app.sync_now()
            finally:
                app.say=original_say
            assert spoken==[assistant_features.SYNC_WIP_REPLY]*2,spoken
            checks.append('Sync sharing entries stay parked as in-development')
            import news, updater, weather, weather_features, update_features
            assert weather._wmo_zh(0)=='晴' and updater.version_tuple('0.10.0')>updater.version_tuple('0.9.9')
            assert isinstance(updater.read_announcement(pet.APP_VERSION),str)
            menu=tk.Toplevel(app.root);app._menu_marks={};app._submenus=[]
            app._add_menu_update(menu);app.root.update()
            assert '检查更新' in app._update_mark.master.winfo_children()[0].cget('text')
            menu.destroy()
            routed=[]
            app._weather_worker=lambda *a,**k:routed.append('weather')
            app._news_worker=lambda *a,**k:routed.append('news')
            app._route_intent({'action':'weather'},'今天天气怎么样',app._conv_id)
            app._route_intent({'action':'news'},'讲个新闻',app._conv_id)
            time.sleep(0.3)
            assert routed==['weather','news'],routed
            checks.append('Weather/news/update modules load offline and route to their workers')
            from openai import OpenAI
            OpenAI(api_key='offline-fixture',base_url='http://127.0.0.1:1').close()
            checks.append('Bundled API client loads offline')
            assert not errors,errors
        finally:
            for timer in app.root.tk.call('after','info'):app.root.tk.call('after','cancel',timer)
            app.root.destroy()
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({'version':pet.APP_VERSION,'frozen':bool(getattr(sys,'frozen',False)),'checks':checks,'errors':errors},ensure_ascii=False,indent=2),'utf-8')
    return 0
