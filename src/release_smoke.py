"""Offline acceptance in a disposable data directory; no real credentials or messages."""
from pathlib import Path
from unittest.mock import patch
import json,sys,time

def run(pet):
    checks=[];errors=[]
    report=Path(sys.argv[sys.argv.index('--report')+1])
    with patch.object(pet,'read_api_key',return_value=''),patch.object(pet,'_embed_texts',return_value=None),patch.object(pet.DeskPet,'_migrate_api_key'):
        app=pet.DeskPet()
        app.root.report_callback_exception=lambda *args:errors.append(str(args[1]))
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
            menu.destroy()
            checks.append('Compact settings, five-minute default and notification sound policy')
            app.show_research();app.root.update()
            app._research_init()
            assert not app._research.profile['queries']
            row={'title':'Synthetic paper','journal':'Fixture Journal','url':'https://example.invalid/paper',
                 'evidence_basis':'title','comment':'可以进一步阅读。','reason':'相关。'}
            text=app._research_notice(row);assert 'Fixture Journal' in text and '题名信息' in text
            import assistant_features
            assert assistant_features.RESEARCH_ENABLED is False
            app._research_check(force=True)
            assert not getattr(app,'_research_running',False)
            checks.append('Research code stays inert while the feature is disabled')
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
