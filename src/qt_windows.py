"""Qt Quick renderer for the main application's history and todo tools."""
import argparse,json,os,random,sys,threading,time
from pathlib import Path
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
import PySide6
_dll=os.add_dll_directory(str(Path(PySide6.__file__).parent)) if os.name=='nt' else None
from PySide6 import QtQuickControls2
from PySide6.QtCore import QObject,QAbstractListModel,QModelIndex,Property,Signal,Slot,Qt,QUrl,QTimer,QCoreApplication,QEvent
from PySide6.QtGui import QGuiApplication,QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow,QSGRendererInterface

ROOT=Path(sys.executable).parent.parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
MAX_MESSAGE=32*1024*1024

class Rows(QAbstractListModel):
    fields=('rowId','message','heading','stamp','kind','category','done','schedule','channels','status','note','recurring')
    roles={int(Qt.UserRole)+i+1:field.encode() for i,field in enumerate(fields)}
    def __init__(self):super().__init__();self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def roleNames(self):return self.roles
    def data(self,index,role):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        field=self.roles.get(role)
        if field is None:return None
        field=field.decode();row=self.rows[index.row()]
        if field=='rowId':return str(row.get('id',''))
        if field=='message':return row.get('text','')
        if field=='heading':return '你' if row.get('role')=='user' else '静香' if row.get('role')=='assistant' else row.get('source','记录')
        if field=='stamp':
            stamp=time.strftime('%m-%d %H:%M',time.localtime(row.get('created',0)))
            return ('微信 · ' if str(row.get('kind','')).startswith('weixin') else '')+stamp
        if field in ('done','recurring'):return bool(row.get(field))
        return str(row.get(field,'') or '')
    def replace(self,rows):
        if rows==self.rows:return
        self.beginResetModel();self.rows=rows;self.endResetModel()

