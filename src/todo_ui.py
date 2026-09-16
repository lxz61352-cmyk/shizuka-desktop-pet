"""Small categorized todo window with an explicit date/time editor."""
import calendar,time
from datetime import datetime,timedelta
import tkinter as tk
from tkinter import ttk,messagebox
from todo_model import CATEGORIES
from tkinter.scrolledtext import ScrolledText
from ui_theme import apply as apply_theme,copy_bindings

from todo_editor import TodoEditorMixin
from todo_schedule import schedule_facts

class TodoUIMixin(TodoEditorMixin):
    def show_todos(self,event=None):
        self._todo_init()
        win=getattr(self,'_todo_win',None)
        if win is not None and win.winfo_exists():self._move_dialog(win,900,690);return
        win=self._todo_win=tk.Toplevel(self.root)
        win.attributes('-topmost',True)
        win.title('静香 · 待办');win.minsize(680,500);self._place_dialog(win,900,690)
        heading=ttk.Frame(win,padding=(20,18,20,4));heading.pack(fill='x')
        ttk.Label(heading,text='一起安排好',style='Pet.Title.TLabel').pack(side='left')
        self._todo_count=tk.StringVar()
        ttk.Label(heading,textvariable=self._todo_count,style='Pet.Muted.TLabel').pack(side='right')
        top=ttk.Frame(win,padding=(12,10));top.pack(fill='x')
        ttk.Button(top,text='＋ 新建待办',command=self._todo_new).pack(side='left')
        ttk.Button(top,text='编辑 / 选择时间',command=self._todo_edit_selected).pack(side='left',padx=8)
        ttk.Button(top,text='刷新',command=self._refresh_todo_view).pack(side='right')
        self._todo_notebook=ttk.Notebook(win);self._todo_notebook.pack(fill='both',expand=True,padx=12)
        self._todo_trees={}
        for name in (*CATEGORIES,'已完成'):
            page=ttk.Frame(self._todo_notebook);self._todo_notebook.add(page,text=name)
            tree=ttk.Treeview(page,columns=('text','time','notify','status'),show='headings',selectmode='browse',height=4)
            for key,label,width in [('text','事项',270),('time','提醒时间',140),('notify','提醒方式',100),('status','状态',140)]:
                tree.heading(key,text=label);tree.column(key,width=width,minwidth=70,stretch=key in ('text','status'))
            bar=ttk.Scrollbar(page,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=bar.set)
            bar.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
            tree.bind('<Double-1>',lambda e:self._todo_edit_selected())
            tree.bind('<Return>',lambda e:self._todo_edit_selected())
            tree.bind('<<TreeviewSelect>>',lambda e:self._todo_show_details())
            self._todo_trees[name]=tree
        details=ttk.Frame(win,padding=(14,10,14,0));details.pack(fill='x')
        ttk.Label(details,text='事项与备注',style='Pet.Muted.TLabel').pack(anchor='w')
        self._todo_details_box=ScrolledText(details,height=4,wrap='word',state='disabled')
        self._todo_details_box.pack(fill='x',pady=(5,0));copy_bindings(self._todo_details_box)
        self._todo_notebook.bind('<<NotebookTabChanged>>',lambda e:self._todo_show_details())
        actions=ttk.Frame(win,padding=(12,8));actions.pack(fill='x')
        self._todo_complete_button=ttk.Button(actions,text='完成',command=self._todo_toggle_selected);self._todo_complete_button.pack(side='left')
        self._todo_end_button=ttk.Button(actions,text='结束循环',command=self._todo_end_selected)
        ttk.Button(actions,text='删除',command=self._todo_delete_selected).pack(side='left',padx=8)
        ttk.Button(actions,text='重试微信提醒',command=self._todo_retry_selected).pack(side='left')
        ttk.Button(actions,text='关闭',command=self._close_todo_window).pack(side='right')
        self._todo_status=tk.StringVar()
        ttk.Label(win,textvariable=self._todo_status,wraplength=750).pack(fill='x',padx=14,pady=(0,10))
        win.protocol('WM_DELETE_WINDOW',self._close_todo_window)
        win.bind('<Escape>',lambda e:self._close_todo_window())
        # Reserve the notes and action rows before allocating remaining space to the list.
        children=win.winfo_children()
        for child in children:child.pack_forget()
        for index,child in enumerate(children):
            child.grid(row=index,column=0,sticky='nsew' if child is self._todo_notebook else 'ew',padx=12 if child is self._todo_notebook else 0)
            if child is self._todo_notebook:win.rowconfigure(index,weight=1,minsize=100)
        win.columnconfigure(0,weight=1)
        apply_theme(win);self._refresh_todo_view()

    def _todo_show_details(self):
        box=getattr(self,'_todo_details_box',None)
        if box is None or not box.winfo_exists():return
        item=self._todo_selected();lines=[]
        if item:
            options=self._todo_options(item);lines.append(item['text'])
            if options.get('manual_note'):lines+=['','备注：'+options['manual_note']]
            for note in options.get('notes',[]):
                stamp=time.strftime('%m-%d %H:%M',time.localtime(note.get('created',0)))
                lines+=['',stamp+' · '+('微信' if note.get('channel')=='weixin' else '对话')+'中的补充',note['text']]
            lines.insert(1,schedule_facts(item,options))
        else:lines=[]
        if hasattr(self,'_todo_complete_button'):
            rule=self._todo_options(item).get('schedule',{}).get('rule') if item else None
            self._todo_complete_button.configure(text='恢复' if item and item.get('done') else '完成本次' if rule and not rule.get('until_done') else '完成')
            if rule and not rule.get('until_done') and not item.get('done'):self._todo_end_button.pack(side='left',after=self._todo_complete_button,padx=6)
            else:self._todo_end_button.pack_forget()
        box.configure(state='normal');box.delete('1.0','end');box.insert('1.0','\n'.join(lines));box.configure(state='disabled')

    def _close_todo_window(self):
        win=getattr(self,'_todo_win',None);self._todo_win=None
        editor=getattr(self,'_todo_editor_win',None)
        if editor is not None and editor.winfo_exists():editor.destroy()
        self._todo_editor_win=None
        if win is not None and win.winfo_exists():win.destroy()

    def _todo_selected(self):
        if not getattr(self,'_todo_win',None):return None
        names=(*CATEGORIES,'已完成')
        tree=self._todo_trees[names[self._todo_notebook.index('current')]]
        selected=tree.selection()
        return next((it for it in self.todos if selected and it['id']==selected[0]),None)

    def _todo_state_label(self,item):
        if item.get('done'):return '已完成'
        options=self._todo_options(item);notice=options.get('notice',{})
        from dialogue_grounding import event_expired
        if event_expired(item,options):return '开始时间已过，完成待确认'
        if options.get('time_hint') and not item.get('due') and not item.get('on_boot'):return '时间待确认'
        wx=notice.get('weixin') if options.get('weixin',True) else None
        if wx in ('failed','uncertain'):return '微信待核对 / 可重试'
        if wx=='waiting':return '微信待就绪'
        if wx=='sending':return '微信发送中'
        if wx=='sent':return '已提醒，未完成'
        if notice.get('desktop'):return '已提醒，未完成'
        return '待提醒' if item.get('due') or item.get('on_boot') else '未安排时间'

    def _refresh_todo_view(self):
        win=getattr(self,'_todo_win',None)
        if win is None or not win.winfo_exists() or not hasattr(self,'_todo_trees'):return
        for name,tree in self._todo_trees.items():
            selection=tree.selection();wanted=[]
            for item in sorted(self.todos,key=lambda x:(x.get('due') or 9e18,x.get('created',0))):
                options=self._todo_options(item)
                target='已完成' if item.get('done') else options.get('category','生活')
                if target!=name:continue
                wanted.append(item['id'])
                when='下次启动' if item.get('on_boot') else datetime.fromtimestamp(item['due']).strftime('%m-%d %H:%M') if item.get('due') else '未安排'
                channels='＋'.join(label for key,label in [('desktop','桌面'),('weixin','微信')] if options.get(key,True)) or '不提醒'
                values=(item['text'],when,channels,self._todo_state_label(item))
                if tree.exists(item['id']):tree.item(item['id'],values=values)
                else:tree.insert('', 'end',iid=item['id'],values=values)
            for old in tree.get_children():
                if old not in wanted:tree.delete(old)
            for index,ident in enumerate(wanted):tree.move(ident,'',index)
            if selection and tree.exists(selection[0]):tree.selection_set(selection)
        self._todo_status.set('')
        if hasattr(self,'_todo_count'):self._todo_count.set(f"还有 {sum(not it.get('done') for it in self.todos)} 件事 · 已完成 {sum(bool(it.get('done')) for it in self.todos)} 件")
        self._todo_show_details()

    def _todo_end_selected(self):
        item=self._todo_selected()
        if item:self._todo_end_series(item['id'])

    def _todo_new(self):self._todo_open_editor()

    def _todo_edit_selected(self):
        item=self._todo_selected()
        if item:self._todo_open_editor(item)
        else:self._todo_status.set('请先选中一条待办，再编辑内容或选择时间。')

    def _todo_toggle_selected(self):
        item=self._todo_selected()
        if item:self._todo_set_done(item['id'],not item.get('done'))

    def _todo_delete_selected(self):
        item=self._todo_selected()
        if item:self._todo_delete(item['id'])

    def _todo_retry_selected(self):
        item=self._todo_selected()
        if not item:return
        notice=self._todo_options(item).get('notice',{})
        state=notice.get('weixin')
        if state not in ('failed','uncertain','waiting'):
            self._todo_status.set('这条待办没有需要重试的微信提醒。');return
        if state=='uncertain' and not messagebox.askyesno('核对微信','上次发送结果不确定。请先核对微信；再次发送可能收到重复提醒。仍要重试吗？',parent=self._todo_win):return
        notice.update(weixin='pending',error='');self._save_todo_details();self._todo_check_reminders()


    def _todo_calendar(self,parent,value):
        try:current=datetime.strptime(value.get(),'%Y-%m-%d')
        except ValueError:current=datetime.now()
        win=tk.Toplevel(parent);win.title('选择日期');win.resizable(False,False)
        win.transient(parent);win.attributes('-topmost',True)
        year=tk.IntVar(value=current.year);month=tk.IntVar(value=current.month)
        head=ttk.Frame(win,padding=8);head.pack(fill='x')
        title=tk.StringVar();grid=ttk.Frame(win,padding=8);grid.pack()
        def select(day):value.set(f'{year.get():04d}-{month.get():02d}-{day:02d}');win.destroy()
        def draw():
            title.set(f'{year.get()}年 {month.get()}月')
            for widget in grid.winfo_children():widget.destroy()
            for column,name in enumerate('一二三四五六日'):ttk.Label(grid,text=name,anchor='center',width=5).grid(row=0,column=column)
            for row,week in enumerate(calendar.monthcalendar(year.get(),month.get()),1):
                for column,day in enumerate(week):
                    if day:ttk.Button(grid,text=str(day),width=5,command=lambda d=day:select(d)).grid(row=row,column=column,padx=1,pady=1)
        def shift(delta):
            y,m=divmod(year.get()*12+month.get()-1+delta,12)
            if 1900<=y<=9999:year.set(y);month.set(m+1);draw()
        ttk.Button(head,text='‹',width=4,command=lambda:shift(-1)).pack(side='left')
        ttk.Label(head,textvariable=title,anchor='center').pack(side='left',fill='x',expand=True)
        ttk.Button(head,text='›',width=4,command=lambda:shift(1)).pack(side='right')
        draw()
