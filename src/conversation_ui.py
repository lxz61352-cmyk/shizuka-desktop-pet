"""Selectable conversation history and a multiline, lightweight composer."""
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from ui_theme import BG,CARD,INK,MUTED,ACCENT,FONT,apply,copy_bindings,copy_text,round_window

CHAT_RADIUS=16   # 聊天框圆角

class Composer(ScrolledText):
    def get(self,*args):return super().get(*(args or ('1.0','end-1c')))

class ConversationUIMixin:
    def open_chat_input(self,prefill=''):
        self._cancel_chat_click();self._wake_pet()
        if self._chat_win is not None:
            self._chat_win.lift();return
        self._cancel_reply();self.close_popup()
        win=tk.Toplevel(self.root);win.withdraw();win.overrideredirect(True);win.attributes('-topmost',True)
        R=CHAT_RADIUS
        header=tk.Frame(win,bg=BG);header.pack(fill='x',padx=12+R,pady=(10+R,6))
        tk.Label(header,text='静香',font=('Microsoft YaHei UI',12,'bold'),bg=BG,fg=INK).pack(side='left')
        entry=Composer(win,height=4,width=38,wrap='word');entry.pack(fill='both',expand=True,padx=12+R)
        entry.insert('1.0',prefill or getattr(self,'_chat_text',''));copy_bindings(entry)
        footer=ttk.Frame(win,padding=(12+R,8+R));footer.pack(fill='x',padx=12+R,pady=(0,R))
        def close():
            self._chat_text=entry.get();self.close_chat_win()
        def send(event=None):
            text=entry.get().strip();self._chat_text='';self.close_chat_win()
            if text:self.on_chat_submit(text)
            return 'break'
        ttk.Button(footer,text='发送',command=send).pack(side='right')
        tk.Button(header,text='×',command=close,bg=BG,fg=MUTED,relief='flat',bd=0,font=FONT).pack(side='right')
        entry.bind('<Return>',send)
        entry.bind('<Shift-Return>',lambda e:(entry.insert('insert','\n'),'break')[-1])
        win.bind('<Escape>',lambda e:close())
        self._chat_win=win;self._chat_entry=entry
        apply(win);round_window(win,R);win.update_idletasks();win.geometry(f'430x{win.winfo_reqheight()}')
        self.update_chat_pos();win.deiconify();win.lift();entry.focus_force()
        win.after(120,lambda:self._poll_chat_outside(win))

    def show_chat_log(self,event=None):
        old=getattr(self,'_chatlog_win',None)
        if old is not None and old.winfo_exists():old.lift();return
        win=self._chatlog_win=tk.Toplevel(self.root);win.title('静香 · 对话');win.geometry('820x650');win.minsize(620,460)
        win.attributes('-topmost',True)
        head=ttk.Frame(win,padding=(22,18,22,8));head.pack(fill='x')
        ttk.Label(head,text='和静香的对话',style='Pet.Title.TLabel').pack(side='left')
        ttk.Button(head,text='继续聊',command=self.open_chat_input).pack(side='right')
        row=ttk.Frame(win,padding=(22,0,22,12));row.pack(fill='x')
        query=tk.StringVar();field=ttk.Entry(row,textvariable=query);field.pack(side='left',fill='x',expand=True)
        mode=tk.StringVar(value='对话');ttk.Combobox(row,textvariable=mode,values=('对话','全部记录'),state='readonly',width=11).pack(side='left',padx=(8,0))
        box=ScrolledText(win,wrap='word',state='disabled',spacing1=5,spacing3=10);box.pack(fill='both',expand=True,padx=22)
        self._chatlog_text=box;copy_bindings(box)
        box.tag_configure('user',foreground=ACCENT,font=('Microsoft YaHei UI',10,'bold'),spacing1=14)
        box.tag_configure('assistant',foreground=INK,font=('Microsoft YaHei UI',10,'bold'),spacing1=14)
        box.tag_configure('meta',foreground=MUTED,font=('Microsoft YaHei UI',9))
        box.tag_configure('body',lmargin1=8,lmargin2=8,rmargin=14)
        foot=ttk.Frame(win,padding=(22,12));foot.pack(fill='x')
        status=tk.StringVar();ttk.Label(foot,textvariable=status,style='Pet.Muted.TLabel').pack(side='left')
        ttk.Button(foot,text='复制所选',command=lambda:copy_text(box)).pack(side='right')
        ttk.Button(foot,text='复制全部',command=lambda:copy_text(box,True)).pack(side='right',padx=8)
        def refresh():
            if not win.winfo_exists():return
            with self._chat_lock:rows=list(self._chat_log)
            search=query.get().strip().casefold()
            if mode.get()=='对话':rows=[r for r in rows if r.get('role') in ('user','assistant') and r.get('kind')!='memory_summary']
            if search:rows=[r for r in rows if search in r.get('text','').casefold()]
            visible=rows[-500:]
            box.configure(state='normal');box.delete('1.0','end')
            for item in visible:
                role=item.get('role');label='您' if role=='user' else '静香' if role=='assistant' else '记录'
                stamp=time.strftime('%m-%d %H:%M',time.localtime(item.get('created',0)))
                channel='微信' if str(item.get('kind','')).startswith('weixin') else '桌面'
                box.insert('end',label+'  ',role if role in ('user','assistant') else 'meta')
                box.insert('end',stamp+' · '+channel+'\n','meta')
                box.insert('end',item.get('text','')+'\n\n','body')
            if not visible:box.insert('end','这里还没有符合条件的对话。\n','meta')
            box.configure(state='disabled');box.see('end')
            status.set(f'{len(rows)} 条记录'+(' · 显示最近500条' if len(rows)>500 else ''))
        self._chatlog_refresh=refresh
        ttk.Button(row,text='查找 / 刷新',command=refresh).pack(side='left',padx=(8,0))
        field.bind('<Return>',lambda e:refresh());mode.trace_add('write',lambda *a:refresh())
        win.protocol('WM_DELETE_WINDOW',self._close_chat_log);win.bind('<Escape>',lambda e:self._close_chat_log())
        apply(win);refresh()
