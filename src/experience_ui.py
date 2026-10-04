"""Settings, reply feedback, memory applicability and local recovery UI."""
from pathlib import Path
import json,threading,time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter.scrolledtext import ScrolledText
from ui_theme import page_header,apply,PAGE_X
from window_opening import dialog_window


class ExperienceMixin:
    def _casual_proactive_allowed(self):
        mode=getattr(self,'_experience',{}).get('desktop_proactive','偶尔')
        if mode=='关闭' or getattr(self,'_pomo_phase',None)=='focus':return False
        gap={'很少':6*3600,'偶尔':3*3600,'较活跃':2*3600}.get(mode,3*3600)
        with self._chat_lock:rows=list(self._chat_log[-120:])
        last=next((r for r in reversed(rows) if r.get('role')=='assistant' and r.get('kind') in ('proactive','weixin_proactive')),None)
        if not last:return True
        if time.time()-last.get('created',0)<gap:return False
        return any(r.get('role')=='user' and r.get('kind') in ('chat','user','weixin')
                   and r.get('created',0)>last.get('created',0) for r in rows)

    def _experience_boot(self):
        import pet
        from experience_settings import load
        from window_art import set_preferences
        self._experience=load(pet.DATA_DIR);set_preferences(self._experience)
        path=Path(pet.DATA_DIR)/'chat-draft.json'
        if path.exists():
            try:self._chat_text=json.loads(path.read_text('utf-8-sig')).get('text','')
            except (ValueError,OSError):pass
        def snapshot():
            from app_identity import APP_VERSION
            from personal_backup import create
            marker=Path(pet.DATA_DIR)/'backup-version.json'
            try:
                previous=json.loads(marker.read_text('utf-8-sig')).get('version') if marker.exists() else None
                if previous!=APP_VERSION:
                    create(pet.DATA_DIR,'version-'+APP_VERSION)
                    from sync_bridge import atomic_json
                    atomic_json(str(marker),{'version':APP_VERSION})
            except Exception as exc:self._backup_error=type(exc).__name__
        threading.Thread(target=snapshot,daemon=True).start()
        self.root.after(800,self._workflow_boot)

    def _save_chat_draft(self,text):
        import pet
        from sync_bridge import atomic_json
        atomic_json(str(Path(pet.DATA_DIR)/'chat-draft.json'),{'text':text})

    def _experience_window(self,attribute,title,width=820,height=690):
        self.close_popup()
        old=getattr(self,attribute,None)
        if old is not None and old.winfo_exists():old.lift();return None
        win=dialog_window(self.root);setattr(self,attribute,win)
        win.title('Shizuka · '+title);win.minsize(650,470);self._place_dialog(win,width,height)
        page_header(win,title).pack(fill='x')
        win.bind('<Escape>',lambda e:win.destroy())
        return win

    def show_settings_center(self, section=None):
        from settings_center import show
        show(self, section)

    def show_reply_feedback(self,row):
        from dialogue_feedback import FeedbackStore,TAGS
        import pet
        if row.get('role')!='assistant':return
        win=self._experience_window('_feedback_editor','标记这条回复',760,580)
        if win is None:return
        body=ttk.Frame(win,padding=PAGE_X);body.pack(fill='both',expand=True)
        quote=ScrolledText(body,height=6,wrap='word');quote.insert('1.0',row.get('text',''));quote.configure(state='disabled');quote.pack(fill='both',expand=True)
        tag=tk.StringVar(value=TAGS[0]);ttk.Combobox(body,textvariable=tag,values=TAGS,state='readonly').pack(anchor='w',pady=12)
        ttk.Label(body,text='哪里不对劲，或哪里说得好（可不填）').pack(anchor='w')
        note=ScrolledText(body,height=3,wrap='word');note.pack(fill='x',pady=6)
        ttk.Label(body,text='保存在本地，不自动变成角色规则或示例。旧消息未留请求快照时会明确标注。',wraplength=680).pack(anchor='w',pady=8)
        def mark():
            with self._chat_lock:
                i=next((i for i,r in enumerate(self._chat_log) if r.get('id')==row.get('id')),len(self._chat_log)-1)
                context=self._chat_log[max(0,i-7):i+1]
            FeedbackStore(pet.DATA_DIR).mark(row,tag.get(),note.get('1.0','end-1c'),context);win.destroy()
        ttk.Button(body,text='保存标记',command=mark).pack(side='right');apply(win)

    def show_feedback(self):
        from dialogue_feedback import FeedbackStore
        import pet
        win=self._experience_window('_feedback_window','反馈记录与导出',920,720)
        if win is None:return
        store=FeedbackStore(pet.DATA_DIR);rows=store.rows();mapping={r['id']:r for r in rows}
        table=ttk.Treeview(win,columns=('tag','text'),show='headings',height=7,selectmode='extended')
        table.heading('tag',text='标记');table.heading('text',text='回复');table.column('tag',width=110,stretch=False)
        for row in rows:table.insert('', 'end',iid=row['id'],values=(row['tag'],row['reply']['text'][:100]))
        table.pack(fill='x',padx=PAGE_X)
        preview=ScrolledText(win,wrap='word',height=15);preview.pack(fill='both',expand=True,padx=PAGE_X,pady=12)
        ttk.Label(win,text='选择一条或多条查看将导出的内容，可在下方编辑。快照只包含当时资料，不含模型内部思考。').pack(padx=PAGE_X,anchor='w')
        def select(event=None):
            preview.delete('1.0','end');preview.insert('1.0',store.export(table.selection()))
        table.bind('<<TreeviewSelect>>',select)
        def export():
            try:payload=json.loads(preview.get('1.0','end-1c'))
            except ValueError:return messagebox.showerror('导出','预览内容必须是有效 JSON。',parent=win)
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.json',initialfile='Shizuka-反馈记录.json',filetypes=[('JSON','*.json')])
            if path:Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf-8')
        ttk.Button(win,text='导出预览中的内容',command=export).pack(anchor='e',padx=PAGE_X,pady=12);apply(win)

    def show_runtime_status(self):
        import pet
        win=self._experience_window('_runtime_window','运行状态',760,570)
        if win is None:return
        text=tk.StringVar();ttk.Label(win,textvariable=text,wraplength=700,justify='left').pack(fill='both',expand=True,padx=PAGE_X,pady=15)
        def refresh():
            if not win.winfo_exists():return
            channel=getattr(self,'_weixin_channel',None)
            status=getattr(self,'_weixin_state',{}).get('status','未连接')
            speech='播放中' if getattr(self,'_voice_active',False) else '已启用，当前未播放' if self._voice_on else '关闭'
            from app_identity import APP_VERSION
            from window_art import performance
            lines=['版本：'+APP_VERSION,'聊天接口：'+('已配置（连接可用性以实际请求为准）' if pet.has_api_key() else '未配置'),
                   '模型：'+pet.api_model(),'微信：'+status,'语音：'+speech,
                   '桌面请求：'+getattr(self,'_last_reply_status','本次启动尚无记录'),
                   '背景绘制：'+performance(),'备份：'+getattr(self,'_backup_error','正常')]
            if channel:
                from proactive_chat import state,describe
                lines.append(describe(state(self._weixin_store.data)))
            text.set('\n\n'.join(lines));win.after(1500,refresh)
        row=ttk.Frame(win,padding=PAGE_X);row.pack(fill='x')
        def reconnect():self._weixin_stop();self._weixin_connect()
        ttk.Button(row,text='重新连接微信',command=reconnect).pack(side='left')
        ttk.Button(row,text='检查模型配置',command=self._prompt_api_key).pack(side='left',padx=8)
        ttk.Button(row,text='停止当前朗读',command=self._cancel_reply).pack(side='left')
        def retry():
            failed=getattr(self,'_failed_chat',None)
            if failed:self.on_chat_submit(failed['text'],attachments=failed.get('attachments'))
            else:messagebox.showinfo('重试','当前没有失败的聊天请求。文件任务不会在这里重试。',parent=win)
        ttk.Button(row,text='重试失败聊天',command=retry).pack(side='left',padx=8)
        apply(win);refresh()

    def show_backup(self):
        import pet
        from personal_backup import create,inspect,stage_restore,category
        win=self._experience_window('_backup_window','本地备份与恢复',760,540)
        if win is None:return
        ttk.Label(win,text='升级版本首次启动会保存一次本地快照。备份不包含微信绑定和接口密钥。\n恢复在下次启动时应用；恢复前另存一份当前快照。',wraplength=700).pack(fill='x',padx=PAGE_X,pady=12)
        status=tk.StringVar();ttk.Label(win,textvariable=status,wraplength=690).pack(fill='x',padx=PAGE_X,pady=10)
        choices={name:tk.BooleanVar(value=True) for name in ('设置与反馈','记忆','待办','聊天')}
        for name,value in choices.items():ttk.Checkbutton(win,text=name,variable=value).pack(anchor='w',padx=PAGE_X)
        def backup():
            def work():
                try:path=create(pet.DATA_DIR);self._ui(lambda:status.set('已备份：'+str(path)))
                except Exception:self._ui(lambda:status.set('备份失败，原数据未修改。'))
            threading.Thread(target=work,daemon=True).start()
        def restore():
            path=filedialog.askopenfilename(parent=win,initialdir=str(Path(pet.DATA_DIR)/'backups'),filetypes=[('本地备份','*.zip')])
            if not path:return
            try:
                items=inspect(path);selected=[name for name,v in choices.items() if v.get()]
                count=sum(category(name) in selected for name in items)
                if not count:return messagebox.showinfo('恢复','所选范围中没有文件。',parent=win)
                if not messagebox.askyesno('确认恢复',f'下次启动将覆盖所选范围的 {count} 个数据文件。\n恢复前会备份当前数据。继续？',parent=win):return
                stage_restore(pet.DATA_DIR,path,selected);status.set('恢复已安排，下次启动应用。请正常退出后重新启动桌宠。')
            except Exception as exc:messagebox.showerror('恢复未安排',str(exc),parent=win)
        row=ttk.Frame(win,padding=PAGE_X);row.pack(fill='x')
        ttk.Button(row,text='立即备份',command=backup).pack(side='left');ttk.Button(row,text='选择备份并恢复所选范围',command=restore).pack(side='left',padx=8)
        apply(win)

    def show_memory_details(self,mid):
        import pet
        from memory_lifecycle import label,expiry
        memory=pet.get_memory();row=next((r for r in memory.snapshot() if r['id']==mid),None)
        if not row:return
        win=self._experience_window('_memory_details','记忆来源与有效期',740,560)
        if win is None:return
        ttk.Label(win,text=row.get('content',''),wraplength=670).pack(fill='x',padx=PAGE_X,pady=12)
        source_path=Path(pet.CHARACTER_DATA_DIR)/'memory-review.json'
        if not row.get('source_quote') and source_path.exists():
            source=json.loads(source_path.read_text('utf-8-sig')).get('sources',{}).get(mid,{})
            row=dict(row,source_quote=source.get('quote'),source_time=source.get('source_time'))
        expires=expiry(row)
        detail='当前状态：'+label(row)+'\n来源原话：'+str(row.get('source_quote') or row.get('quote') or '此条未保留来源原话')+'\n来源时间：'+time.strftime('%Y-%m-%d %H:%M',time.localtime(row.get('source_time') or row.get('created',0)))
        if expires:detail+='\n有效至：'+time.strftime('%Y-%m-%d %H:%M',time.localtime(expires))
        ttk.Label(win,text=detail,wraplength=670,justify='left').pack(fill='x',padx=PAGE_X,pady=12)
        choice=tk.StringVar(value='保持原样')
        ttk.Combobox(win,textvariable=choice,values=('保持原样','长期有效','今天有效','7天有效','事情已结束'),state='readonly').pack(anchor='w',padx=PAGE_X,pady=12)
        def save():
            from copy import deepcopy
            with memory._lock:
                self._remember_memory_undo(memory.items)
                current=next(r for r in memory.items if r['id']==mid)
                if choice.get()=='长期有效':current.update(expires_at=0,status='active')
                elif choice.get()=='今天有效':
                    stamp=list(time.localtime());stamp[2]+=1;stamp[3:6]=[0,0,0]
                    current.update(expires_at=time.mktime(tuple(stamp)),status='active')
                elif choice.get()=='7天有效':current.update(expires_at=time.time()+7*86400,status='active')
                elif choice.get()=='事情已结束':current['status']='completed'
                memory.save()
                self._finish_memory_undo(memory.items)
            self._build_memory_rows();win.destroy()
        ttk.Button(win,text='保存',command=save).pack(anchor='e',padx=PAGE_X,pady=12);apply(win)

    def _remember_memory_undo(self,rows):
        from copy import deepcopy
        self._memory_before=deepcopy(rows)

    def _finish_memory_undo(self,rows):
        from copy import deepcopy
        self._memory_undo=(self._memory_before,deepcopy(rows))

    def undo_memory_change(self):
        import pet
        previous=getattr(self,'_memory_undo',None)
        if previous is None:return
        memory=pet.get_memory()
        with memory._lock:
            from memory_lifecycle import undo_edit
            memory.items,conflicts=undo_edit(memory.items,*previous)
            memory.save();self._memory_undo=None
        self._build_memory_rows()
        if conflicts:messagebox.showinfo('撤销修改','部分记忆已有新的修改，已保留这些新内容。',parent=self._mem_win)
