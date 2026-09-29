"""GUI acceptance on the release runner's disposable profile; no messages sent."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time,tkinter as tk
from tkinter import ttk
from PIL import Image


def run(app,pet):
    checks=[]
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    def click(win,label):
        target=next(w for w in widgets(win) if isinstance(w,(tk.Button,ttk.Button)) and w.cget('text')==label)
        target.invoke();app.root.update()
    def wait(predicate,seconds=12):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            # run() starts this dispatcher normally; the isolated self-test does not run().
            while not app._ui_q.empty():app._ui_q.get_nowait()()
            app.root.update();time.sleep(.02)
        assert predicate(),'GUI worker did not finish'
    root=Path(pet.DATA_DIR)
    app._record_notice('Synthetic reminder','待办提醒',key='gui-fixture',todo_id='gui-todo')
    app.show_chat_log(mode='通知');app.root.update()
    row=next(r for r in app._chatlog_text.rows if r.get('key')=='gui-fixture')
    hit=next((a,b) for a,b,r in app._chatlog_text.hit_rows if r['id']==row['id'])
    app._chatlog_text.open_row(SimpleNamespace(y=(hit[0]+hit[1])/2-app._chatlog_text.canvasy(0)))
    app.root.update();assert app._workflow().notices()[-1]['read']
    app._notice_detail.destroy()
    app._log_chat('user','context fixture previous',kind='user')
    app._log_chat('assistant','needle for search',kind='reply');anchor=app._chat_log[-1]
    app._log_chat('user','context fixture next',kind='user')
    app.show_chat_log(mode='对话');app.root.update()
    field=next(w for w in widgets(app._chatlog_win) if type(w) is ttk.Entry)
    field.insert(0,'needle for search');app._chatlog_refresh();app.root.update()
    assert len(app._chatlog_text.rows)==1
    app._chatlog_text.on_context(anchor);app.root.update()
    from art_transcript import ArtTranscript
    context=next(w for w in widgets(app._chat_context_win) if isinstance(w,ArtTranscript))
    assert any(r['text']=='context fixture previous' for r in context.rows)
    assert any(r['text']=='context fixture next' for r in context.rows)
    app._chat_context_win.destroy();app._close_chat_log()
    checks.append('History search expands real same-channel neighbors; notification opens and persists read status')

    from experience_settings import load
    assert load(pet.DATA_DIR)['startup_missed'] is False
    app.show_settings_center();app.root.update()
    toggle=next(w for w in widgets(app._settings_center) if isinstance(w,ttk.Checkbutton) and '错过' in w.cget('text'))
    toggle.invoke();assert load(pet.DATA_DIR)['startup_missed'] is True
    toggle.invoke();assert load(pet.DATA_DIR)['startup_missed'] is False
    app._settings_center.destroy()
    checks.append('Missed-item startup list defaults off and its independent switch persists both ways')

    item=dict(id='gui-todo',text='Synthetic task',done=False,on_boot=False,due=time.time()+3600,created=time.time())
    app.todos.append(item);app._todo_options(item).update(weixin=False,desktop=False)
    original_due=item['due']
    app.show_todo_quick('gui-todo');app.root.update();click(app._todo_quick_win,'10分钟后提醒')
    assert item['due']==original_due and app._todo_effective_due(item)<original_due
    app._todo_quick_win.destroy()
    with patch.object(app,'say',return_value=True),patch.object(app,'_pomo_game_running',return_value=False):
        app._pomo_task_start('gui-todo');app.root.update()
        assert not app.visible and app._pomo_float.attributes('-topmost')
        app._pomo_end_at-=120;app._pomo_checkpoint()
        remaining=app._workflow().data['focus']['remaining']
        app._pomo_cancel_tick();app._pomo_phase=None;app._pomo_float_hide()
        app._pomo_offer_recovery();app.root.update();click(app._pomo_recovery,'继续剩余时间')
        assert abs(app._pomo_left()-remaining)<2
        app._pomo_stop();app.root.update()
        assert 119<=app._workflow().total('gui-todo')<=125 and not item['done']
        app._pomo_task_start('gui-todo');app._pomo_end_at=time.monotonic();app._pomo_tick()
        wait(lambda:getattr(app,'_pomo_completed',None) is not None)
        assert not item['done'] and app._pomo_phase=='break'
        click(app._pomo_completed,'完成关联事项');assert item['done']
        app._pomo_stop()
    checks.append('Todo snooze preserves schedule; linked focus stays folded/topmost, recovers remaining time, and completes its task only on click')

    app.restore();app.open_chat_input(prefill='Keep my question');app.root.update()
    atts=app._chat_attachment_draft
    with patch('attachment_ui.ImageGrab.grabclipboard',return_value=Image.new('RGB',(120,160),'blue')):
        app.paste_attachment(atts,lambda:None)
    assert len(atts)==1;app._remember_attachments(atts)
    app.manage_attachments(atts,lambda:None);app.root.update()
    book=next(w for w in widgets(app._material_manager) if isinstance(w,ttk.Notebook))
    recent=book.nametowidget(book.tabs()[1]);book.select(recent)
    saved=next(w for w in widgets(recent) if isinstance(w,tk.Listbox));saved.selection_set(0)
    click(app._material_manager,'加入本轮');assert len(atts)==2
    click(app._material_manager,'返回聊天')
    task=next(w for w in widgets(app._chat_win) if isinstance(w,ttk.Combobox))
    task.set('提取文字');task.event_generate('<<ComboboxSelected>>');app.root.update()
    assert app._chat_entry.get().startswith('Keep my question') and '提取文字' in app._chat_entry.get()
    pdf=root/'fixture.pdf';Image.new('RGB',(180,240),'red').save(pdf)
    app._pick_pdf_pages(str(pdf),atts,lambda:None)
    wait(lambda:any(isinstance(w,ttk.Label) and str(w.cget('image')) for w in widgets(app._pdf_picker)))
    click(app._pdf_picker,'加入所选页面');wait(lambda:app._pdf_picker is None)
    assert len(atts)==3 and '第1页' in atts[-1]['name']
    app.close_chat_win();app.open_chat_input();app.root.update()
    assert len(app._chat_attachment_draft)==3
    # Native layout bounds, including a fully populated toolbar and preview chips.
    win=app._chat_win
    for widget in widgets(win):
        if isinstance(widget,tk.Button) and widget.winfo_ismapped():
            assert widget.winfo_rootx()+widget.winfo_width()<=win.winfo_rootx()+win.winfo_width(),widget.cget('text')
    from attachment_files import message_content
    payload=message_content(app._chat_entry.get(),atts)
    assert sum(b['type']=='image_url' for b in payload)==3
    atts.clear();app.close_chat_win()
    checks.append('Paste, material reuse, non-destructive action picker and PDF preview/select run with packaged renderer; toolbar stays bounded')
    return checks
