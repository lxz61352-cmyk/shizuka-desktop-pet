"""Offline acceptance across real normal dialogs and pending resize workers."""
from concurrent.futures import Future
import time
import tkinter as tk
from tkinter import font as tkfont
from unittest.mock import patch
import window_art
from window_opening import MAX_PREPARE_SECONDS,FADE_SECONDS


def run(app,pet):
    checks=[]
    def pump(seconds=.02):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:app.root.update();time.sleep(.002)
    def settled(win):
        deadline=time.monotonic()+MAX_PREPARE_SECONDS+FADE_SECONDS+1
        while time.monotonic()<deadline:
            pump()
            art=getattr(win,'_art_backdrop',None)
            if art and not getattr(win,'_opening_pending',False) and art.ready():break
        if getattr(win,'_opening_result',None)!='ready':
            import json
            from pathlib import Path
            import sys
            report=Path(sys.argv[sys.argv.index('--report')+1]).parent/'background-diagnostic.json'
            report.write_text(json.dumps(dict(title=win.title(),result=getattr(win,'_opening_result',None),
                opening_ms=getattr(win,'_opening_ms',None),debug=getattr(win,'_opening_debug',None),diffs=getattr(win,'_opening_diffs',None),ready=art.ready() if art else None,
                pending=art.pending if art else None,resize_pending=art.resize_pending if art else None,
                size=art.size if art else None,window_size=(win.winfo_width(),win.winfo_height()),
                signature_matches=art.signature==art.layout_signature() if art else None,
                child_jobs=[dict(kind=row[0].winfo_class(),pending=str(getattr(row[0],'pending',None)),
                    layout=str(getattr(row[0],'_layout_job',None)),reflow=str(getattr(row[0],'_reflow_pending',None)))
                    for row in art.layout_signature() if hasattr(row[0],'set_backdrop')] if art else []),
                ensure_ascii=False,indent=2),encoding='utf-8')
        assert win._opening_result=='ready',(win.title(),getattr(win,'_opening_result',None))
        assert art.ready(),win.title()
        assert isinstance(art.canvas,tk.Canvas),win.title()
        assert art.image.size==(win.winfo_width(),win.winfo_height()),win.title()
        assert float(win.attributes('-alpha'))==1,win.title()
        return art
    # All of these use disposable data and only open local views.
    for show,name in ((app.show_chat_log,'_chatlog_win'),(app.show_todos,'_todo_win'),
        (app.show_computer_assistant,'_computer_win'),(app.show_weixin,'_weixin_win'),
        (app.show_memory,'_mem_win'),(app.show_usage,'_usage_win'),
        (app.show_pomodoro_settings,'_pomo_settings_win'),(app.show_settings_center,'_settings_center'),
        (app.show_backup,'_backup_window'),(app.show_runtime_status,'_runtime_window'),
        (app.show_feedback,'_feedback_window')):
        show();settled(getattr(app,name))
    previous=set(app._todo_win.winfo_children())
    app._todo_calendar(app._todo_win,tk.StringVar(app.root,value='2026-10-03'))
    calendar=next(win for win in app._todo_win.winfo_children() if win not in previous and isinstance(win,tk.Toplevel))
    settled(calendar);calendar.destroy()
    checks.append('Twelve actual normal dialogs, including date picker, share transcript canvas backgrounds and settled first frames')
    app._todo_open_editor()
    editor=app._todo_editor_win;settled(editor)
    def text_boxes(parent):
        for child in parent.winfo_children():
            if isinstance(child,tk.Text):yield child
            yield from text_boxes(child)
    boxes=list(text_boxes(editor))
    assert len(boxes)==2
    for box in boxes:
        assert box._glass_text_parameters[2]==1,box
        assert tkfont.Font(root=box,font=box.cget('font')).actual()['weight']=='bold'
        box.insert('1.0','透明输入框编辑检查')
        assert box.get('1.0','end-1c')=='透明输入框编辑检查'
    editor.destroy();app._todo_editor_win=None
    checks.append('Actual new-todo title and note editors have transparent backgrounds, opaque bold text and editable native contents')
    for win in (app._chatlog_win,app._todo_win,app._computer_win,app._weixin_win,app._settings_center):
        art=settled(win);original=win.winfo_geometry()
        waiting=Future()
        with patch.object(window_art._WORKER,'submit',return_value=waiting):
            win.geometry(f'{win.winfo_width()+91}x{win.winfo_height()+39}+70+70');pump(.06)
            assert art.image.size==(win.winfo_width(),win.winfo_height()),win.title()
            signature=art.layout_signature()
            for row in signature:
                widget=row[0]
                if min(row[3:5])<3:continue
                assert getattr(widget,'_backdrop_source',None) is art.image,(win.title(),str(widget))
            if not waiting.done():waiting.set_result(window_art._prepare(art.request))
            pump(.08)
        win.geometry(original);pump(.1);settled(win)
    checks.append('History, todo, computer, WeChat and settings keep child crops in the same frame while high-quality resize work is pending')
    for name in ('_settings_center','_backup_window','_runtime_window','_feedback_window'):
        win=getattr(app,name,None)
        if win and win.winfo_exists():win.destroy()
    return checks
