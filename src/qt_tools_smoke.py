"""Exercise the actual main-menu routes against a disposable data owner."""
import ctypes,json,os,socket,sys,time,traceback
from pathlib import Path
from unittest.mock import patch

def run(pet):
    report=Path(sys.argv[sys.argv.index('--report')+1]);checks=[];errors=[];app=None;bridge=None
    os.environ['SHIZUKA_WINDOW_BACKEND']='qt'
    def wait(predicate):
        deadline=time.monotonic()+20
        while not predicate():
            app.root.update();time.sleep(.02)
            if time.monotonic()>deadline:raise AssertionError('Qt pipe/render timeout')
    with patch.object(pet,'read_api_key',return_value=''),patch.object(pet,'_embed_texts',return_value=None),\
         patch.object(pet.DeskPet,'_migrate_api_key'),patch.object(pet.DeskPet,'_todo_start_memory_review'),\
         patch.object(pet.DeskPet,'_todo_check_reminders'),patch.object(socket.socket,'connect',side_effect=AssertionError('Offline fixture')),\
         patch.object(ctypes.windll.user32,'GetAsyncKeyState',return_value=0):
        try:
            app=pet.DeskPet();app.root.report_callback_exception=lambda *args:errors.append(''.join(traceback.format_exception(*args)))
            app.root.update();app._motion.reset();app._ground.cancel()
            app._log_chat('user','虚构聊天记录，用来测试新的真实入口。',kind='user')
            app._log_chat('assistant','虚构回复。',kind='chat')
            app.show_chat_log();app.show_todos();bridge=app._qt_windows
            wait(lambda:bridge.ready and {'history','todos'}<=bridge.presented)
            assert getattr(app,'_chatlog_win',None) is None and getattr(app,'_todo_win',None) is None
            assert bridge.backend=='Direct3D11';checks.append('Actual history/todo menu routes present Qt frames through private pipes')
            pid=bridge.process.pid;app.show_chat_log();app.show_todos();assert app._qt_windows is bridge and bridge.process.pid==pid
            checks.append('Repeated menu entries reuse one warm renderer')
            app._todo_open_editor();wait(lambda:'editor' in bridge.presented)
            session=next(iter(bridge.sessions));values=dict(bridge.sessions[session]['initial'])
            values.update(title='虚构事项',note='虚构备注',category='研究',desktop=False,weixin=False)
            saved=bridge.action('save',dict(session=session,values=values));record=next(r for r in app.todos if r['id']==saved['id'])
            core=json.loads(Path(pet.TODO_FILE).read_text('utf-8'))
            assert any(r['id']==record['id'] for r in core['items'])
            assert app._todo_options(record)['manual_note']=='虚构备注'
            checks.append('Qt editor route uses main application persistence and original todo schema')
            bridge.send_editor(record['id']);session=next(iter(bridge.sessions));values=dict(bridge.sessions[session]['initial']);values['note']='第二份虚构备注'
            bridge.action('save',dict(session=session,values=values))
            details=json.loads(app._todo_details_path.read_text('utf-8'))
            assert details['items'][record['id']]['manual_note']=='第二份虚构备注'
            assert len(app.todos)==1;checks.append('Existing todo edits preserve identity and extension data')
            bridge.action('context',dict(id=app._chat_log[0]['id']));wait(lambda:'context' in bridge.presented)
            checks.append('Same-channel history context presents a Qt window')
            assert not errors and not bridge.errors,(errors,bridge.errors)
        except Exception:errors.append(traceback.format_exc())
        finally:
            if app:
                app._closing=True;app.root.destroy()
            if bridge:
                try:bridge.process.wait(timeout=4)
                except Exception:errors.append('Renderer did not stop after main-window destruction')
                if bridge.process.poll() is not None:checks.append('Main shutdown closes the private renderer')
    result=dict(frozen=bool(getattr(sys,'frozen',False)),checks=checks,errors=errors,backend=bridge.backend if bridge else None)
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if sys.stdout:print(json.dumps(dict(checks=len(checks),errors=len(errors))),flush=True)
    return 1 if errors else 0
