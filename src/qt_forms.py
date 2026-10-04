"""Qt presentation adapter for ordinary tool dialogs.

The existing widgets are a private, invisible control/layout model. They never
receive the artwork renderer. All displayed controls and backgrounds live in the
single Qt process; callbacks and persisted state still belong to the main app.
"""
import json, re, tempfile, time, uuid
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
from tkinter import commondialog

_original_bind = tk.Misc._bind
_original_focus = tk.Misc.focus_set
_original_dialog = commondialog.Dialog.show
_original_see = tk.Text.see
_installed = False

def owner(widget):
    try:
        window=widget.winfo_toplevel()
        return getattr(window,'_qt_form',None) if getattr(window,'_qt_model_only',False) else None
    except (tk.TclError, AttributeError):return None

def install(app):
    global _installed
    app.root._qt_form_app = app
    if not hasattr(app, '_qt_forms'):app._qt_forms = Forms(app)
    if not _installed:
        def bind(widget, what, sequence, func, add, needcleanup=1):
            form = owner(widget)
            if form and callable(func):
                key = (str(widget), tuple(map(str,what)), sequence)
                form.bindings[key] = (form.bindings.get(key, []) if add else []) + [func]
            return _original_bind(widget, what, sequence, func, add, needcleanup)
        tk.Misc._bind = bind
        def focus(widget):
            form=owner(widget)
            if form:form.focus=str(widget)
            else:return _original_focus(widget)
        tk.Misc.focus_set=focus
        def dialog(instance,**options):
            merged=dict(instance.options);merged.update(options)
            form=owner(merged.get('parent',instance.master))
            if form and instance.__class__.__name__ in ('Open','SaveAs','Directory','Message'):
                return form.registry.dialog(form,instance.__class__.__name__,merged)
            return _original_dialog(instance,**options)
        commondialog.Dialog.show=dialog
        def see(widget,index):
            form=owner(widget)
            if form and str(index)=='end':form.scroll_end[str(widget)]=form.scroll_end.get(str(widget),0)+1
            return _original_see(widget,index)
        tk.Text.see=see
        _installed = True
    return app._qt_forms

def create_dialog(parent):
    app = getattr(parent._root(), '_qt_form_app', None)
    if app is None or getattr(app, '_qt_window_failed', False):return None
    from qt_window_bridge import enabled
    if not enabled():return None
    registry = install(app)
    window = tk.Toplevel(parent)
    window.withdraw(); window.attributes('-alpha', 0)
    form = Form(registry, window)
    registry.forms[form.ident] = form
    window._qt_form = form; window._qt_model_only = True
    registry.root.after(0, form.start)
    return window

class Forms:
    def __init__(self, app):
        self.app=app;self.root=app.root;self.forms={};self.temp=tempfile.TemporaryDirectory(prefix='shizuka-qt-images-')
        self.images={};self.root.after(180,self.poll)
    def image(self, name, widget):
        if not name:return ''
        key=str(name)
        # PhotoImage names are unique for their lifetime. Pixel updates are rare
        # (QR/preview); the source can mark _qt_image_revision when reusing one.
        key += ':'+str(getattr(widget,'_qt_image_revision',0))
        if key not in self.images:
            path=Path(self.temp.name)/(uuid.uuid4().hex+'.png')
            try:widget.tk.call(str(name),'write',str(path),'-format','png')
            except tk.TclError:return ''
            self.images[key]=path.as_uri()
        return self.images[key]
    def poll(self):
        try:
            for form in list(self.forms.values()):
                try:
                    if form.window.winfo_exists() and form.started:form.publish()
                except tk.TclError:continue
        finally:
            try:self.root.after(180,self.poll)
            except tk.TclError:pass
    def action(self, params):
        form=self.forms.get(params.get('form'))
        if not form or not form.window.winfo_exists():raise ValueError('窗口已关闭')
        return form.action(params)
    def dialog(self,form,kind,options):
        bridge=form.bridge;ident=uuid.uuid4().hex
        safe={key:value for key,value in options.items() if key in ('title','message','detail','icon','type','initialdir','initialfile','filetypes','defaultextension','multiple','mustexist')}
        bridge.send(dict(type='form_dialog',form=form.ident,dialog=ident,kind=kind,options=safe))
        deferred=[]
        try:
            while True:
                if bridge.closed or bridge.process.poll() is not None:raise RuntimeError('窗口进程已关闭')
                try:packet=bridge.incoming.get_nowait()
                except __import__('queue').Empty:packet=None
                if packet and packet.get('type')=='form_dialog_result' and packet.get('dialog')==ident:
                    if not packet.get('ok'):raise RuntimeError(packet.get('error','系统弹窗未打开'))
                    return packet.get('value','')
                if packet:deferred.append(packet)
                self.root.update();time.sleep(.01)
        finally:
            for packet in deferred:bridge.incoming.put(packet)
    def recover(self):
        for form in list(self.forms.values()):form.recover()

