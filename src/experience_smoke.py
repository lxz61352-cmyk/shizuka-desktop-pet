"""App-owned GUI acceptance in the release self-test's disposable data root."""
import json,time
from pathlib import Path
from unittest.mock import patch
from tkinter import ttk


def run(app,pet):
    checks=[]
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    app.show_settings_center();app.root.update()
    win=app._settings_center
    book=next(w for w in widgets(win) if isinstance(w,ttk.Notebook))
    assert len(book.tabs())==5
    for tab in book.tabs():
        book.select(tab);app.root.update()
        frame=book.nametowidget(tab)
        for child in frame.winfo_children():
            if child.winfo_ismapped():
                assert child.winfo_rooty()+child.winfo_height()<=win.winfo_rooty()+win.winfo_height(),child
    from proactive_chat import state
    assert not state(app._weixin_store.data)['enabled']
    win.destroy();checks.append('Settings center: five groups fit; WeChat proactive remains opt-in')

    app.open_chat_input(prefill='未发送的草稿');app.root.update();app.save_chat_and_close()
    assert json.loads((Path(pet.DATA_DIR)/'chat-draft.json').read_text('utf-8'))['text']=='未发送的草稿'
    app.open_chat_input();app.root.update();assert app._chat_entry.get()=='未发送的草稿'
    app.close_chat_win();checks.append('Composer draft survives close and is persisted locally')

    from dialogue_feedback import capture,FeedbackStore
    with patch.object(pet,'api_model',return_value='offline'):
        trace=capture(app,'desktop',[{'role':'system','content':'离线角色及相关记忆'},
                                     {'role':'user','content':'虚构消息'}])
    app._log_chat('assistant','虚构回复，用于界面验证。')
    row=app._chat_log[-1];assert row['trace_id']==trace
    app.show_reply_feedback(row);app.root.update()
    save=next(w for w in widgets(app._feedback_editor) if isinstance(w,ttk.Button) and w.cget('text')=='保存标记')
    save.invoke();app.root.update()
    feedback=FeedbackStore(pet.DATA_DIR).rows();assert feedback[-1]['trace']['id']==trace
    app.show_feedback();app.root.update()
    table=next(w for w in widgets(app._feedback_window) if isinstance(w,ttk.Treeview))
    table.selection_set(table.get_children()[-1]);app.root.update()
    app._feedback_window.destroy();checks.append('Reply feedback stores the actual request trace and previews selected export')

    mem=pet.get_memory();mem.add('用户今天在复习');mem.save()
    app.show_memory();app.root.update();app.show_memory_details(mem.items[0]['id']);app.root.update()
    app._memory_details.destroy();app._close_memory_window()
    app.show_backup();app.root.update();app._backup_window.destroy()
    app.show_runtime_status();app.root.update();app._runtime_window.destroy()
    checks.append('Memory applicability/source, backup/restore and runtime-status panels open')

    with patch.object(app,'say',return_value=True):
        app._pomo_start('focus');app.root.update()
        assert not app.visible and app._pomo_phase=='focus'
        assert app._pomo_float is not None and app._pomo_float.attributes('-topmost')
        app._pomo_stop();app.root.update()
    checks.append('Focus Pomodoro folds the pet while the timer remains topmost')
    return checks
