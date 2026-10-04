"""Keep native editing usable when a colour-keyed field shows its parent art."""
from itertools import count
import tkinter as tk
from weakref import WeakSet

_serial=count()


def register(widget):
    window=widget.winfo_toplevel()
    router=getattr(window,'_glass_editor_router',None)
    if router is None:router=window._glass_editor_router=EditorRouter(window)
    router.editors.add(widget)
    router.install_tags(window)


class EditorRouter:
    def __init__(self,window):
        self.window=window;self.editors=WeakSet();self.active=None;self.forwarding=False
        self.tag='PetGlassEditor'+str(next(_serial))
        for sequence in ('<Button-1>','<Button-3>','<B1-Motion>','<ButtonRelease-1>','<MouseWheel>'):
            window.bind_class(self.tag,sequence,lambda event,seq=sequence:self.route(event,seq))

    def install_tags(self,widget):
        if isinstance(widget,tk.Toplevel) and widget is not self.window:return
        tags=widget.bindtags()
        if self.tag not in tags:widget.bindtags((self.tag,*tags))
        # Decorative labels are intentionally hidden from application child
        # lists, but they also need to forward clicks through transparent fields.
        for name in widget.tk.splitlist(widget.tk.call('winfo','children',widget._w)):
            self.install_tags(widget.nametowidget(name))

    def route(self,event,sequence):
        if self.forwarding:return
        target=None
        if sequence in ('<B1-Motion>','<ButtonRelease-1>'):
            target=self.active
        else:
            for editor in self.editors:
                if not editor.winfo_exists() or not editor.winfo_ismapped():continue
                x,y=editor.winfo_rootx(),editor.winfo_rooty()
                if x<=event.x_root<x+editor.winfo_width() and y<=event.y_root<y+editor.winfo_height():
                    target=editor;break
            if sequence=='<Button-1>':self.active=target
        if target is None or not target.winfo_exists():return
        if event.widget is target:
            if sequence=='<ButtonRelease-1>':self.active=None
            return
        self.forwarding=True
        try:
            options=dict(x=event.x_root-target.winfo_rootx(),y=event.y_root-target.winfo_rooty(),
                         rootx=event.x_root,rooty=event.y_root,state=event.state)
            if sequence=='<MouseWheel>':options['delta']=event.delta
            target.event_generate(sequence,**options)
        finally:
            self.forwarding=False
            if sequence=='<ButtonRelease-1>':self.active=None
        return 'break'
