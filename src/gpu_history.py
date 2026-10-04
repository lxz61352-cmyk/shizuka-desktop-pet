"""Isolated Qt Quick history trial: GPU background and recycled message rows.

No conversation requests, credential access or changes to application settings.
"""
import argparse,json,os,sys,time,statistics,math
from pathlib import Path

ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
import PySide6
_dll_directory=os.add_dll_directory(str(Path(PySide6.__file__).parent)) if os.name=='nt' else None
from PySide6 import QtQuickControls2
from PySide6.QtCore import QAbstractListModel,QModelIndex,QObject,Qt,Property,Signal,Slot,QTimer,QUrl,QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow,QSGRendererInterface
from window_composition import disable_transitions


class Messages(QAbstractListModel):
    roles={Qt.UserRole+1:b'message',Qt.UserRole+2:b'heading',Qt.UserRole+3:b'stamp',Qt.UserRole+4:b'rowId'}
    def __init__(self,rows):
        super().__init__();self.all_rows=rows;self.rows=rows
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def roleNames(self):return self.roles
    def data(self,index,role):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.UserRole+1:return row.get('text','')
        if role==Qt.UserRole+2:return '你' if row.get('role')=='user' else 'Shizuka' if row.get('role')=='assistant' else row.get('source','记录')
        if role==Qt.UserRole+3:return time.strftime('%m-%d %H:%M',time.localtime(row.get('created',0)))
        if role==Qt.UserRole+4:return str(row.get('id',index.row()))
    def search(self,text):
        self.beginResetModel();needle=text.strip().casefold()
        self.rows=[row for row in self.all_rows if needle in row.get('text','').casefold()] if needle else self.all_rows
        self.endResetModel()


class Controller(QObject):
    countChanged=Signal()
    def __init__(self,app,rows):
        super().__init__();self.app=app;self.model=Messages(rows)
    @Property(int,notify=countChanged)
    def count(self):return len(self.model.rows)
    @Slot(str)
    def search(self,text):self.model.search(text);self.countChanged.emit()
    @Slot(str)
    def copy(self,text):self.app.clipboard().setText(text)
    @Slot()
    def copyAll(self):self.copy('\n\n'.join(('你' if row.get('role')=='user' else 'Shizuka')+'：'+row.get('text','') for row in self.model.rows))


