"""Compact title/note editor with explicit event, advance and recurrence controls."""
from copy import deepcopy
from datetime import datetime,timedelta
import time,tkinter as tk
from tkinter import ttk,messagebox
from tkinter.scrolledtext import ScrolledText
from todo_model import CATEGORIES
from todo_schedule import rule_label
from ui_theme import apply,copy_bindings

REPEATS=('不重复','每天','每周','每月','工作日','每天直到完成')

class TodoEditorMixin:
    def _todo_open_editor(self,item=None):
        old=getattr(self,'_todo_editor_win',None)
        if old is not None and old.winfo_exists():old.lift();return
        self._todo_init();parent=self._todo_win or self.root
        win=self._todo_editor_win=tk.Toplevel(parent);win.transient(parent);win.attributes('-topmost',True)
        win.title('编辑待办' if item else '新建待办');win.geometry('640x740');win.minsize(600,680)
        options=self._todo_options(item) if item else {'category':'生活','desktop':True,'weixin':True}
        schedule=options.get('schedule',{});rule=schedule.get('rule');body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
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
            due=None;event=None;new_rule=None;boot=mode.get()=='下次启动';now=time.time()
            try:
                advance=int(lead.get()) if mode.get()=='指定时间' else 0
                if not 0<=advance<=43200:raise ValueError('提前量应在0至43200分钟之间')
                if mode.get()=='指定时间':
                    event=datetime.strptime(f'{date.get()} {int(hour.get()):02d}:{int(minute.get()):02d}','%Y-%m-%d %H:%M')
                    if item and initial_event and initial_time==(date.get(),hour.get(),minute.get()):event=datetime.fromtimestamp(initial_event)
                    if repeat.get()!='不重复':
                        every=int(interval.get()) if repeat.get() in ('每天','每周','每月') else 1
                        if not 1<=every<=366:raise ValueError('周期间隔应在1至366之间')
                        new_rule={'frequency':{'每天':'daily','每周':'weekly','每月':'monthly','工作日':'weekly','每天直到完成':'daily'}[repeat.get()],
                            'interval':every,'weekdays':list(range(5)) if repeat.get()=='工作日' else [event.weekday()],
                            'month_day':event.day,'hour':event.hour,'minute':event.minute,'anchor_date':event.date().isoformat(),'until_done':repeat.get()=='每天直到完成'}
                        # Preserve multi-day weekly rules and monthly end-day anchor on a note-only edit.
                        if rule and repeat.get()==('每天直到完成' if rule.get('until_done') else '工作日' if rule.get('weekdays')==list(range(5)) else {'daily':'每天','weekly':'每周','monthly':'每月'}[rule['frequency']]) and initial_time==(date.get(),hour.get(),minute.get()):
                            new_rule={**deepcopy(rule),'interval':every}
                    due=event.timestamp()-advance*60
                    unchanged=item and initial_event==event.timestamp() and advance==schedule.get('lead_minutes',0)
                    if event.timestamp()<=now and not unchanged:
                        if new_rule:
                            from todo_schedule import occurrence
                            event=occurrence(new_rule,datetime.fromtimestamp(now+advance*60));due=event.timestamp()-advance*60
                        else:raise ValueError('请选择未来的事项时间')
                    if not unchanged:due=max(now,due)
                    elif item:due=item.get('due')
                elif repeat.get()!='不重复':raise ValueError('周期事项需要指定时间')
                new_schedule={'version':1,'event_at':event.timestamp() if event else None,'lead_minutes':advance,'lead_reason':'editor','rule':new_rule,'reminder_at':due}
                if item:
                    record=next((row for row in self.todos if row['id']==item['id']),None)
                    if record is None:raise ValueError('这件事已被删除')
                    old_options=deepcopy(self._todo_options(record));old_title=record['text']
                    rescheduled=(record.get('due'),record.get('on_boot'),old_options.get('schedule',{}).get('rule'))!=(due,boot,new_rule)
                    record.update(text=title,due=due,on_boot=boot);self._save_todos()
                else:
                    record=self.add_todo(title,due_ts=due,on_boot=boot);rescheduled=True;old_options={};old_title=''
                opts=self._todo_options(record)
                if old_options.get('schedule',{}).get('rule') and not new_rule:self._todo_queue_routine(record,'停止重复')
                opts.update(category=group.get(),manual_note=note,desktop=desktop.get(),weixin=weixin.get(),time_hint='')
                self._todo_install_schedule(record,opts,new_schedule)
                if rescheduled or old_title!=title or old_options.get('manual_note','')!=note:
                    opts['source_text']=title+('；'+note if note else '')+('；'+rule_label(new_rule) if new_rule else '')
                    opts['source_id']='editor-'+record['id']+'-'+str(int(now*1000))
                    self._todo_queue_routine(record,'调整' if item else '建立')
                if rescheduled:opts.pop('notice',None)
                self._save_todo_details();self._refresh_todo_view();self._todo_start_memory_review()
                if getattr(self,'_todo_win',None):
                    name='已完成' if record.get('done') else group.get();self._todo_notebook.select((*CATEGORIES,'已完成').index(name))
                    tree=self._todo_trees[name];tree.selection_set(record['id']);tree.see(record['id'])
            except Exception as exc:return messagebox.showerror('未保存',str(exc),parent=win)
            self._activity_saved_until=time.monotonic()+3
            win.destroy();self._todo_editor_win=None
        buttons=ttk.Frame(body);buttons.pack(side='bottom',fill='x',pady=8)
        ttk.Button(buttons,text='保存',command=save).pack(side='right');ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=8)
        self._todo_editor_controls={'content':content,'notes':notes,'category':group,'mode':mode,'date':date,'hour':hour,'minute':minute,
            'lead':lead,'repeat':repeat,'interval':interval,'desktop':desktop,'weixin':weixin,'save':save}
        apply(win);content.focus_set()
