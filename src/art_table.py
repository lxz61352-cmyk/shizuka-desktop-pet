"""Lightweight, keyboard-selectable table painted on the window's actual backdrop."""
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import Image, ImageDraw, ImageTk
from ui_theme import FONT, palette


class ArtTabs(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.tabs=[];self.current=0
        self.bar=ttk.Frame(self);self.bar.pack(fill='x',pady=(0,8))
    def add(self,page,text):
        index=len(self.tabs)
        button=ttk.Button(self.bar,text=text,command=lambda:self.select(index))
        button.pack(side='left',padx=(0,8));self.tabs.append((page,button,text))
        if index==0:page.pack(fill='both',expand=True)
        self._labels()
    def _labels(self):
        for i,(_,button,text) in enumerate(self.tabs):button.configure(text=('●  ' if i==self.current else '')+text)
    def index(self,which):return self.current if which=='current' else int(which)
    def select(self,index):
        self.tabs[self.current][0].pack_forget();self.current=int(index)
        self.tabs[self.current][0].pack(fill='both',expand=True);self._labels()
        self.event_generate('<<NotebookTabChanged>>')


class ArtTable(tk.Canvas):
    """Treeview-compatible subset used by the todo view; no opaque field or grid."""
    def __init__(self,parent,columns):
        super().__init__(parent,bg=palette(parent)['bg'],highlightthickness=0,bd=0,height=150,takefocus=True)
        self.columns=columns;self.headings={};self.widths={};self.data={};self.order=[];self.selected=()
        self.art=None;self.photo=None;self.bounds={};self.pending=None
        self.bind('<Configure>',lambda e:self.queue())
        self.bind('<Button-1>',self.pick)
        self.bind('<Up>',lambda e:self.step(-1));self.bind('<Down>',lambda e:self.step(1))
        self.bind('<MouseWheel>',self.wheel)
        self.bind('<Destroy>',self.dispose)
    def dispose(self,event):
        if event.widget is self and self.pending:self.after_cancel(self.pending);self.pending=None
    def queue(self):
        if self.pending is None:self.pending=self.after_idle(self.render)
    def heading(self,key,text):self.headings[key]=text;self.queue()
    def column(self,key,width,**kwargs):self.widths[key]=width;self.queue()
    def get_children(self):return tuple(self.order)
    def exists(self,iid):return iid in self.data
    def insert(self,parent,index,iid,values):
        self.data[iid]=tuple(values);self.order.append(iid);self.queue();return iid
    def item(self,iid,values=None):
        if values is None:return {'values':self.data[iid]}
        if self.data[iid]!=tuple(values):self.data[iid]=tuple(values);self.queue()
    def delete(self,*iids):
        for iid in iids:
            if iid in self.data:self.data.pop(iid);self.order.remove(iid)
        self.selected=tuple(i for i in self.selected if i in self.data);self.queue()
    def move(self,iid,parent,index):
        if self.order[index:index+1]==[iid]:return
        self.order.remove(iid);self.order.insert(index,iid);self.queue()
    def selection(self):return self.selected
    def selection_set(self,items):
        wanted=(items,) if isinstance(items,str) else tuple(items)
        selected=tuple(i for i in wanted if i in self.data)[:1]
        if selected!=self.selected:
            self.selected=selected;self.queue();self.event_generate('<<TreeviewSelect>>')
    def pick(self,event):
        self.focus_set();y=self.canvasy(event.y)
        for iid,(top,bottom) in self.bounds.items():
            if top<=y<bottom:self.selection_set(iid);break
    def step(self,direction):
        if not self.order:return 'break'
        index=self.order.index(self.selected[0]) if self.selected else (-1 if direction>0 else len(self.order))
        iid=self.order[max(0,min(len(self.order)-1,index+direction))];self.selection_set(iid)
        if iid in self.bounds:
            top,bottom=self.bounds[iid];visible=self.canvasy(0);height=self.winfo_height()
            if top<visible:self.yview_moveto(top/max(1,self.content_height))
            elif bottom>visible+height:self.yview_moveto((bottom-height)/max(1,self.content_height))
        self.paint();return 'break'
    def set_backdrop(self,image):self.art=image;self.paint()
    def render(self):
        self.pending=None
        if not self.winfo_exists():return
        super().delete('content');self.bounds={};colors=palette(self)
        font=tkfont.Font(root=self,font=FONT);line=font.metrics('linespace')
        width=max(260,self.winfo_width());available=width-24
        total=sum(self.widths.get(k,100) for k in self.columns)
        widths=[available*self.widths.get(k,100)/total for k in self.columns]
        y=14;x=12
        for key,w in zip(self.columns,widths):
            self.create_text(x+8,y,text=self.headings.get(key,key),anchor='nw',font=(FONT[0],10,'bold'),fill=colors['muted'],tags='content');x+=w
        y+=line+16;self.create_line(12,y,width-12,y,fill=colors['accent'],tags='content');y+=4
        if not self.order:
            self.create_text(20,y+25,text='这里还没有事项',anchor='nw',font=FONT,fill=colors['muted'],tags='content');y+=80
        for iid in self.order:
            top=y;x=12;bottom=y+line+28
            for value,w in zip(self.data[iid],widths):
                item=self.create_text(x+8,y+12,text=str(value),anchor='nw',width=max(30,w-18),font=FONT,fill=colors['ink'],tags='content')
                box=self.bbox(item);bottom=max(bottom,(box[3] if box else y+line)+14);x+=w
            self.bounds[iid]=(top,bottom)
            self.create_line(12,bottom,width-12,bottom,fill=colors['line'],tags='content');y=bottom+1
        self.content_height=y+8;self.configure(scrollregion=(0,0,width,self.content_height));self.paint()
    def paint(self):
        if not self.winfo_exists():return
        super().delete('art')
        size=(max(1,self.winfo_width()),max(1,self.winfo_height()))
        image=self.art.resize(size).convert('RGBA') if self.art is not None else Image.new('RGBA',size,palette(self)['bg'])
        top=self.canvasy(0)
        if self.selected and self.selected[0] in self.bounds:
            a,b=self.bounds[self.selected[0]];layer=Image.new('RGBA',size)
            ImageDraw.Draw(layer).rounded_rectangle((8,a-top,size[0]-8,b-top),radius=8,fill=(115,178,220,55))
            image=Image.alpha_composite(image,layer)
        self.photo=ImageTk.PhotoImage(image,master=self)
        self.create_image(0,top,anchor='nw',image=self.photo,tags='art');self.tag_lower('art')
    def yview(self,*args):
        result=super().yview(*args)
        if args:self.paint()
        return result
    def wheel(self,event):
        self.yview('scroll',-1 if event.delta>0 else 1,'units');return 'break'
