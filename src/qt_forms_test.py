"""Own-window GPU, virtual list and dialog regression fixture; no desktop access."""
import ctypes,json,time,traceback
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,QMetaObject,Q_ARG,Qt
from PySide6.QtQml import QQmlEngine,QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QMessageBox

def run(app,controller,root,report,errors):
    checks=[];metrics={};packets=[];original=controller.emit;controller.emit=packets.append
    controller.forms.emit=packets.append;controller.forms.dialogs.emit=packets.append
    ident='form-fixture';start=time.monotonic();phase=[0];window=[None];field=[None];geometry=[]
    card=next((root/'assets/backgrounds/shizuka').glob('*.webp'))
    controller.receive(dict(type='style',background=str(card),blur=8,darkness=.64))
    def node(ident,kind,x,y,width,height,**values):
        value=dict(id=ident,kind=kind,x=x,y=y,width=width,height=height,clip=[0,0,900,660],enabled=True,text='',value='',image='',ackSequence=0)
        value.update(values);return value
    nodes=[node('title','label',20,10,600,35,title=True,text='虚构 Qt 工具窗口'),
           node('field','field',20,60,500,36,value='初始虚构文字',secret=False,readonly=False),
           node('button','button',550,60,150,36,text='虚构按钮'),
           node('text','text',20,112,500,80,value='虚构多行内容\n第二行',readonly=False,scrollToEnd=0),
           node('combo','combo',550,112,280,36,value='随机',choices=['随机','card-01.webp','card-02.webp'],editable=False),
           node('table','list',20,212,830,410,rows=[dict(id=str(i),cells=[str(i),'虚构记录 '+str(i)]) for i in range(5000)],headings=['序号','内容'],selection=[],multiple=True)]
    packet=dict(type='form',form=ident,title='Shizuka · 虚构工具测试',width=900,height=660,minimumWidth=400,minimumHeight=350,visible=True,nodes=nodes,focus='')
    controller.receive(packet)
    def items(win):
        result=[]
        def visit(item):
            result.append(item)
            for child in item.childItems():visit(child)
        visit(win.contentItem());return result
    def find(win,name):return next((item for item in items(win) if item.objectName()==name),None)
    def finish():
        controller.emit=original
        result=dict(checks=checks,errors=list(errors),metrics=metrics)
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(checks=len(checks),errors=len(errors),metrics=metrics)),flush=True)
        app.exit(1 if errors else 0)
    def poll():
        try:
            if time.monotonic()-start>25:raise AssertionError('Own form test timed out')
            if phase[0]==3:
                assert ident not in controller.forms.forms
                checks.append('Dynamic tool window teardown releases its model and window')
                timer.stop();finish();return
            state=controller.forms.forms[ident];win=state.window;window[0]=win
            if phase[0]==4:
                combo=find(win,'combo-combo')
                context=QQmlEngine.contextForObject(combo)
                expression=QQmlExpression(context,combo,'popup.contentItem.itemAtIndex(1) ? popup.contentItem.itemAtIndex(1).contentItem.color : undefined')
                color,undefined=expression.evaluate();assert not expression.hasError()
                if undefined:return
                assert color.lightnessF()<.3
                expression=QQmlExpression(context,combo,'popup.contentItem.itemAtIndex(1).contentItem.font.bold')
                bold,undefined=expression.evaluate();assert not undefined and not bold
                expression=QQmlExpression(QQmlEngine.contextForObject(combo),combo,'popup.close()')
                expression.evaluate();assert not expression.hasError()
                checks.append('White dropdown uses dark unbolded text and a contrasting highlighted row')
                metrics['comboTested']=True;phase[0]=0;return
            if phase[0]==0:
                if not win.isVisible() or not win.property('backgroundPrimed'):return
                if not metrics.get('comboTested'):
                    combo=find(win,'combo-combo')
                    expression=QQmlExpression(QQmlEngine.contextForObject(combo),combo,'popup.open()')
                    expression.evaluate();assert not expression.hasError()
                    phase[0]=4;return
                area=app.primaryScreen().availableGeometry();assert win.screen()==app.primaryScreen() and area.contains(win.position())
                style=ctypes.windll.user32.GetWindowLongW(ctypes.c_void_p(int(win.winId())),-16)
                assert style&0x00c00000 and style&0x00020000 and style&0x00010000 and style&0x00080000
                checks.append('Primary-monitor window has native caption, minimize, maximize, system menu and close controls')
                win.grabWindow().save(str(report.with_suffix('.png')))
                metrics['items']=[item.objectName() for item in items(win) if item.objectName()][:40]
                field[0]=find(win,'field-field');assert field[0]
                metrics['initialTexture']=str(win.property('backgroundTextureSize'))
                table=find(win,'table-table');assert table
                delegates=[item for item in items(win) if item.objectName().startswith('row-')]
                assert len(delegates)<50;metrics['listDelegates']=len(delegates)
                checks.append('Five thousand rows use fewer than fifty visible/recycled delegates')
                button=find(win,'button-button');assert QMetaObject.invokeMethod(button,'clicked')
                assert any(p.get('method')=='form' and p['params'].get('action')=='invoke' for p in packets)
                field[0].forceActiveFocus();field[0].setProperty('text','输入中的虚构文字')
                assert QMetaObject.invokeMethod(field[0],'textEdited')
                assert any(p.get('method')=='form' and p['params'].get('action')=='edit' and p['params'].get('value')=='输入中的虚构文字' for p in packets)
                checks.append('Displayed Qt button and field emit original main-application actions')
                nodes[1]['value']='输入中的虚构文字';nodes[1]['ackSequence']=1;controller.receive(packet)
                assert field[0] is find(win,'field-field') and field[0].hasActiveFocus()
                checks.append('Acknowledged field updates preserve delegate identity and input focus')
                win.grabWindow().save(str(report.with_suffix('.png')))
                geometry.append(win.size());win.showMaximized();phase[0]=1;return
            if phase[0]==1:
                assert win.isVisible() and str(win.property('backgroundTextureSize'))==metrics['initialTexture']
                win.showNormal();win.resize(1000,710);phase[0]=2;return
            if phase[0]==2:
                assert win.isVisible() and str(win.property('backgroundTextureSize'))==metrics['initialTexture']
                checks.append('Maximize, restore and resize retain the same background texture')
                before=len(packets);win.close()
                close_requests=[p for p in packets[before:] if p.get('method')=='form' and p['params'].get('action') in ('close','escape')]
                assert len(close_requests)==1 and win.isVisible(),close_requests
                checks.append('Native close waits for one original close callback and preserves a cancelled window')
                dialogs=controller.forms.dialogs
                dialogs.show(dict(dialog='confirm',kind='Message',options=dict(type='yesno',message='虚构确认',title='测试')))
                dialog=dialogs.active['confirm'];dialog.button(QMessageBox.No).click()
                assert any(p.get('type')=='form_dialog_result' and p.get('value')=='no' for p in packets)
                dialogs.show(dict(dialog='file',kind='Open',options=dict(title='虚构文件选择',initialdir=str(root/'build'),filetypes=[['JSON','*.json']])) )
                dialog=dialogs.active['file'];dialog.reject()
                assert any(p.get('type')=='form_dialog_result' and p.get('dialog')=='file' and p.get('value')=='' for p in packets)
                checks.append('Qt confirmation and file dialogs return original no/cancel results without side effects')
                controller.receive(dict(type='form_remove',form=ident));phase[0]=3;return
            if phase[0]==3:
                assert ident not in controller.forms.forms
                checks.append('Dynamic tool window teardown releases its model and window')
                timer.stop();finish()
        except Exception:
            errors.append(traceback.format_exc());timer.stop();finish()
    timer=QTimer(app);timer.timeout.connect(poll);timer.start(160)
