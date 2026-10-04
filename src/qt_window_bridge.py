"""Private stdio bridge: Tk owns business state; Qt owns its two GPU windows.

No network listener, second data writer, credentials or second model client.
Pipe I/O runs on workers. Application callbacks only run on Tk's UI thread.
"""
from copy import deepcopy
from pathlib import Path
import json,os,queue,subprocess,sys,threading,time,uuid

REVISION='qt-tools-v2'
MAX_MESSAGE=32*1024*1024
FIELDS=('id','role','text','source','created','kind','todo_id','read')

def enabled():
    forced=os.environ.get('SHIZUKA_WINDOW_BACKEND','')
    if forced:return forced=='qt'
    if os.environ.get('SHIZUKA_DATA_DIR'):return False  # Legacy release fixtures.
    import pet
    return (Path(pet.ROOT_DIR)/'qt-windows/ShizukaWindows.exe').is_file()

def get_bridge(app):
    existing=getattr(app,'_qt_windows',None)
    if existing is None or existing.closed:
        existing=app._qt_windows=Bridge(app)
    return existing

def open_window(app,kind,**options):
    if getattr(app,'_qt_window_failed',False) or not enabled():return False
    try:
        get_bridge(app).show(kind,**options);return True
    except Exception as error:
        # Keep the original tools recoverable when the optional runtime fails.
        callback=getattr(app,'_record_notice',None)
        if callback:callback('Qt窗口未能启动，已使用原窗口：'+str(error),'界面')
        return False

def open_editor(app,item=None):
    if getattr(app,'_qt_window_failed',False) or not enabled():return False
    try:
        bridge=get_bridge(app);bridge.show('todos');bridge.send_editor((item or {}).get('id',''));return True
    except Exception as error:
        callback=getattr(app,'_record_notice',None)
        if callback:callback('Qt编辑器未能启动，已使用原编辑器：'+str(error),'界面')
        return False