class Form:
    def __init__(self, registry, window):
        self.registry=registry;self.window=window;self.ident='form-'+uuid.uuid4().hex
        self.widgets={};self.bindings={};self.ack={};self.focus='';self.scroll_end={};self.last=None;self.started=False;self.visible=True;self.width=800;self.height=640;self.explicit_size=False
        self.original={name:getattr(window,name) for name in ('geometry','deiconify','withdraw','lift','destroy','state','attributes')}
        self.disposed=False
        # Tk's default WM_DELETE_WINDOW callback was registered before this
        # adapter, so it can call the original destroy method directly.
        window.bind('<Destroy>',self.model_destroyed,add='+')
        window.geometry=self.geometry;window.deiconify=self.show;window.withdraw=self.hide
        window.lift=self.raise_;window.destroy=self.destroy;window.attributes=self.attributes;window.state=self.state
    def attributes(self,*args):
        if args and args[0] in ('-alpha','-topmost'):
            if len(args)==1:return 1.0 if args[0]=='-alpha' else True
            return None
        return self.original['attributes'](*args)
    def geometry(self, value=None):
        if value is None:return f'{self.width}x{self.height}+0+0'
        match=re.match(r'(\d+)x(\d+)',str(value))
        if match:self.width,self.height=map(int,match.groups());self.explicit_size=True
        return self.original['geometry'](f'{self.width}x{self.height}-30000-30000')
    def state(self,value=None):
        if value in ('withdrawn','iconic'):self.hide();return None
        if value=='normal':self.show();return None
        return 'normal' if self.visible else 'withdrawn'
    def start(self):
        if not self.window.winfo_exists():return
        self.started=True
        try:
            from qt_window_bridge import get_bridge
            self.bridge=get_bridge(self.registry.app)
            self.window.transient('')  # A withdrawn Tk owner must not suppress the private layout model.
            if not self.explicit_size:
                self.window.update_idletasks()
                self.width=max(280,self.window.winfo_reqwidth());self.height=max(180,self.window.winfo_reqheight())
            # Mapping at alpha=0 is needed for Tk's pack/grid layout. Keep the
            # private model outside every monitor and out of task switching.
            self.original['geometry'](f'{self.width}x{self.height}-30000-30000')
            self.window.update_idletasks()
            if __import__('sys').platform=='win32':
                import ctypes
                u=ctypes.windll.user32;u.GetParent.restype=ctypes.c_void_p
                handle=u.GetParent(ctypes.c_void_p(self.window.winfo_id()))
                style=u.GetWindowLongW(ctypes.c_void_p(handle),-20)
                self.native_style=(handle,style)
                u.SetWindowLongW(ctypes.c_void_p(handle),-20,(style|0x80|0x08000000)&~0x40000)
            self.original['deiconify']();self.window.update_idletasks()
            self.publish(force=True)
        except Exception:
            self.registry.app._qt_window_failed=True;self.recover()
            raise
    def show(self):
        self.visible=True
        if self.started:self.publish(force=True)
    def hide(self):
        self.visible=False
        if self.started:self.publish(force=True)
    def raise_(self,*args):
        self.visible=True
        if self.started:self.bridge.send(dict(type='form_activate',form=self.ident))
    def destroy(self):
        self.dispose()
        if self.window.winfo_exists():self.original['destroy']()
    def model_destroyed(self,event):
        if event.widget is self.window and self.registry.forms.get(self.ident) is self:
            self.dispose()
    def dispose(self):
        if self.disposed:return
        self.disposed=True;self.visible=False
        if self.started and not self.bridge.closed:self.bridge.send(dict(type='form_remove',form=self.ident))
        if self.started:self.bridge.opened.discard(self.ident)
        self.registry.forms.pop(self.ident,None)
    def recover(self):
        if not self.window.winfo_exists():return
        for name,method in self.original.items():setattr(self.window,name,method)
        self.window._qt_model_only=False
        self.window._qt_form=None
        if hasattr(self,'native_style'):
            import ctypes
            handle,style=self.native_style
            ctypes.windll.user32.SetWindowLongW(ctypes.c_void_p(handle),-20,style)
        self.original['attributes']('-alpha',1);self.original['geometry'](f'{self.width}x{self.height}+100+100')
        from ui_theme import apply
        apply(self.window)
        if self.visible:self.original['deiconify']()
        else:self.original['withdraw']()
        self.registry.forms.pop(self.ident,None)
    def event(self,widget,sequence,**values):
        fields=dict(widget=widget,x=0,y=0,x_root=100,y_root=100,num=1,delta=0,keysym='',char='',state=0)
        fields.update(values);event=SimpleNamespace(**fields)
        for (name,what,seq),callbacks in list(self.bindings.items()):
            if name==str(widget) and seq==sequence and what==('bind',str(widget)):
                for callback in callbacks:
                    if callback(event)=='break':return
    def widget(self,ident):
        widget=self.widgets.get(ident)
        if widget is None and isinstance(ident,str) and ident.startswith(str(self.window)+'.'):
            try:widget=self.window.nametowidget(ident)
            except KeyError:pass
        if not widget or not widget.winfo_exists():raise ValueError('控件已更新，请重新操作')
        return widget
    def action(self,p):
        action=p.get('action')
        if action=='close':
            command=self.window.protocol('WM_DELETE_WINDOW')
            if command:self.window.tk.call(command)
            else:self.destroy()
            return None
        if action=='escape':
            callbacks=[callbacks for (name,what,seq),callbacks in self.bindings.items() if name==str(self.window) and seq=='<Escape>']
            if callbacks:self.event(self.window,'<Escape>')
            else:return self.action(dict(action='close'))
            return None
        if action=='resize':
            self.width=max(240,min(4096,int(p['width'])));self.height=max(180,min(4096,int(p['height'])))
            self.original['geometry'](f'{self.width}x{self.height}-30000-30000');self.window.update_idletasks()
            self.publish(force=True);return None
        widget=self.widget(p.get('widget'))
        if action=='event':
            sequence=p.get('sequence')
            if sequence in ('<Return>','<Escape>','<FocusOut>','<Button-1>','<Button-3>'):
                self.event(widget,sequence,x=float(p.get('x',0)),y=float(p.get('y',0)),x_root=int(p.get('globalX',100)),y_root=int(p.get('globalY',100)))
            return None
        if action=='textSelection' and isinstance(widget,tk.Text):
            start=max(0,int(p.get('start',0)));end=max(start,int(p.get('end',0)))
            widget.tag_remove('sel','1.0','end')
            if end>start:widget.tag_add('sel',f'1.0+{start}chars',f'1.0+{end}chars')
            return None
        if action=='invoke':
            if str(widget.cget('state'))!='disabled':widget.invoke()
        elif action=='edit':
            self.ack[str(widget)]=max(self.ack.get(str(widget),0),int(p.get('sequence',0)))
            value=str(p.get('value',''))
            if isinstance(widget,tk.Text):
                if str(widget.cget('state'))=='normal':widget.delete('1.0','end');widget.insert('1.0',value)
            elif isinstance(widget,ttk.Combobox):widget.set(value);self.event(widget,'<<ComboboxSelected>>')
            elif isinstance(widget,(tk.Scale,ttk.Scale)):widget.set(float(value))
            else:
                if str(widget.cget('state')) not in ('disabled','readonly'):
                    widget.delete(0,'end');widget.insert(0,value)
            if isinstance(widget,(tk.Spinbox,ttk.Spinbox)):
                command=widget.cget('command')
                if command:widget.tk.call(command)
            self.event(widget,'<KeyRelease>')
        elif action=='select':
            ids=[str(i) for i in p.get('rows',[])]
            if isinstance(widget,ttk.Treeview):
                ids=[i for i in ids if widget.exists(i)];widget.selection_set(ids)
                if ids:widget.focus(ids[-1]);widget.see(ids[-1])
                self.event(widget,'<<TreeviewSelect>>')
            else:
                widget.selection_clear(0,'end')
                for i in ids:
                    if 0<=int(i)<widget.size():widget.selection_set(int(i))
                self.event(widget,'<<ListboxSelect>>')
        elif action=='double':
            if isinstance(widget,ttk.Treeview):
                ident=str(p.get('row',''))
                if not widget.exists(ident):return None
                widget.selection_set(ident);widget.focus(ident);widget.see(ident);self.window.update_idletasks()
                box=widget.bbox(ident);y=box[1]+box[3]//2 if box else 1
                self.event(widget,'<Double-1>',y=y)
                self.event(widget,'<Double-Button-1>',y=y)
            else:self.event(widget,'<Double-1>')
        elif action=='tab':widget.select(int(p['index']))
        elif action=='scroll':
            try:widget.yview_scroll(int(p.get('delta',0)),'units')
            except tk.TclError:pass
        elif action=='scrollTo':widget.yview_moveto(max(0,min(1,float(p.get('position',0)))))
        elif action=='canvas':
            item=int(p['item']);sequence='<Button-3>' if p.get('right') else '<Double-Button-1>' if p.get('double') else '<Button-1>'
            if item not in widget.find_all():return None
            tags=widget.gettags(item);widget.addtag_withtag('current',item)
            event=SimpleNamespace(widget=widget,x=float(p.get('x',0)),y=float(p.get('y',0)),x_root=int(p.get('globalX',100)),y_root=int(p.get('globalY',100)),num=3 if p.get('right') else 1,delta=0,state=0)
            for (name,what,seq),callbacks in list(self.bindings.items()):
                if name==str(widget) and seq in (sequence,sequence.replace('-Button','')):
                    # Canvas binds use ('tag', canvas, tag) rather than widget binds.
                    if len(what)==3 and (what[-1] in tags or what[-1]==str(item)):
                        for callback in callbacks:callback(event)
            widget.dtag(item,'current')
            self.event(widget,sequence,x=event.x,y=event.y,x_root=event.x_root,y_root=event.y_root,num=event.num)
        self.window.update_idletasks()
        if self.window.winfo_exists():self.publish(force=True)
        return None
    def publish(self,force=False):
        if self.bridge.closed:return
        self.window.update_idletasks()
        nodes=[];self.widgets={}
        self.walk(self.window,0,0,(0,0,self.width,self.height),nodes)
        minimum=self.window.minsize()
        parent=owner(self.window.master)
        packet=dict(type='form',form=self.ident,title=self.window.title(),width=self.width,height=self.height,
                    minimumWidth=max(240,minimum[0]),minimumHeight=max(180,minimum[1]),visible=self.visible,nodes=nodes,focus=self.focus,parent=parent.ident if parent else '')
        if self.visible:self.bridge.opened.add(self.ident)
        else:self.bridge.opened.discard(self.ident)
        if force or packet!=self.last:self.bridge.send(packet);self.last=packet;self.focus=''
    def walk(self,widget,x,y,clip,nodes):
        for child in widget.winfo_children():
            if not child.winfo_manager() or getattr(child,'_art_decoration',False):continue
            if not child.winfo_ismapped():continue
            cx=x+child.winfo_x();cy=y+child.winfo_y();width=child.winfo_width();height=child.winfo_height()
            if width<=1 or height<=1:continue
            left,top,right,bottom=clip
            if cx+width<left or cy+height<top or cx>right or cy>bottom:continue
            ident=str(child);self.widgets[ident]=child
            node=dict(id=ident,x=cx,y=cy,width=width,height=height,clip=[left,top,right,bottom],kind='',enabled=True,ackSequence=self.ack.get(ident,0))
            try:self.describe(child,node)
            except tk.TclError:continue
            if node['kind']:nodes.append(node)
            nextclip=(max(left,cx),max(top,cy),min(right,cx+width),min(bottom,cy+height))
            self.walk(child,cx,cy,nextclip,nodes)
    def describe(self,w,n):
        def option(key,default=''):
            try:return w.cget(key)
            except tk.TclError:return default
        n['enabled']=str(option('state','normal'))!='disabled'
        n['text']=str(option('text'));n['value']='';n['image']=''
        n['clickable']=any(name==str(w) and sequence=='<Button-1>' and what==('bind',str(w)) for name,what,sequence in self.bindings)
        if isinstance(w,(tk.Label,ttk.Label)):
            n['kind']='label';n['image']=self.registry.image(option('image'),w)
            n['title']=getattr(w,'_type_role','')=='title';n['align']=str(option('anchor','w'))
        elif isinstance(w,(tk.Checkbutton,ttk.Checkbutton,tk.Radiobutton,ttk.Radiobutton)):
            n['kind']='radio' if isinstance(w,(tk.Radiobutton,ttk.Radiobutton)) else 'check'
            variable=str(option('variable'))
            value=str(w.getvar(variable)) if variable else ''
            n['checked']=value==str(option('value')) if n['kind']=='radio' else value==str(option('onvalue',1))
        elif isinstance(w,(tk.Button,ttk.Button)):n['kind']='button'
        elif isinstance(w,ttk.Combobox):n.update(kind='combo',value=w.get(),choices=list(option('values',())),editable=str(option('state'))!='readonly')
        elif isinstance(w,(tk.Entry,ttk.Entry,tk.Spinbox,ttk.Spinbox)):
            secret=bool(str(option('show')))
            n.update(kind='field',value='' if secret else w.get(),secret=secret,hasValue=secret and bool(w.get()),readonly=str(option('state'))=='readonly')
        elif isinstance(w,tk.Text):n.update(kind='text',value=w.get('1.0','end-1c'),readonly=str(option('state'))=='disabled',scrollToEnd=self.scroll_end.get(str(w),0))
        elif isinstance(w,(tk.Scale,ttk.Scale)):n.update(kind='slider',value=float(w.get()),low=float(option('from',0)),high=float(option('to',100)))
        elif isinstance(w,ttk.Progressbar):n.update(kind='progress',value=float(option('value',0)),maximum=float(option('maximum',100)),indeterminate=str(option('mode'))=='indeterminate')
        elif isinstance(w,ttk.Treeview):
            columns=list(option('displaycolumns',()))
            if columns==['#all'] or not columns:columns=list(option('columns',()))
            rows=[]
            def collect(parent,depth=0):
                for ident in w.get_children(parent):
                    item=w.item(ident);cells=list(map(str,item['values']))
                    if 'tree' in str(option('show')):cells.insert(0,'  '*depth+str(item['text']))
                    rows.append(dict(id=ident,cells=cells))
                    if item['open']:collect(ident,depth+1)
            collect('')
            headings=[str(w.heading(c,'text')) for c in columns]
            if 'tree' in str(option('show')):headings.insert(0,str(w.heading('#0','text')))
            n.update(kind='list',rows=rows,headings=headings,selection=list(w.selection()),multiple=str(option('selectmode'))=='extended')
        elif isinstance(w,tk.Listbox):n.update(kind='list',rows=[dict(id=str(i),cells=[str(v)]) for i,v in enumerate(w.get(0,'end'))],headings=[],selection=list(map(str,w.curselection())),multiple=str(option('selectmode')) in ('extended','multiple'))
        elif isinstance(w,ttk.Notebook):n.update(kind='tabs',choices=[str(w.tab(t,'text')) for t in w.tabs()],index=w.index(w.select()) if w.select() else 0)
        elif isinstance(w,tk.Canvas):
            # Canvas-window children (settings pages) remain normal controls.
            # Only visible primitives are published, independent of total rows.
            items=[];offsetx=w.canvasx(0);offsety=w.canvasy(0)
            for ident in w.find_overlapping(offsetx,offsety,offsetx+n['width'],offsety+n['height']):
                kind=w.type(ident)
                if kind=='window':continue
                coords=w.coords(ident);box=w.bbox(ident)
                if not box:continue
                item=dict(id=ident,kind=kind,x=box[0]-offsetx,y=box[1]-offsety,width=max(1,box[2]-box[0]),height=max(1,box[3]-box[1]),coords=coords)
                for key in ('text','fill','outline','anchor'):
                    try:item[key]=str(w.itemcget(ident,key))
                    except tk.TclError:pass
                if kind=='image':item['image']=self.registry.image(w.itemcget(ident,'image'),w)
                if kind=='rectangle' and any(tag.startswith('memfield:') for tag in w.gettags(ident)):
                    item['fill']='#20344446'
                items.append(item)
            view=w.yview()
            n.update(kind='canvas',items=items,scrollable=view!=(0.,1.),scrollPosition=view[0],scrollSize=view[1]-view[0])
        elif isinstance(w,(tk.LabelFrame,ttk.LabelFrame)):
            if n['text']:n['kind']='group'