def load_inputs(fixture,root):
    # Read data directly: importing the Tk pet would bring its entire runtime
    # into this independent renderer and make the preview unnecessarily large.
    art_dir=root/'assets/backgrounds/shizuka'
    prefs={'blur':8,'darkness':.64,'background_file':''}
    data_root=Path(os.environ.get('SHIZUKA_DATA_DIR',str(root/'data')))
    settings=data_root/'experience-settings.json'
    if settings.is_file():
        try:
            saved=json.loads(settings.read_text('utf-8-sig'))
            if isinstance(saved,dict):prefs.update({key:saved[key] for key in prefs if key in saved})
        except (OSError,ValueError):pass
    for key,high in [('blur',64),('darkness',1)]:
        try:
            value=float(prefs[key]);prefs[key]=max(0,min(high,value)) if math.isfinite(value) else 0
        except (ValueError,TypeError):prefs[key]=0
    if fixture:
        rows=[dict(id=str(index),role='user' if index%2 else 'assistant',created=1780000000+index,
                   text=f'第 {index+1} 条测试消息\n'+('这是一条虚构消息，用来检查背景加载、滚动和窗口拉伸。'*(1+index%4))) for index in range(5000)]
    else:
        from character_packs import selected_pack
        pack,_=selected_pack(root/'characters',data_root/'settings.json')
        if pack is None:raise ValueError('No active character pack was found')
        history=pack.data_directory(data_root)/'对话记录/对话记录.json'
        rows=json.loads(history.read_text('utf-8-sig')) if history.is_file() else []
    if not isinstance(rows,list):raise ValueError('History must be a list of messages')
    rows=[row for row in rows if isinstance(row,dict) and isinstance(row.get('text'),str)]
    cards=json.loads((art_dir/'manifest.json').read_text('utf-8-sig'))['cards']
    cards=[card for card in cards if Path(card['file']).name==card['file'] and (art_dir/card['file']).is_file()]
    if not cards:raise ValueError('No background artwork was found')
    card=next((card for card in cards if card['file']==prefs['background_file']),cards[0])
    return rows,prefs,art_dir/card['file']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',action='store_true')
    parser.add_argument('--app-root',type=Path,default=ROOT)
    parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args();rows,prefs,image=load_inputs(args.fixture or args.self_test,args.app_root)
    if args.self_test and args.report is None:args.report=args.app_root/'build/gpu-self-test.json'
    started=time.perf_counter();app=QGuiApplication(sys.argv);app.setApplicationName('Shizuka')
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    controller=Controller(app,rows);engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('historyController',controller)
    engine.rootContext().setContextProperty('messageModel',controller.model)
    engine.rootContext().setContextProperty('backgroundUrl',QUrl.fromLocalFile(str(image)))
    engine.rootContext().setContextProperty('initialBlur',float(prefs['blur']))
    engine.rootContext().setContextProperty('initialDarkness',float(prefs['darkness']))
    engine.rootContext().setContextProperty('fixtureMode',args.fixture or args.self_test)
    errors=[];engine.warnings.connect(lambda messages:errors.extend(message.toString() for message in messages))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('GpuHistory.qml'))))
    if not engine.rootObjects():raise RuntimeError('GPU history QML failed to load: '+str(errors))
    window=engine.rootObjects()[0]
    window.setPersistentGraphics(True);window.setPersistentSceneGraph(True)
    native_transitions_disabled=disable_transitions(int(window.winId()))
    frames=[];first_frame=[];updates=[];maximize_samples=[];texture_sizes=set()
    def swapped():
        now=time.perf_counter();frames.append(now)
        if not first_frame:first_frame.append(round((now-started)*1000,1))
    window.frameSwapped.connect(swapped)
    if args.self_test:
        state={'step':0};timer=QTimer(app)
        def step():
            try:
                n=state['step'];state['step']+=1
                tick=time.perf_counter()
                if n<45:
                    window.resize(QSize(850+(n%12)*15,610+(n%9)*8))
                    window.setProperty('blurAmount',(n%30)/30)
                    window.setProperty('darknessAmount',.3+(n%20)/40)
                    window.setProperty('scrollFraction',(n%10)/10)
                    updates.append(round((time.perf_counter()-tick)*1000,2))
                elif n<69:
                    if n>45:
                        pixels=window.grabWindow()
                        assert not pixels.isNull(),'Maximize/restore frame is empty'
                        colors=[pixels.pixelColor(round(pixels.width()*x/10),round(pixels.height()*y/10)).getRgb()[:3]
                            for x in range(1,10) for y in range(1,10)]
                        black=sum(max(color)<8 for color in colors)/len(colors)
                        blank=sum(color==(16,24,36) for color in colors)/len(colors)
                        assert black<.8 and blank<.8,('Blank maximize frame',black,blank)
                        maximize_samples.append(dict(size=[pixels.width(),pixels.height()],black_fraction=black,blank_fraction=blank))
                    texture=window.property('backgroundTextureSize');texture_sizes.add((texture.width(),texture.height()))
                    if n%2:window.showMaximized()
                    else:window.showNormal()
                    timer.setInterval(120)
                else:
                    timer.stop();api=window.rendererInterface().graphicsApi().name
                    assert api=='Direct3D11',api
                    assert window.property('backgroundStatus')==1,'Background failed to load'
                    assert 0<window.property('maxDelegates')<100,'Delegate count is unbounded'
                    assert len(frames)>10,'Frames were not presented'
                    assert native_transitions_disabled,'Native transition policy was not applied'
                    assert len(texture_sizes)==1,('Background effect texture changed size',texture_sizes)
                    assert len(maximize_samples)>=20,'Maximize/restore was not exercised'
                    controller.search('第 2501 条');assert controller.count==1
                    controller.search('');assert controller.count==5000
                    assert not errors,errors
                    args.report.parent.mkdir(parents=True,exist_ok=True)
                    screenshot=args.report.with_suffix('.png');assert window.grabWindow().save(str(screenshot))
                    intervals=[(b-a)*1000 for a,b in zip(frames,frames[1:])]
                    report=dict(backend=api,messages=5000,first_frame_ms=first_frame[0],frames=len(frames),
                        median_frame_interval_ms=round(statistics.median(intervals),2),
                        p95_frame_interval_ms=round(sorted(intervals)[int(len(intervals)*.95)],2),
                        max_main_update_ms=max(updates),max_delegates=window.property('maxDelegates'),errors=errors,
                        native_transitions_disabled=native_transitions_disabled,
                        maximize_restore_samples=maximize_samples,background_texture_sizes=list(texture_sizes))
                    args.report.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
                    app.exit(0)
            except Exception as error:
                timer.stop();print(repr(error),flush=True);app.exit(1)
        QTimer.singleShot(700,lambda:(timer.timeout.connect(step),timer.start(20)))
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