class Bridge:
    def __init__(self,app):
        import pet
        self.app=app;self.root=app.root;self.app_root=Path(pet.ROOT_DIR)
        from qt_forms import install
        install(app)
        executable=self.app_root/'qt-windows/ShizukaWindows.exe'
        if os.environ.get('SHIZUKA_QT_SOURCE')=='1' and not getattr(sys,'frozen',False):
            command=[sys.executable,str(Path(__file__).with_name('qt_windows.py')),'--app-root',str(self.app_root)]
        elif executable.is_file():command=[str(executable)]
        elif not getattr(sys,'frozen',False):command=[sys.executable,str(self.app_root/'src/qt_windows.py')]
        else:raise FileNotFoundError('Qt窗口运行包缺失')
        self.command=command;self.incoming=queue.Queue();self.outgoing=queue.Queue()
        self.closed=False;self.opened=set();self.presented=set();self.selected='';self.sessions={};self.history_ids=[]
        self.last_history=None;self.last_poll=0;self.ready=False;self.errors=[];self.backend=None
        self.process=subprocess.Popen(command,cwd=self.app_root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        threading.Thread(target=self._write,name='qt-window-writer',daemon=True).start()
        threading.Thread(target=self._read,name='qt-window-reader',daemon=True).start()
        self.root.bind('<Destroy>',self._destroy,add='+')
        self.root.after(25,self._poll)
        self.app._chatlog_refresh=lambda:self.publish_history(force=True) if 'history' in self.opened else None
        from window_art import PREFERENCES
        self.preferences=dict(PREFERENCES)
        self.send(dict(type='style',**self.style()))
        self._status()

    def style(self):
        from window_art import catalog,PREFERENCES,ART_DIR
        cards=catalog();fixed=next((card for card in cards if card['file']==PREFERENCES['background_file']),None)
        return dict(background=str(ART_DIR/fixed['file']) if fixed else '',
                    backgrounds=[] if fixed else [str(ART_DIR/card['file']) for card in cards],blur=float(PREFERENCES['blur']),
                    darkness=float(PREFERENCES['darkness']))

    def send(self,value):
        if self.closed:raise RuntimeError('Qt窗口已关闭')
        self.outgoing.put(value)

    def _write(self):
        try:
            while True:
                value=self.outgoing.get()
                if value is None:break
                packet=(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
                if len(packet)>MAX_MESSAGE:raise ValueError('窗口数据过大，请减少单条材料内容')
                self.process.stdin.write(packet);self.process.stdin.flush()
        except (OSError,ValueError) as error:self.incoming.put(dict(type='pipe_error',message=str(error)))
        finally:
            try:self.process.stdin.close()
            except OSError:pass

    def _read(self):
        try:
            while True:
                line=self.process.stdout.readline(MAX_MESSAGE+1)
                if not line:break
                if len(line)>MAX_MESSAGE:raise ValueError('Qt返回数据超过限制')
                value=json.loads(line)
                if isinstance(value,dict):self.incoming.put(value)
        except (OSError,ValueError) as error:self.incoming.put(dict(type='pipe_error',message=str(error)))
        finally:self.incoming.put(dict(type='process_exit'))

    def _poll(self):
        if self.closed:return
        try:
            for _ in range(30):
                try:message=self.incoming.get_nowait()
                except queue.Empty:break
                kind=message.get('type')
                if kind=='request':self._request(message)
                elif kind=='ready':self.ready=True;self.backend=message.get('backend');self._status()
                elif kind=='presented':self.presented.add(message.get('window'));self._status()
                elif kind=='closed':self.opened.discard(message.get('window'));self._status()
                elif kind=='render_error':self.errors.append(message.get('message','Qt绘制错误'))
                elif kind in ('pipe_error','process_exit'):
                    reopen=set(self.opened);self.app._qt_window_failed=True
                    if self.opened:
                        text=message.get('message','Qt窗口进程已退出；如正在保存，请先核对待办再操作。')
                        self.errors.append(text)
                        self.app._record_notice(text,'界面')
                    self.shutdown()
                    if hasattr(self.app,'_qt_forms'):self.app._qt_forms.recover()
                    if 'history' in reopen:self.root.after_idle(self.app.show_chat_log)
                    if 'todos' in reopen:self.root.after_idle(self.app.show_todos)
                    return
            now=time.monotonic()
            if now-self.last_poll>2:
                self.last_poll=now
                if 'history' in self.opened:self.publish_history()
                from window_art import PREFERENCES
                if self.preferences!=PREFERENCES:
                    reset=self.preferences['background_file']!=PREFERENCES['background_file']
                    self.preferences=dict(PREFERENCES)
                    self.send(dict(type='style',reset_backgrounds=reset,**self.style()))
            self.root.after(25,self._poll)
        except Exception as error:
            self.errors.append(str(error))
            if not self.closed:
                try:self.root.after(100,self._poll)
                except Exception:self.shutdown()

    def _status(self,**extra):
        import pet
        value=dict(revision=REVISION,pid=self.process.pid,ready=self.ready,windows=sorted(self.opened),presented=sorted(self.presented),
                   transport='private-stdio',data_owner='main-application',backend=self.backend,**extra)
        (Path(pet.DATA_DIR)/'qt-window-runtime.json').write_text(json.dumps(value,indent=2),encoding='utf-8')

    def show(self,kind,**options):
        if self.process.poll() is not None:raise RuntimeError('Qt窗口进程已退出，请重新打开')
        self.opened.add(kind)
        if kind=='history':self.publish_history(force=True)
        elif kind=='todos':self.publish_todos()
        self.send(dict(type='open',window=kind,**options));self._status()

    def close(self,kind):
        if not self.closed:self.send(dict(type='close',window=kind))
        self.opened.discard(kind)

    def publish_history(self,force=False):
        notices=[{k:deepcopy(row[k]) for k in FIELDS if k in row} for row in self.app._workflow().notices()]
        with self.app._chat_lock:
            source=self.app._chat_log
            stamp=(len(source),source[-1].get('id') if source else '',source[-1].get('text') if source else '',
                   tuple((r.get('id'),r.get('read'),r.get('text')) for r in notices))
            if not force and stamp==self.last_history:return
            rows=[{k:deepcopy(row[k]) for k in FIELDS if k in row} for row in source
                  if row.get('role') in ('user','assistant') and row.get('kind')!='memory_summary']
        offset=0
        if not force and self.history_ids and len(rows)>=len(self.history_ids) and rows[len(self.history_ids)-1].get('id')==self.history_ids[-1]:
            offset=len(self.history_ids)-1
        self.send(dict(type='history',offset=offset,rows=rows[offset:],notices=notices))
        self.history_ids=[row.get('id') for row in rows];self.last_history=stamp

    def publish_todos(self):
        from todo_schedule import schedule_facts
        self.app._todo_init();rows=[]
        for item in self.app.todos:
            options=self.app._todo_options(item)
            rule=options.get('schedule',{}).get('rule')
            rows.append(dict(id=item['id'],text=item['text'],done=bool(item.get('done')),
                created=item.get('created',0),due=item.get('due'),on_boot=bool(item.get('on_boot')),
                category=options.get('category','生活'),schedule=schedule_facts(item,options),
                channels='＋'.join(label for key,label in [('desktop','桌面'),('weixin','微信')] if options.get(key,True)) or '不提醒',
                status=self.app._todo_state_label(item),note=options.get('manual_note',''),
                notes=deepcopy(options.get('notes',[])),recurring=bool(rule and not rule.get('until_done')),
                retry_state=options.get('notice',{}).get('weixin','')))
        self.send(dict(type='todos',rows=rows))

    def send_editor(self,ident=''):
        from todo_editing import editor_values,edit_token
        self.app._todo_init()
        item=next((r for r in self.app.todos if r['id']==ident),None) if ident else None
        if ident and not item:raise ValueError('这件事已被删除')
        options=self.app._todo_options(item) if item else {}
        initial=editor_values(item,options);session=uuid.uuid4().hex
        self.sessions.clear()  # Only one editor can be open.
        self.sessions[session]=dict(id=ident,initial=initial,token=edit_token(item,options),at=time.monotonic())
        self.send(dict(type='editor',session=session,id=ident,values=initial))

    def _request(self,message):
        rid=message.get('id');method=message.get('method');params=message.get('params',{})
        try:
            if not isinstance(params,dict):raise ValueError('请求内容无效')
            result=self.action(method,params)
            self.send(dict(type='result',id=rid,ok=True,value=result))
        except Exception as error:
            self.send(dict(type='result',id=rid,ok=False,error=str(error)))

    def action(self,method,params):
        app=self.app;ident=params.get('id','')
        if method=='form':return app._qt_forms.action(params)
        if method=='refresh':
            self.publish_history(force=True);self.publish_todos();return None
        if method=='chat':app.open_chat_input();return None
        if method=='feedback':
            if ident:
                row=next((r for r in app._chat_log if r.get('id')==ident),None)
                if not row:raise ValueError('原记录已不存在')
                app.show_reply_feedback(row)
            else:app.show_feedback()
            return None
        if method=='background':self.send(dict(type='shuffle_background',window=params.get('window','history')));return None
        if method=='context':
            from workflow_store import surrounding
            before=max(0,min(500,int(params.get('before',6))));after=max(0,min(500,int(params.get('after',6))))
            with app._chat_lock:rows,older,newer=surrounding(app._chat_log,ident,before,after)
            self.send(dict(type='context',id=ident,rows=[{k:r[k] for k in FIELDS if k in r} for r in rows],older=older,newer=newer))
            return None
        if method=='notice':
            row=next((r for r in app._workflow().notices() if r.get('id')==ident),None)
            if row:app.show_notice(row)
            return None
        if method=='selected':self.selected=ident;return None
        if method=='edit':self.send_editor(ident);return None
        if method=='save':
            from todo_editing import save_editor,edit_token
            session=self.sessions.get(params.get('session'))
            if not session or time.monotonic()-session['at']>3600:raise ValueError('编辑已过期，请重新打开')
            item=next((r for r in app.todos if r['id']==session['id']),None) if session['id'] else None
            if session['id'] and (item is None or edit_token(item,app._todo_options(item))!=session['token']):
                raise ValueError('待办在编辑期间已发生变化，请重新打开核对')
            record=save_editor(app,params.get('values',{}),session['id'],session['initial'])
            self.sessions.pop(params['session'],None);self.selected=record['id'];self.publish_todos()
            return dict(id=record['id'],category='已完成' if record.get('done') else app._todo_options(record).get('category','生活'))
        item=next((r for r in app.todos if r['id']==ident),None)
        if not item:raise ValueError('请先选中仍然存在的待办')
        if method=='done':app._todo_set_done(ident,not item.get('done'))
        elif method=='delete':app._todo_delete(ident)
        elif method=='end_series':app._todo_end_series(ident)
        elif method=='quick':app.show_todo_quick(ident)
        elif method=='focus':app._pomo_task_start(ident)
        elif method=='snooze':
            minutes=int(params.get('minutes',10))
            if not 1<=minutes<=1440:raise ValueError('稍后提醒支持1分钟到24小时')
            app._todo_snooze(ident,time.time()+minutes*60)
        elif method=='retry':
            notice=app._todo_options(item).get('notice',{});state=notice.get('weixin')
            if state not in ('failed','uncertain','waiting'):raise ValueError('这条待办没有需要重试的微信提醒')
            if state=='uncertain' and params.get('confirmed') is not True:raise ValueError('先核对微信，确认是否需要再次发送')
            notice.update(weixin='pending',error='');app._save_todo_details();app._todo_check_reminders()
        else:raise ValueError('不支持的窗口操作')
        self.publish_todos();return None

    def _destroy(self,event):
        if event.widget is self.root:self.shutdown()

    def shutdown(self):
        if self.closed:return
        self.closed=True;self.outgoing.put(None)
        def finish():
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.terminate()
        threading.Thread(target=finish,name='qt-window-stop',daemon=True).start()