class Controller(QObject):
    stateChanged=Signal();styleChanged=Signal();editorOpened=Signal();contextOpened=Signal()
    activated=Signal(str)
    packet=Signal(dict)
    def __init__(self,app,emit):
        super().__init__();self.app=app;self.emit=emit;self.packet.connect(self.receive)
        self.history=Rows();self.todos=Rows();self.context=Rows()
        self.all_history=[];self.notices=[];self.all_todos=[]
        self.history_more=False;self.history_total=0
        self.history_query='';self.history_mode='对话';self.todo_category='生活';self.todo_query=''
        self.visible={'history':False,'todos':False,'editor':False,'context':False}
        self.style=dict(background='',backgrounds=[],blur=8,darkness=.64)
        self.window_backgrounds={};self.last_background=''
        self.background_overrides={};self.editor_data={};self.session='';self.edit_id='';self.saving=False
        self.selected='';self.sequence=0;self.pending_save=None;self.status=''
        self.context_id='';self.context_before=6;self.context_after=6;self.older=False;self.newer=False
    @Property(bool,notify=stateChanged)
    def historyVisible(self):return self.visible['history']
    @Property(bool,notify=stateChanged)
    def todosVisible(self):return self.visible['todos']
    @Property(bool,notify=stateChanged)
    def editorVisible(self):return self.visible['editor']
    @Property(bool,notify=stateChanged)
    def contextVisible(self):return self.visible['context']
    @Property(int,notify=stateChanged)
    def historyCount(self):return len(self.history.rows)
    @Property(bool,notify=stateChanged)
    def historyHasMore(self):return self.history_more and self.history_mode!='通知'
    @Property(int,notify=stateChanged)
    def historyTotal(self):
        if self.history_mode=='通知':return self.historyCount
        extra=sum(1 for r in self.notices if self.history_query.strip().casefold() in r.get('text','').casefold()) if self.history_mode=='全部记录' else 0
        return self.history_total+extra
    @Property(str,notify=stateChanged)
    def historyMode(self):return self.history_mode
    @Property(int,notify=stateChanged)
    def todoCount(self):return len(self.todos.rows)
    @Property(str,notify=stateChanged)
    def todoCategory(self):return self.todo_category
    @Property(str,notify=stateChanged)
    def selectedId(self):return self.selected
    @Property('QVariantMap',notify=stateChanged)
    def selectedTodo(self):
        row=next((r for r in self.all_todos if r['id']==self.selected),{})
        return dict(id=row.get('id',''),title=row.get('text',''),note=row.get('note',''),schedule=row.get('schedule',''),
            done=bool(row.get('done')),recurring=bool(row.get('recurring')),retry_state=row.get('retry_state',''),
            notes='\n\n'.join(str(n.get('text','')) for n in row.get('notes',[])))
    @Property('QVariantMap',notify=stateChanged)
    def editorInitial(self):return self.editor_data
    @Property(str,notify=stateChanged)
    def editingId(self):return self.edit_id
    @Property(bool,notify=stateChanged)
    def isSaving(self):return self.saving
    @Property(str,notify=stateChanged)
    def statusText(self):return self.status
    @Property(bool,notify=stateChanged)
    def hasOlder(self):return self.older
    @Property(bool,notify=stateChanged)
    def hasNewer(self):return self.newer
    @Property(int,notify=stateChanged)
    def contextFocusIndex(self):return next((i for i,r in enumerate(self.context.rows) if r.get('id')==self.context_id),0)
    @Property(float,notify=styleChanged)
    def blur(self):return float(self.style['blur'])
    @Property(float,notify=styleChanged)
    def darkness(self):return float(self.style['darkness'])
    @Slot(str,result=QUrl)
    def background(self,kind):
        if kind not in self.window_backgrounds:self._pick_background(kind)
        path=self.background_overrides.get(kind,self.window_backgrounds[kind])
        return QUrl.fromLocalFile(path) if path else QUrl()
    def _pick_background(self,kind):
        previous=self.window_backgrounds.get(kind,'')
        cards=self.style['backgrounds']
        choices=[path for path in cards if path not in (previous,self.last_background)]
        if not choices:choices=[path for path in cards if path!=previous] or cards
        path=random.choice(choices) if choices else self.style['background']
        self.window_backgrounds[kind]=path;self.last_background=path
    def open_background(self,kind):
        self.background_overrides.pop(kind,None);self._pick_background(kind);self.styleChanged.emit()
    def forget_background(self,kind):
        self.window_backgrounds.pop(kind,None);self.background_overrides.pop(kind,None)
    @Slot(str,'QVariantMap',result=int)
    def request(self,method,params):
        self.sequence+=1;self.emit(dict(type='request',id=self.sequence,method=method,params=dict(params)))
        return self.sequence
    @Slot(str,str)
    def filterHistory(self,query,mode):
        changed=query!=self.history_query
        self.history_query=query;self.history_mode=mode;self._history()
        if changed:self.request('history_filter',dict(query=query))
    @Slot()
    def loadOlderHistory(self):
        self.request('history_more',dict(query=self.history_query))
    def _history(self):
        rows=self.notices if self.history_mode=='通知' else self.all_history
        if self.history_mode=='全部记录':rows=sorted(self.all_history+self.notices,key=lambda r:r.get('created',0))
        needle=self.history_query.strip().casefold()
        self.history.replace([r for r in rows if not needle or needle in r.get('text','').casefold()]);self.stateChanged.emit()
    @Slot(str,str)
    def filterTodos(self,query,category):
        self.todo_query=query;self.todo_category=category;self._todos()
    def _todos(self):
        needle=self.todo_query.strip().casefold()
        rows=[r for r in self.all_todos if ('已完成' if r['done'] else r['category'])==self.todo_category
              and (not needle or needle in (r['text']+'\n'+r.get('note','')).casefold())]
        self.todos.replace(sorted(rows,key=lambda r:(r.get('due') or 9e18,r.get('created',0))))
        if self.selected and not any(r['id']==self.selected for r in rows):self.selected=''
        self.stateChanged.emit()
    @Slot(str)
    def selectTodo(self,ident):self.selected=ident;self.stateChanged.emit();self.request('selected',dict(id=ident))
    @Slot(str)
    def copy(self,text):self.app.clipboard().setText(text)
    @Slot()
    def copyHistory(self):self.copy('\n\n'.join(('你' if r.get('role')=='user' else '静香' if r.get('role')=='assistant' else r.get('source','通知'))+'：'+r.get('text','') for r in self.history.rows))
    @Slot(str)
    def close(self,kind):
        if kind.startswith('form-'):
            self.request('form',dict(form=kind,action='escape'));return
        self.visible[kind]=False
        if kind=='todos':self.visible['editor']=False
        self.stateChanged.emit();self.emit(dict(type='closed',window=kind))
    @Slot('QVariantMap')
    def save(self,values):
        if self.saving:return
        self.saving=True;self.status='正在保存…'
        self.pending_save=self.request('save',dict(session=self.session,values=dict(values)));self.stateChanged.emit()
    @Slot(str)
    def openContext(self,ident):
        self.context_id=ident;self.context_before=6;self.context_after=6;self.moreContext(0)
    @Slot(int)
    def moreContext(self,side):
        if side<0:self.context_before=min(500,self.context_before+20)
        if side>0:self.context_after=min(500,self.context_after+20)
        self.request('context',dict(id=self.context_id,before=self.context_before,after=self.context_after))
    @Slot(dict)
    def receive(self,message):
        if hasattr(self,'forms'):
            try:
                if self.forms.receive(message):return
            except Exception as error:
                self.emit(dict(type='pipe_error',message='Qt工具窗口创建失败：'+str(error)));return
        kind=message.get('type')
        if kind=='style':
            before=(self.style['background'],tuple(self.style['backgrounds']))
            if message.get('window'):self.background_overrides[message['window']]=message.get('background','')
            else:self.style.update({k:message[k] for k in self.style if k in message})
            if message.get('reset_backgrounds') or before!=(self.style['background'],tuple(self.style['backgrounds'])):
                self.background_overrides.clear();self.window_backgrounds.clear()
            self.styleChanged.emit()
        elif kind=='shuffle_background':self.open_background(message['window'])
        elif kind=='open':
            window=message['window']
            if not self.visible[window]:self.open_background(window)
            self.visible[window]=True
            if window=='history' and message.get('mode'):self.history_mode=message['mode'];self._history()
            self.stateChanged.emit()
            self.activated.emit(window)
            self.emit(dict(type='opened',window=window))
        elif kind=='close':self.close(message['window'])
        elif kind=='history':
            if message.get('query',self.history_query)!=self.history_query:return
            self.history_more=message.get('has_more',False);self.history_total=message.get('total',0)
            offset=message.get('offset',0);self.all_history=self.all_history[:offset]+message['rows'];self.notices=message.get('notices',[]);self._history()
        elif kind=='todos':self.all_todos=message['rows'];self._todos()
        elif kind=='editor':
            if not self.visible['editor']:self.open_background('editor')
            self.editor_data=message['values'];self.session=message['session'];self.edit_id=message.get('id','')
            self.saving=False;self.status='';self.visible['editor']=True;self.stateChanged.emit();self.editorOpened.emit()
            self.activated.emit('editor')
        elif kind=='context':
            if not self.visible['context']:self.open_background('context')
            self.context.replace(message['rows']);self.older=message['older'];self.newer=message['newer']
            self.visible['context']=True;self.stateChanged.emit();self.contextOpened.emit()
            self.activated.emit('context')
        elif kind=='result':
            if message.get('id')==self.pending_save:
                self.saving=False;self.pending_save=None
                if message['ok']:
                    self.visible['editor']=False;value=message.get('value') or {};self.selected=value.get('id','')
                    self.todo_category=value.get('category','生活');self.status='已保存';self._todos()
                else:self.status='未保存：'+message.get('error','请重试')
            elif not message.get('ok'):self.status=message.get('error','操作未完成')
            self.stateChanged.emit()
        elif kind=='shutdown':self.app.quit()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--forms-self-test',action='store_true');parser.add_argument('--report',type=Path)
    parser.add_argument('--app-root',type=Path,default=ROOT)
    args=parser.parse_args()
    app=QApplication(sys.argv);app.setQuitOnLastWindowClosed(False);app.setApplicationName('Shizuka')
    app.setWindowIcon(QIcon(str(args.app_root/'assets/pet_icon.ico')))
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    def emit(value):
        sys.stdout.buffer.write((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8'));sys.stdout.buffer.flush()
    controller=Controller(app,emit);engine=QQmlApplicationEngine();errors=[]
    engine.warnings.connect(lambda messages:errors.extend(m.toString() for m in messages))
    engine.warnings.connect(lambda messages:[emit(dict(type='render_error',message=m.toString())) for m in messages])
    context=engine.rootContext()
    for name,value in [('controller',controller),('historyModel',controller.history),('todoModel',controller.todos),('contextModel',controller.context)]:context.setContextProperty(name,value)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('QtTools.qml'))))
    if not engine.rootObjects():raise RuntimeError('Qt工具窗口加载失败：'+str(errors))
    windows={}
    def initialize(obj):
        obj.setPersistentGraphics(True);obj.setPersistentSceneGraph(True)
        screen=app.primaryScreen()
        if screen:
            obj.setScreen(screen);area=screen.availableGeometry()
            obj.resize(min(obj.width(),max(obj.minimumWidth(),area.width()-60)),min(obj.height(),max(obj.minimumHeight(),area.height()-60)))
            obj.setPosition(area.x()+max(0,(area.width()-obj.width())//2),area.y()+max(0,(area.height()-obj.height())//2))
        if os.name=='nt':
            import ctypes
            for attribute,color in [(3,1),(20,1),(35,0x462c14),(36,0xfcf5f0)]:
                value=ctypes.c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(obj.winId())),attribute,ctypes.byref(value),4)
    from qt_form_models import FormWindows
    controller.forms=FormWindows(app,engine,controller,initialize,emit)
    for obj in engine.rootObjects()[0].children():
        if isinstance(obj,QQuickWindow):
            windows[obj.objectName()]=obj;obj.setPersistentGraphics(True);obj.setPersistentSceneGraph(True)
            screen=app.primaryScreen()
            if screen:
                obj.setScreen(screen)
                area=screen.availableGeometry()
                obj.resize(min(obj.width(),max(obj.minimumWidth(),area.width()-60)),
                           min(obj.height(),max(obj.minimumHeight(),area.height()-60)))
                obj.setPosition(area.x()+max(0,(area.width()-obj.width())//2),
                                area.y()+max(0,(area.height()-obj.height())//2))
            if os.name=='nt':
                import ctypes
                value=ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(obj.winId())),3,ctypes.byref(value),4)
                for attribute,color in [(20,1),(35,0x462c14),(36,0xfcf5f0)]:
                    value=ctypes.c_int(color)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(obj.winId())),attribute,ctypes.byref(value),4)
    def activate(kind):
        window=windows.get(kind)
        if window and window.isVisible():
            if window.windowState()==Qt.WindowMinimized:window.showNormal()
            window.raise_();window.requestActivate()
    controller.activated.connect(activate)
    presented=set()
    def report_frame(kind):
        if kind not in presented:
            presented.add(kind);emit(dict(type='presented',window=kind))
    for kind,window in windows.items():window.frameSwapped.connect(lambda kind=kind:report_frame(kind))
    def stdin():
        try:
            for line in iter(lambda:sys.stdin.buffer.readline(MAX_MESSAGE+1),b''):
                if len(line)>MAX_MESSAGE:break
                packet=json.loads(line)
                if isinstance(packet,dict):controller.packet.emit(packet)
        except (OSError,ValueError):pass
        finally:controller.packet.emit(dict(type='shutdown'))
    if args.forms_self_test:
        from qt_forms_test import run
        run(app,controller,args.app_root,args.report,errors)
    elif args.self_test:
        from qt_windows_test import run
        run(app,controller,windows,args.app_root,args.report,errors)
    else:
        threading.Thread(target=stdin,name='qt-window-input',daemon=True).start()
        emit(dict(type='ready',backend='Direct3D11',windows=list(windows)))
    result=app.exec()
    for state in controller.forms.forms.values():state.window.deleteLater()
    for obj in engine.rootObjects():obj.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    return result

if __name__=='__main__':raise SystemExit(main())
