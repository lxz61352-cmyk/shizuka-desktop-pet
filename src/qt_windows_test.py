"""Fictional GPU/UI exercise, without credentials or private data."""
import json,time
from pathlib import Path
from PySide6.QtCore import QObject,QTimer
from todo_editing import editor_values

def run(app,controller,windows,root,report_path,errors):
    assert set(windows)=={'history','todos','editor','context'},list(windows)
    root=Path(root);report_path=Path(report_path or root/'build/qt-windows-self-test.json')
    cards=json.loads((root/'assets/backgrounds/shizuka/manifest.json').read_text('utf-8-sig'))['cards']
    image=root/'assets/backgrounds/shizuka'/cards[0]['file']
    controller.receive(dict(type='style',background=str(image),blur=8,darkness=.64))
    history=[dict(id='m'+str(i),role='user' if i%2 else 'assistant',created=1780000000+i,kind='weixin' if i%4==0 else 'chat',
        text=f'fixture-{i+1}\n'+('虚构消息，用来验证GPU背景、滚动和窗口缩放。'*(1+i%4))) for i in range(5000)]
    todos=[dict(id='t'+str(i),text=f'fictional-task-{i+1}',created=1780000000+i,due=None,on_boot=False,done=False,
        category='生活' if i%2 else '研究',schedule='未安排时间',channels='桌面',status='未安排时间',note='虚构备注',notes=[],recurring=False,retry_state='') for i in range(1200)]
    controller.receive(dict(type='history',offset=0,rows=history,notices=[]))
    controller.receive(dict(type='todos',rows=todos))
    controller.receive(dict(type='open',window='history'))
    controller.receive(dict(type='open',window='todos'))
    packets=[];controller.emit=packets.append
    frames={name:0 for name in windows};samples=[];textures={name:set() for name in windows}
    for name,window in windows.items():window.frameSwapped.connect(lambda name=name:frames.__setitem__(name,frames[name]+1))
    timer=QTimer(app);state={'n':0};started=time.monotonic()
    def tick():
        try:
            n=state['n'];state['n']+=1
            if n<12:
                if n==0:assert all(windows[k].isVisible() for k in ('history','todos')),'First open must show windows without showNormal'
                for name in ('history','todos'):
                    window=windows[name]
                    if n%2:window.showMaximized()
                    else:window.showNormal()
            elif n==12:
                controller.filterHistory('fixture-2501','对话');assert controller.historyCount==1
                controller.filterHistory('','对话');assert controller.historyCount==5000
                controller.filterTodos('fictional-task-1002','生活');assert controller.todoCount==1
                controller.filterTodos('','生活');assert controller.todoCount==600
                controller.selectTodo('t1');assert controller.selectedTodo['id']=='t1'
                initial=editor_values(None,{},1780000000)
                controller.receive(dict(type='editor',session='fictional-session',id='',values=initial))
                controller.context_id='m22'
                controller.receive(dict(type='context',id='m22',rows=history[16:29],older=True,newer=True))
            elif n<21:
                for name,window in windows.items():
                    window.resize(760+(n%5)*35,590+(n%4)*30)
                    window.setProperty('localBlur',(n%6)/10)
                    window.setProperty('localDarkness',.35+(n%4)/10)
            elif n==21:
                title=windows['editor'].findChild(QObject,'todoTitle');note=windows['editor'].findChild(QObject,'todoNote')
                assert title and note,'Editor fields were not created'
                title.setProperty('text','可编辑的虚构标题');note.setProperty('text','透明区域保留完整备注')
                # QML's actual save handler assembles the field values.
                save=windows['editor'].findChild(QObject,'todoSave');save.clicked.emit()
                packet=packets[-1]
                assert packet['method']=='save' and packet['params']['values']['title']=='可编辑的虚构标题',packet
                assert packet['params']['values']['note']=='透明区域保留完整备注',packet
                controller.receive(dict(type='result',id=packet['id'],ok=False,error='虚构校验失败'))
                assert controller.editorVisible and not controller.isSaving
                assert title.property('text')=='可编辑的虚构标题'
            else:
                timer.stop()
                assert not errors,errors
                delegates={name:windows[name].findChild(QObject,list_name).property('maxDelegates') for name,list_name in [('history','historyList'),('todos','todoList')]}
                assert 0<delegates['history']<100 and 0<delegates['todos']<100,delegates
                assert all(frames[name]>2 for name in windows),frames
                for name,window in windows.items():
                    assert window.rendererInterface().graphicsApi().name=='Direct3D11'
                    assert len(textures[name])==1,(name,textures[name])
                replacement=root/'assets/backgrounds/shizuka'/cards[1]['file']
                controller.receive(dict(type='style',window='history',background=str(replacement)))
                assert windows['history'].isVisible(),'Changing artwork must retain the current window and frame'
                report=dict(backend='Direct3D11',messages=5000,todos=1200,max_delegates=delegates,
                    frames=frames,texture_sizes={name:list(values) for name,values in textures.items()},
                    samples=samples,errors=errors,elapsed=round(time.monotonic()-started,2),checks=[
                        'four real QML windows render','virtualized history and todo lists','search and category filters',
                        'maximized and restored windows','fixed background effect dimensions','transparent editable title/note fields',
                        'actual QML save request','failed save keeps editor content','background replacement keeps window visible'])
                report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
                windows['history'].grabWindow().save(str(report_path.with_suffix('.png')))
                print(json.dumps(dict(success=True,backend=report['backend'],max_delegates=delegates,checks=len(report['checks']))),flush=True)
                app.exit(0);return
            for name,window in windows.items():
                if not window.isVisible() or frames[name]<1:continue
                texture=window.property('backgroundTextureSize');textures[name].add((texture.width(),texture.height()))
                pixels=window.grabWindow()
                assert not pixels.isNull(),name
                colors=[pixels.pixelColor(round(pixels.width()*x/10),round(pixels.height()*y/10)).getRgb()[:3] for x in range(1,10) for y in range(1,10)]
                black=sum(max(c)<8 for c in colors)/len(colors)
                blank=sum(c==(16,24,36) for c in colors)/len(colors)
                assert black<.8 and blank<.8,(name,black,blank)
                samples.append(dict(window=name,size=[pixels.width(),pixels.height()],black_fraction=black,blank_fraction=blank))
        except Exception as error:
            timer.stop();print(repr(error),flush=True);app.exit(1)
    timer.timeout.connect(tick)
    QTimer.singleShot(900,lambda:timer.start(120))
