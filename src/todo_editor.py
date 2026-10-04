"""Compact title/note editor with explicit event, advance and recurrence controls."""
from copy import deepcopy
from datetime import datetime,timedelta
import time,tkinter as tk
from tkinter import ttk,messagebox
from tkinter.scrolledtext import ScrolledText
from todo_model import CATEGORIES
from todo_schedule import rule_label
from ui_theme import apply,copy_bindings,page_header
from window_opening import dialog_window

REPEATS=('不重复','每天','每周','每月','工作日','每天直到完成')

class TodoEditorMixin:
    def _todo_open_editor(self,item=None):
        from qt_window_bridge import open_editor
        if open_editor(self,item):return
        old=getattr(self,'_todo_editor_win',None)
        if old is not None and old.winfo_exists():self._move_dialog(old,640,740);return
        self._todo_init();parent=self._todo_win or self.root
        win=self._todo_editor_win=dialog_window(parent);win.transient(parent);win.attributes('-topmost',True)
        win.title('编辑待办' if item else '新建待办');win.minsize(600,680);self._place_dialog(win,640,740)
        page_header(win,'编辑待办' if item else '新建待办').pack(fill='x')
        options=self._todo_options(item) if item else {'category':'生活','desktop':True,'weixin':True}
        schedule=options.get('schedule',{});rule=schedule.get('rule');body=ttk.Frame(win,padding=(22,0,22,18));body.pack(fill='both',expand=True)
        def row():
            frame=ttk.Frame(body);frame.pack(fill='x',pady=7);return frame
        ttk.Label(body,text='标题').pack(anchor='w')
        content=tk.Text(body,height=2,wrap='word');content.pack(fill='x',pady=(4,10));copy_bindings(content)
        if item:content.insert('1.0',item['text'])
        ttk.Label(body,text='备注').pack(anchor='w')
        notes=ScrolledText(body,height=3,wrap='word');notes.pack(fill='x',pady=(4,8));copy_bindings(notes)
        notes.insert('1.0',options.get('manual_note',''))
        group=tk.StringVar(value=options.get('category','生活'));repeat=tk.StringVar(value='不重复')
        if rule:repeat.set('每天直到完成' if rule.get('until_done') else '工作日' if rule.get('weekdays')==list(range(5)) else {'daily':'每天','weekly':'每周','monthly':'每月'}[rule['frequency']])
        frame=row();ttk.Label(frame,text='用途').pack(side='left');ttk.Combobox(frame,textvariable=group,values=CATEGORIES,state='readonly',width=10).pack(side='left',padx=(10,20))
        ttk.Label(frame,text='重复').pack(side='left');ttk.Combobox(frame,textvariable=repeat,values=REPEATS,state='readonly',width=16).pack(side='left',padx=10)
        mode=tk.StringVar(value='下次启动' if item and item.get('on_boot') else '指定时间' if item and item.get('due') else '未安排时间')
        frame=row();ttk.Label(frame,text='事项时间').pack(side='left');ttk.Combobox(frame,textvariable=mode,values=('未安排时间','指定时间','下次启动'),state='readonly',width=18).pack(side='left',padx=10)
        initial_event=schedule.get('event_at') or (item or {}).get('due')
        dt=datetime.fromtimestamp(initial_event) if initial_event else datetime.now()+timedelta(hours=1)
        date=tk.StringVar(value=dt.strftime('%Y-%m-%d'));hour=tk.StringVar(value=dt.strftime('%H'));minute=tk.StringVar(value=dt.strftime('%M'))
        initial_time=(date.get(),hour.get(),minute.get())
        frame=row();date_box=ttk.Entry(frame,textvariable=date,width=13);date_box.pack(side='left')
        choose=ttk.Button(frame,text='选日期',command=lambda:self._todo_calendar(win,date));choose.pack(side='left',padx=8)
        hours=ttk.Spinbox(frame,from_=0,to=23,textvariable=hour,width=3,format='%02.0f');hours.pack(side='left')
        ttk.Label(frame,text=' : ').pack(side='left');minutes=ttk.Spinbox(frame,from_=0,to=59,textvariable=minute,width=3,format='%02.0f');minutes.pack(side='left')
        lead=tk.StringVar(value=str(schedule.get('lead_minutes',0)));interval=tk.StringVar(value=str((rule or {}).get('interval',1)))
        frame=row();ttk.Label(frame,text='提前').pack(side='left');lead_box=ttk.Spinbox(frame,from_=0,to=43200,textvariable=lead,width=6);lead_box.pack(side='left',padx=8)
        ttk.Label(frame,text='分钟提醒').pack(side='left');ttk.Label(frame,text='周期间隔').pack(side='left',padx=(24,8))
        interval_box=ttk.Spinbox(frame,from_=1,to=366,textvariable=interval,width=4);interval_box.pack(side='left')
        def change(*args):
            enabled=mode.get()=='指定时间'
            for widget in (date_box,choose,hours,minutes,lead_box):widget.configure(state='normal' if enabled else 'disabled')
            interval_box.configure(state='normal' if repeat.get() in ('每天','每周','每月') else 'disabled')
        def change_repeat(*args):
            if repeat.get()!='不重复':
                mode.set('指定时间')
                if repeat.get()=='每天直到完成':hour.set('09');minute.set('00');lead.set('0');interval.set('1')
            change()
        mode.trace_add('write',change);repeat.trace_add('write',change_repeat);change()
        def quick(delta):
            target=datetime.now()+timedelta(minutes=delta);mode.set('指定时间');date.set(target.strftime('%Y-%m-%d'));hour.set(target.strftime('%H'));minute.set(target.strftime('%M'));lead.set('0')
        frame=row();ttk.Button(frame,text='30分钟后',command=lambda:quick(30)).pack(side='left');ttk.Button(frame,text='1小时后',command=lambda:quick(60)).pack(side='left',padx=8)
        desktop=tk.BooleanVar(value=options.get('desktop',True));weixin=tk.BooleanVar(value=options.get('weixin',True))
        frame=row();ttk.Checkbutton(frame,text='桌面提醒',variable=desktop).pack(side='left');ttk.Checkbutton(frame,text='微信提醒',variable=weixin).pack(side='left',padx=18)
        if options.get('time_hint'):ttk.Label(body,text=options['time_hint'],wraplength=560).pack(anchor='w')
        def save():
            title=content.get('1.0','end-1c').strip();note=notes.get('1.0','end-1c').strip()
            if not title or len(title)>1000 or len(note)>4000:return messagebox.showerror('未保存','请填写标题；标题最多1000字，备注最多4000字。',parent=win)
            try:
                from todo_editing import save_editor
                values=dict(title=title,note=note,category=group.get(),repeat=repeat.get(),mode=mode.get(),
                    date=date.get(),hour=hour.get(),minute=minute.get(),lead=lead.get(),interval=interval.get(),
                    desktop=desktop.get(),weixin=weixin.get())
                record=save_editor(self,values,item['id'] if item else '',
                    dict(zip(('date','hour','minute'),initial_time)))
                if getattr(self,'_todo_win',None):
                    name='已完成' if record.get('done') else group.get()
                    self._todo_notebook.select((*CATEGORIES,'已完成').index(name))
                    tree=self._todo_trees[name];tree.selection_set(record['id']);tree.see(record['id'])
            except Exception as exc:return messagebox.showerror('未保存',str(exc),parent=win)
            win.destroy();self._todo_editor_win=None
        buttons=ttk.Frame(body);buttons.pack(side='bottom',fill='x',pady=8)
        ttk.Button(buttons,text='保存',command=save).pack(side='right');ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=8)
        self._todo_editor_controls={'content':content,'notes':notes,'category':group,'mode':mode,'date':date,'hour':hour,'minute':minute,
            'lead':lead,'repeat':repeat,'interval':interval,'desktop':desktop,'weixin':weixin,'save':save}
        apply(win);content.focus_set()
