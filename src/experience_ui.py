"""Settings, reply feedback, memory applicability and local recovery UI."""
from pathlib import Path
import json,threading,time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter.scrolledtext import ScrolledText
from ui_theme import page_header,apply,PAGE_X


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
        win=tk.Toplevel(self.root);setattr(self,attribute,win)
        win.title('静香 · '+title);win.minsize(650,470);self._place_dialog(win,width,height)
        page_header(win,title).pack(fill='x')
        win.bind('<Escape>',lambda e:win.destroy())
        return win

    def show_settings_center(self):
        import pet
        from experience_settings import load,save
        from window_art import catalog,set_preferences
        win=self._experience_window('_settings_center','设置中心')
        if win is None:return
        prefs=load(pet.DATA_DIR)
        search=tk.StringVar();ttk.Entry(win,textvariable=search).pack(fill='x',padx=PAGE_X,pady=(0,12))
        notebook=ttk.Notebook(win);notebook.pack(fill='both',expand=True,padx=PAGE_X,pady=(0,18))
        groups={};searchable=[]
        for title in ('聊天与角色','主动搭话','声音与提醒','外观','连接与数据'):
            frame=ttk.Frame(notebook,padding=16);notebook.add(frame,text=title);groups[title]=frame
        def toggle(group,label,attr):
            value=tk.BooleanVar(value=bool(getattr(self,attr,False)))
            def change():
                setattr(self,attr,value.get());self._save_settings()
                mark=getattr(self,'_menu_marks',{}).get(attr)
                if mark and mark.winfo_exists():mark.configure(text='✓' if value.get() else '')
            button=ttk.Checkbutton(groups[group],text=label,variable=value,command=change)
            button.pack(anchor='w',pady=5);searchable.append((group,label,button))
        toggle('聊天与角色','敏感话题模式（非露骨成人话题）','_sensitive_topics_on')
        toggle('聊天与角色','不确定的消息联网查证','_web_search_on')
        for label,command in [('查看话题范围说明',self._show_sensitive_topic_help),('查看和标记对话',self.show_chat_log),
                              ('反馈记录与导出',self.show_feedback),('查看记忆与有效期',self.show_memory)]:
            ttk.Button(groups['聊天与角色'],text=label,command=command).pack(anchor='w',pady=6)
        self._weixin_init()
        from proactive_chat import state,command,describe,HELP
        pro=groups['主动搭话'];value=state(self._weixin_store.data)
        enabled=tk.BooleanVar(value=value['enabled']);start=tk.StringVar(value='%02d:%02d'%divmod(value['start'],60));end=tk.StringVar(value='%02d:%02d'%divmod(value['end'],60))
        frequency=tk.StringVar(value={1:'少',2:'偶尔',3:'多'}.get(value['daily_limit'],'偶尔'))
        ttk.Checkbutton(pro,text='允许微信主动搭话（无回复则暂停后续闲聊）',variable=enabled).pack(anchor='w',pady=6)
        row=ttk.Frame(pro);row.pack(fill='x',pady=8)
        ttk.Label(row,text='允许时段').pack(side='left');ttk.Entry(row,textvariable=start,width=8).pack(side='left',padx=8)
        ttk.Label(row,text='至').pack(side='left');ttk.Entry(row,textvariable=end,width=8).pack(side='left',padx=8)
        ttk.Combobox(row,textvariable=frequency,values=('少','偶尔','多'),state='readonly',width=8).pack(side='left')
        status=tk.StringVar(value=describe(value));ttk.Label(pro,textvariable=status,wraplength=690).pack(fill='x',pady=8)
        def set_proactive():
            data=dict(self._weixin_store.data)
            current,reply=command('/主动 时间 '+start.get()+'-'+end.get(),data)
            if '格式' in reply or '有效时刻' in reply:return messagebox.showerror('时间设置',reply,parent=win)
            data['proactive_chat']=current
            current,_=command('/主动 频率 '+frequency.get(),data)
            if enabled.get()!=current['enabled']:
                data['proactive_chat']=current;current,_=command('/主动 '+('开启' if enabled.get() else '关闭'),data)
            self._weixin_store.update(proactive_chat=current)
            channel=getattr(self,'_weixin_channel',None)
            if channel:channel.proactive_cancel.set()
            status.set(describe(current))
        ttk.Button(pro,text='保存微信主动设置',command=set_proactive).pack(anchor='w',pady=6)
        from proactive_topics import TOPIC_DESCRIPTION
        ttk.Label(pro,text=TOPIC_DESCRIPTION,wraplength=690,justify='left').pack(fill='x',pady=6)
        ttk.Label(pro,text=HELP,wraplength=690,justify='left').pack(fill='x',pady=8)
        desktop=tk.StringVar(value=prefs['desktop_proactive'])
        row=ttk.Frame(pro);row.pack(fill='x',pady=8);ttk.Label(row,text='桌面主动闲聊').pack(side='left')
        ttk.Combobox(row,textvariable=desktop,values=('关闭','很少','偶尔','较活跃'),state='readonly',width=10).pack(side='left',padx=8)
        def save_desktop(*args):
            prefs['desktop_proactive']=desktop.get();self._experience=save(pet.DATA_DIR,prefs)
        desktop.trace_add('write',save_desktop)
        for label,attr in [('语音朗读','_voice_on'),('开机问候','_greeting_on'),('开机待办提醒','_summary_on'),
                           ('全屏时免打扰','_quiet_fullscreen'),('游戏时免打扰','_quiet_games')]:toggle('声音与提醒',label,attr)
        missed=tk.BooleanVar(value=prefs.get('startup_missed',False))
        def save_missed():
            prefs['startup_missed']=missed.get();self._experience=save(pet.DATA_DIR,prefs)
        ttk.Checkbutton(groups['声音与提醒'],text='开机在聊天记录的通知页列出错过事项',variable=missed,
                        command=save_missed).pack(anchor='w',pady=6)
        ttk.Button(groups['声音与提醒'],text='配置语音',command=self._pick_gsv_dir).pack(anchor='w',pady=10)
        art=groups['外观'];names=['随机背景']+[r['file'] for r in catalog()]
        selected=tk.StringVar(value=prefs['background_file'] or '随机背景')
        ttk.Label(art,text='普通功能窗口背景（聊天装饰框保持独立）').pack(anchor='w',pady=8)
        ttk.Combobox(art,textvariable=selected,values=names,state='readonly',width=48).pack(fill='x')
        blur=tk.IntVar(value=prefs['blur']);dark=tk.DoubleVar(value=prefs['darkness'])
        ttk.Label(art,text='背景模糊').pack(anchor='w',pady=(16,4));ttk.Scale(art,from_=0,to=20,variable=blur).pack(fill='x')
        ttk.Label(art,text='背景加深').pack(anchor='w',pady=(16,4));ttk.Scale(art,from_=.25,to=.85,variable=dark).pack(fill='x')
        def save_art():
            prefs.update(background_file='' if selected.get()=='随机背景' else selected.get(),blur=blur.get(),darkness=dark.get())
            self._experience=save(pet.DATA_DIR,prefs);set_preferences(self._experience)
            for window in self.root.winfo_children():
                backdrop=getattr(window,'_art_backdrop',None)
                if backdrop:backdrop.reload_preferences()
        ttk.Button(art,text='应用到已打开的窗口',command=save_art).pack(anchor='w',pady=18)
        for label,cmd in [('微信连接',self.show_weixin),('模型与接口',self._prompt_api_key),('运行状态与重连',self.show_runtime_status),
                          ('本地备份与恢复',self.show_backup)]:ttk.Button(groups['连接与数据'],text=label,command=cmd).pack(anchor='w',pady=8)
        merge=tk.DoubleVar(value=self._weixin_store.data.get('chat_merge_seconds',.8))
        ttk.Label(groups['聊天与角色'],text='微信连续短消息等待合并（秒，0 为关闭，最长合并 3 秒）').pack(anchor='w',pady=(16,4))
        ttk.Spinbox(groups['聊天与角色'],from_=0,to=2,increment=.2,textvariable=merge,width=8).pack(anchor='w')
        def save_merge():
            try:self._weixin_store.update(chat_merge_seconds=max(0,min(2,merge.get())))
            except (ValueError,tk.TclError):messagebox.showerror('合并等待','请输入 0–2 秒。',parent=win)
        ttk.Button(groups['聊天与角色'],text='保存合并等待',command=save_merge).pack(anchor='w',pady=8)
        keywords={'聊天与角色':'反馈 导出 记忆 敏感 模型 连续 合并','主动搭话':'微信 主动 时间 频率',
                  '声音与提醒':'语音 提醒 免打扰','外观':'背景 模糊 明暗 图片','连接与数据':'接口 备份 恢复 状态 连接'}
        def find(*args):
            text=search.get().strip()
            if text:
                match=next((title for title,words in keywords.items() if text in title+words),None)
                if match:notebook.select(groups[match])
        search.trace_add('write',find);apply(win)

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
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.json',initialfile='静香-反馈记录.json',filetypes=[('JSON','*.json')])
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
