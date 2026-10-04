"""Incremental Qt models: edits keep their delegate, focus and IME session."""
from PySide6.QtCore import QObject,QAbstractListModel,QModelIndex,Property,Signal,Slot,Qt,QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickWindow
from pathlib import Path

class Objects(QAbstractListModel):
    roles={int(Qt.UserRole)+1:b'node',int(Qt.UserRole)+2:b'rowModel'}
    def __init__(self,parent=None):super().__init__(parent);self.values=[];self.child_models={}
    def roleNames(self):return self.roles
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.values)
    @Slot(int,int,result='QVariantList')
    def selectionRange(self,first,last):return [r['id'] for r in self.values[max(0,min(first,last)):max(first,last)+1]]
    def data(self,index,role):
        if not index.isValid() or not 0<=index.row()<len(self.values):return None
        value=self.values[index.row()]
        if role==int(Qt.UserRole)+1:return value
        if role==int(Qt.UserRole)+2:return self.child_models.get(value['id'])
    def replace(self,values):
        wanted={r['id'] for r in values}
        for index in range(len(self.values)-1,-1,-1):
            if self.values[index]['id'] not in wanted:
                self.beginRemoveRows(QModelIndex(),index,index);self.values.pop(index);self.endRemoveRows()
        for index,value in enumerate(values):
            value=dict(value)
            if 'rows' in value:
                key=value['id']
                model=self.child_models.get(key)
                if model is None:model=self.child_models[key]=Objects(self)
                model.replace(value.pop('rows'))
            if index>=len(self.values) or self.values[index]['id']!=value['id']:
                previous=next((i for i in range(index,len(self.values)) if self.values[i]['id']==value['id']),None)
                if previous is not None:
                    self.beginMoveRows(QModelIndex(),previous,previous,QModelIndex(),index)
                    self.values.insert(index,self.values.pop(previous));self.endMoveRows()
                else:
                    self.beginInsertRows(QModelIndex(),index,index);self.values.insert(index,value);self.endInsertRows()
            if self.values[index]!=value:
                self.values[index]=value;self.dataChanged.emit(self.index(index),self.index(index),list(self.roles))
        for key in list(self.child_models):
            if key not in wanted:self.child_models.pop(key).deleteLater()

class FormState(QObject):
    changed=Signal()
    def __init__(self,controller,ident):
        super().__init__(controller);self.controller=controller;self.ident=ident;self.data={};self.nodes=Objects(self);self.window=None;self.disposed=False
    @Property('QVariantMap',notify=changed)
    def meta(self):return {k:v for k,v in self.data.items() if k!='nodes'}
    @Property(str,constant=True)
    def formId(self):return self.ident
    @Property(QObject,constant=True)
    def nodeModel(self):return self.nodes
    @Slot('QVariantMap')
    def action(self,params):
        if self.disposed:return
        value=dict(params);value['form']=self.ident
        self.controller.request('form',value)
    def replace(self,data):
        self.data=data;self.nodes.replace(data.get('nodes',[]));self.changed.emit()

class FormWindows:
    def __init__(self,app,engine,controller,initialize,emit):
        self.app=app;self.engine=engine;self.controller=controller;self.initialize=initialize;self.emit=emit;self.forms={}
        self.component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path(__file__).with_name('QtFormWindow.qml'))))
        from qt_form_dialogs import Dialogs
        self.dialogs=Dialogs(app,emit)
        if self.component.isError():raise RuntimeError('\n'.join(e.toString() for e in self.component.errors()))
    def receive(self,message):
        kind=message.get('type');ident=message.get('form')
        if kind=='form_dialog':
            parent=self.forms.get(ident)
            self.dialogs.show(message,parent.window if parent else None);return True
        if kind not in ('form','form_remove','form_activate'):return False
        if kind=='form_remove':
            self.controller.forget_background(ident)
            state=self.forms.pop(ident,None)
            if state:
                state.disposed=True;state.window.hide();state.window.deleteLater();state.deleteLater()
                self.emit(dict(type='closed',window=ident))
            return True
        if kind=='form_activate':
            state=self.forms.get(ident)
            if state:
                if state.window.windowState()==Qt.WindowMinimized:state.window.showNormal()
                state.window.raise_();state.window.requestActivate()
            return True
        state=self.forms.get(ident)
        if not state:
            self.controller.open_background(ident)
            state=self.forms[ident]=FormState(self.controller,ident)
            window=self.component.createWithInitialProperties({'formState':state},self.engine.rootContext())
            if not isinstance(window,QQuickWindow):raise RuntimeError('工具窗口加载失败：'+str(self.component.errors()))
            state.window=window;window.setObjectName(ident)
            window.resize(message.get('width',800),message.get('height',640))
            window.setMinimumWidth(message.get('minimumWidth',240));window.setMinimumHeight(message.get('minimumHeight',180))
            self.initialize(window)
            window.frameSwapped.connect(lambda:self.frame(ident))
        elif message.get('visible') and not state.data.get('visible'):
            self.controller.open_background(ident)
        state.replace(message)
        parent=self.forms.get(message.get('parent'))
        if parent:state.window.setTransientParent(parent.window)
        return True
    def frame(self,ident):
        state=self.forms.get(ident)
        if state and not getattr(state,'presented',False):
            state.presented=True;self.emit(dict(type='presented',window=ident))
