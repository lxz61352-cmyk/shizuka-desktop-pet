"""Explicit, occurrence-bound reminder postponement. Recurrence stays unchanged."""
from copy import deepcopy
from datetime import datetime,timedelta
import re,threading,time
import tkinter as tk
from tkinter import ttk,messagebox
from ui_theme import apply,PAGE_X


def snooze_time(text,now):
    text=text.strip().rstrip('。！!')
    if text in ('晚点再提醒我','晚点再提醒','稍后再提醒','稍后提醒','晚点再叫我','/稍后'):
        return now+600
    if text in ('晚上再提醒我','晚上再提醒','改到晚上','/稍后 今晚'):
        target=datetime.fromtimestamp(now).replace(hour=20,minute=0,second=0,microsecond=0).timestamp()
        if target<=now:raise ValueError('今晚20:00已经过了，请说明新的时间，例如“30分钟后再提醒我”。')
        return target
    match=re.fullmatch(r'(?:/稍后\s*)?(\d+|十|半|二十|三十|一|两)(分钟|小时)(?:后)?(?:再(?:提醒|叫)(?:我)?)?',text)
    if not match:return None
    if not text.startswith('/稍后') and not re.search(r'再(?:提醒|叫)',text):return None
    amount={'十':10,'半':.5,'二十':20,'三十':30,'一':1,'两':2}.get(match[1])
    if amount is None:amount=int(match[1])
    seconds=amount*(60 if match[2]=='分钟' else 3600)
    if not 60<=seconds<=86400:raise ValueError('稍后提醒支持1分钟到24小时；其他日期请编辑待办时间。')
    return now+seconds


class TodoQuickMixin:
    def _todo_effective_due(self,item):
        return self._todo_options(item).get('snooze_until') or item.get('due')

    def _todo_snooze(self,tid,until,signature=None):
        row=next((r for r in self.todos if r['id']==tid and not r.get('done')),None)
        if not row:return '这条待办已完成或不存在。'
        if signature and self._todo_notice_signature(row)!=signature:return '这条提醒已变化，请重新选择。'
        if not time.time()<until<=time.time()+86401:return '请选择未来24小时内的提醒时间。'
        options=self._todo_options(row);prior=deepcopy(options)
        options['snooze_until']=until;options['snooze_due']=row.get('due');options.pop('notice',None)
        try:self._save_todo_details()
        except Exception:options.clear();options.update(prior);raise
        self._todo_cancel_notices(tid);self._refresh_todo_view()
        return row['text']+'，改在 '+time.strftime('%m-%d %H:%M',time.localtime(until))+' 再提醒。'+('循环时间不变。' if options.get('schedule',{}).get('rule') else '')

    def show_todo_quick(self,tid=None):
        row=next((r for r in self.todos if r['id']==tid),None) if tid else self._todo_selected()
        if not row:
            messagebox.showinfo('待办快捷处理','先选中一条待办。',parent=self.root);return
        if row.get('done'):return
        win=self._experience_window('_todo_quick_win','待办快捷处理',690,390)
        if win is None:return
        signature=self._todo_notice_signature(row)
        total=self._workflow().total(row['id'])
        label=tk.StringVar(value=row['text']+'\n累计专注 '+str(round(total/60,1))+' 分钟')
        ttk.Label(win,textvariable=label,wraplength=600).pack(fill='both',expand=True,padx=PAGE_X,pady=10)
        controls=ttk.Frame(win);controls.pack(fill='x',padx=PAGE_X,pady=12)
        def delay(seconds=None):
            try:
                at=time.time()+seconds if seconds else snooze_time('/稍后 今晚',time.time())
                label.set(self._todo_snooze(row['id'],at,signature));
            except ValueError as error:label.set(str(error))
        ttk.Button(controls,text='10分钟后提醒',command=lambda:delay(600)).pack(side='left')
        ttk.Button(controls,text='30分钟后提醒',command=lambda:delay(1800)).pack(side='left',padx=8)
        ttk.Button(controls,text='今晚20:00提醒',command=delay).pack(side='left')
        actions=ttk.Frame(win);actions.pack(fill='x',padx=PAGE_X,pady=(0,16))
        def complete():
            if self._todo_notice_signature(row)!=signature:label.set('这条提醒已变化，请重新打开。');return
            self._todo_set_done(row['id'],True);win.destroy()
        ttk.Button(actions,text='完成本次',command=complete).pack(side='left')
        ttk.Button(actions,text='开始专注',command=lambda:(self._pomo_task_start(row['id']),win.destroy())).pack(side='left',padx=8)
        ttk.Button(actions,text='编辑时间…',command=lambda:self._todo_open_editor(row)).pack(side='left')
        ttk.Button(actions,text='关闭',command=win.destroy).pack(side='right');apply(win)

    def _todo_quick_from_chat(self,text,channel='desktop'):
        now=time.time();pending=getattr(self,'_todo_snooze_choices',{}).get(channel)
        if pending and now-pending['at']<300 and text.strip().isdigit():
            index=int(text.strip())-1
            if not 0<=index<len(pending['items']):return '请选择列表里的编号。'
            spec=pending['items'][index];self._todo_snooze_choices.pop(channel,None)
            return self._todo_snooze(spec['id'],pending['until'],spec['signature'])
        try:until=snooze_time(text,now)
        except ValueError as error:return str(error)
        if until is None:
            if pending:self._todo_snooze_choices.pop(channel,None)
            return None
        target=getattr(self,'_todo_reply_targets',{}).get(channel)
        if target and time.monotonic()-target['at']<1800:
            specs=[s for s in target['items'] if any(r['id']==s['id'] and not r.get('done') for r in self.todos)]
        else:specs=[dict(id=r['id'],title=r['text'],signature=self._todo_notice_signature(r)) for r in self.todos if not r.get('done')]
        if not specs:return '当前没有可以延后提醒的待办。'
        if len(specs)==1:return self._todo_snooze(specs[0]['id'],until,specs[0]['signature'])
        if not hasattr(self,'_todo_snooze_choices'):self._todo_snooze_choices={}
        self._todo_snooze_choices[channel]=dict(at=now,until=until,items=specs)
        return '要延后哪一条？回复编号即可。\n'+'\n'.join(str(i)+'. '+r['title'] for i,r in enumerate(specs,1))

    def _weixin_quick_todo(self,text,cancel):
        ready=threading.Event();result=[]
        def apply():
            try:result.append(None if cancel.is_set() else self._todo_quick_from_chat(text,'weixin'))
            except Exception:result.append('提醒时间保存失败，请到待办里核对后再试。')
            finally:ready.set()
        self._ui(apply)
        if not ready.wait(8):cancel.set();return '提醒时间尚未确认保存，请到待办里核对。'
        return result[0]
