"""Shared inbox, conversation context, and focus-to-task actions."""
from copy import deepcopy
import time,tkinter as tk
from tkinter import ttk,messagebox
from ui_theme import apply,PAGE_X


class WorkflowMixin:
    def _workflow(self):
        if not hasattr(self,'_workflow_store'):
            from workflow_store import WorkflowStore
            import pet
            self._workflow_store=WorkflowStore(pet.DATA_DIR)
        return self._workflow_store

    def _record_notice(self,text,source,**kwargs):
        self._workflow().notice(text,source,**kwargs)

    def _workflow_boot(self):
        self._pomo_offer_recovery()
        if getattr(self,'_experience',{}).get('startup_missed',False):
            missed=[r for r in self.todos if not r.get('done') and r.get('due') and r['due']<time.time()-600]
            for row in missed:
                self._record_notice(row['text']+'：原定提醒时间 '+time.strftime('%m-%d %H:%M',time.localtime(row['due']))+
                                    '，记录尚未标完成；是否已处理由你确认。','错过的事项',
                                    key='missed:'+row['id']+':'+str(row['due']),todo_id=row['id'])
            if missed:self.show_chat_log(mode='通知')

    def show_chat_context(self,row):
        from art_transcript import ArtTranscript
        from workflow_store import surrounding
        previous=getattr(self,'_chat_context_win',None)
        if previous is not None and previous.winfo_exists():previous.destroy()
        win=self._experience_window('_chat_context_win','对话前后文',820,640)
        if win is None:return
        hint=tk.StringVar();ttk.Label(win,textvariable=hint,wraplength=740).pack(fill='x',padx=PAGE_X)
        body=ttk.Frame(win);body.pack(fill='both',expand=True,padx=PAGE_X,pady=10)
        box=ArtTranscript(body);bar=ttk.Scrollbar(body,command=box.yview);box.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');box.pack(fill='both',expand=True);box.on_feedback=self.show_reply_feedback
        count=[6,6]
        def refresh():
            with self._chat_lock:rows=list(self._chat_log)
            found,older,newer=surrounding(rows,row['id'],*count)
            box.set_rows(found);box.focus_row(row['id'])
            hint.set('已定位选中消息；仅显示同一渠道。时间以每条记录为准。' if found else '原记录已不存在。')
            previous.configure(state='normal' if older else 'disabled');following.configure(state='normal' if newer else 'disabled')
        def more(side):count[side]+=20;refresh()
        controls=ttk.Frame(win);controls.pack(fill='x',padx=PAGE_X,pady=12)
        previous=ttk.Button(controls,text='更早的20条',command=lambda:more(0));previous.pack(side='left')
        following=ttk.Button(controls,text='后面的20条',command=lambda:more(1));following.pack(side='left',padx=8)
        ttk.Button(controls,text='关闭',command=win.destroy).pack(side='right')
        apply(win);win.update_idletasks();refresh()

    def show_notice(self,row):
        previous=getattr(self,'_notice_detail',None)
        if previous is not None and previous.winfo_exists():previous.destroy()
        self._workflow().read([row['id']])
        if hasattr(self,'_chatlog_refresh'):self._chatlog_refresh()
        win=self._experience_window('_notice_detail','通知详情',720,450)
        if win is None:return
        ttk.Label(win,text=row.get('source','通知')+' · '+time.strftime('%m-%d %H:%M',time.localtime(row['created']))).pack(anchor='w',padx=PAGE_X)
        from art_transcript import ArtTranscript
        text=ArtTranscript(win,plain=True);text.pack(fill='both',expand=True,padx=PAGE_X,pady=12);text.set_rows([row])
        controls=ttk.Frame(win);controls.pack(fill='x',padx=PAGE_X,pady=12)
        todo=next((r for r in self.todos if r['id']==row.get('todo_id')),None)
        if todo and not todo.get('done'):
            ttk.Button(controls,text='处理待办…',command=lambda:self.show_todo_quick(todo['id'])).pack(side='left')
        ttk.Button(controls,text='关闭',command=win.destroy).pack(side='right');apply(win)

    def _pomo_checkpoint(self):
        if getattr(self,'_pomo_phase',None) and time.monotonic()-getattr(self,'_pomo_last_tick',time.monotonic())<=30:
            self._workflow().checkpoint(self._pomo_left())

    def _pomo_offer_recovery(self):
        pending=deepcopy(self._workflow().data.get('focus'))
        if not pending or getattr(self,'_pomo_phase',None):return
        win=self._experience_window('_pomo_recovery','恢复番茄钟',650,340)
        if win is None:return
        todo=pending.get('todo') or {};remaining=max(0,float(pending.get('remaining',0)))
        ttk.Label(win,text=('上次的'+('专注' if pending['phase']=='focus' else '休息')+'还剩 '+self._pomo_mmss(remaining)+
                           '\n'+todo.get('text','未关联待办')+'\n退出或休眠期间不计入专注。'),wraplength=580).pack(fill='both',expand=True,padx=PAGE_X,pady=15)
        def resume():
            if self._pomo_phase is not None:return
            if (self._workflow().data.get('focus') or {}).get('id')!=pending['id']:win.destroy();return
            self._pomo_linked_todo=todo or None
            self._pomo_start(pending['phase'],resume_seconds=remaining);win.destroy()
        def discard():
            if (self._workflow().data.get('focus') or {}).get('id')==pending['id']:self._workflow().finish('放弃恢复')
            win.destroy()
        controls=ttk.Frame(win);controls.pack(fill='x',padx=PAGE_X,pady=16)
        ttk.Button(controls,text='继续剩余时间',command=resume).pack(side='left')
        ttk.Button(controls,text='结束这次',command=discard).pack(side='left',padx=8)
        ttk.Button(controls,text='稍后决定',command=win.destroy).pack(side='right');apply(win)

    def _pomo_task_start(self,tid):
        row=next((r for r in self.todos if r['id']==tid and not r.get('done')),None)
        if not row:return
        if self._pomo_phase is not None:
            messagebox.showinfo('番茄钟','已有计时正在运行，请先结束当前计时。',parent=self.root);return
        if self._workflow().data.get('focus'):
            self._pomo_offer_recovery();return
        self._pomo_linked_todo=dict(id=row['id'],text=row['text'],signature=self._todo_notice_signature(row))
        self._pomo_start('focus')

    def _pomo_finished_actions(self,completed):
        if not completed:return
        todo=completed.get('todo') or {}
        self._record_notice((todo.get('text') or '本轮专注')+'：专注结束，记录 '+str(round(completed.get('elapsed',0)/60,1))+' 分钟。',
                            '专注记录',key='focus:'+completed['id'],todo_id=todo.get('id'))
        if self._pomo_game_running() or getattr(self,'_quiet_active',False):return
        active=self._workflow().data.get('focus') or {}
        if self._pomo_phase!='break':return
        active_id=active.get('id')
        win=self._experience_window('_pomo_completed','本轮专注结束',700,360)
        if win is None:return
        todo=(completed or {}).get('todo') or {}
        elapsed=(completed or {}).get('elapsed',0)
        label=(todo.get('text') or '本轮专注')+'\n记录了 '+str(round(elapsed/60,1))+' 分钟，休息倒计时已开始。'
        if todo:label+='\n这件事累计专注 '+str(round(self._workflow().total(todo['id'])/60,1))+' 分钟；尚未自动标记完成。'
        ttk.Label(win,text=label,wraplength=620).pack(fill='both',expand=True,padx=PAGE_X,pady=12)
        buttons=ttk.Frame(win);buttons.pack(fill='x',padx=PAGE_X,pady=15)
        def still_current():
            return (self._workflow().data.get('focus') or {}).get('id')==active_id
        def again():
            if still_current():self._pomo_start('focus')
            win.destroy()
        def stop():
            if still_current():self._pomo_stop()
            win.destroy()
        def finish_task():
            row=next((r for r in self.todos if r['id']==todo.get('id') and not r.get('done')),None)
            if not row or self._todo_notice_signature(row)!=todo.get('signature'):
                messagebox.showinfo('待办已变化','这条待办已完成、删除或更改提醒。请到待办页面确认。',parent=win);return
            self._todo_set_done(row['id'],True);win.destroy()
        ttk.Button(buttons,text='再专注一轮',command=again).pack(side='left')
        ttk.Button(buttons,text='继续休息',command=win.destroy).pack(side='left',padx=8)
        if todo:ttk.Button(buttons,text='完成关联事项',command=finish_task).pack(side='left')
        ttk.Button(buttons,text='结束计时',command=stop).pack(side='right');apply(win)
