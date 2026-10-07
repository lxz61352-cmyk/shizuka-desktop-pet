"""Selectable dialogue rows, separated by fine rules over full-window artwork."""
import tkinter as tk
import time
from PIL import Image, ImageTk
from ui_theme import FONT,palette
from backdrop_frame import fit_image
from virtual_transcript import VirtualTranscriptMixin


class ArtTranscript(VirtualTranscriptMixin,tk.Canvas):
    def __init__(self,parent,plain=False,**kwargs):
        colors=palette(parent)
        super().__init__(parent,highlightthickness=0,bd=0,bg=colors['bg'],
                         selectbackground=colors['selected'],selectforeground=colors['ink'],**kwargs)
        self.rows=[];self.art=None;self.photos=[];self.cards=[];self.texts={};self.all_selected=False
        self.plain=plain
        self._render_width=None;self._paint_source=None;self._paint_size=None
        self._reflow_pending=None;self._layout_job=None;self._row_items=[]
        self._follow_end=False;self._pending_focus=None
        self._virtual=None;self._virtual_records={}
        self.bind('<Configure>',self._resized)
        self.bind('<Destroy>',self._dispose_images,add='+')
        self.bind('<MouseWheel>',self.wheel)
        self.bind('<Button-1>',self.select_start)
        self.bind('<B1-Motion>',self.select_move)
        self.bind('<Control-c>',lambda e:self.copy())
        self.bind('<Control-C>',lambda e:self.copy())
        self.bind('<Control-a>',lambda e:self.select_all())
        self.bind('<Control-A>',lambda e:self.select_all())
        self.bind('<Prior>',lambda e:self.scroll(-1,'pages'))
        self.bind('<Next>',lambda e:self.scroll(1,'pages'))
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label='复制所选',command=self.copy)
        menu.add_command(label='复制全部',command=lambda:self.copy(True))
        def context_menu(event):
            while menu.index('end') is not None and menu.index('end')>1:menu.delete(2,'end')
            y=self.canvasy(event.y)
            row=next((r for top,bottom,r in getattr(self,'hit_rows',[]) if top<=y<=bottom),None)
            if row and row.get('role')=='assistant' and hasattr(self,'on_feedback'):
                menu.add_separator();menu.add_command(label='标记这条回复…',command=lambda:self.on_feedback(row))
            if row and hasattr(self,'on_context'):
                menu.add_command(label='查看通知 / 处理…' if row.get('kind')=='notification' else '展开前后文…',command=lambda:self.on_context(row))
            menu.tk_popup(event.x_root,event.y_root)
        self.bind('<Button-3>',context_menu)
        self.bind('<Double-1>',self.open_row)
        self.configure(takefocus=True)

    def set_rows(self,rows):
        if self.all_selected:self.itemconfigure('message',fill=palette(self)['ink'])
        self.all_selected=False;self.select_clear();self.selecting=None
        self.rows=list(rows);self._follow_end=True;self._pending_focus=None
        self.render(incremental=len(self.rows)>100);self.paint()

    def open_row(self,event):
        y=self.canvasy(event.y)
        row=next((r for top,bottom,r in self.hit_rows if top<=y<=bottom),None)
        if row and hasattr(self,'on_context'):self.on_context(row)

    def focus_row(self,ident):
        if self._virtual is not None:
            index=self._virtual_ids.get(ident)
            if index is not None:
                self._follow_end=False;self._virtual_focus=index;self._virtual_present();self.paint()
            return
        if self._layout_job:
            self._pending_focus=ident;self._follow_end=False;return
        found=next(((top,bottom) for top,bottom,r in self.hit_rows if r.get('id')==ident),None)
        if found:
            height=float(self.cget('scrollregion').split()[-1]);self.yview('moveto',max(0,found[0]-30)/max(1,height))

    def set_backdrop(self,image):
        self.art=image;self.paint()

    def _dispose_images(self,event):
        if event.widget is self:
            for name in ('_reflow_pending','_layout_job'):
                if getattr(self,name,None):self.after_cancel(getattr(self,name));setattr(self,name,None)
            for photo in self.photos:photo.__del__()
            self.photos=[];self._paint_source=None

    def _resized(self,event):
        # Height changes and window moves don't change text wrapping.
        if max(260,event.width)!=self._render_width:
            if self._reflow_pending:self.after_cancel(self._reflow_pending)
            if self._layout_job:self.after_cancel(self._layout_job);self._layout_job=None
            self._reflow_pending=self.after(100,self._reflow)
        self.paint()
        if self._virtual is not None and max(260,event.width)==self._render_width:self._virtual_present()

    def _reflow(self):
        self._reflow_pending=None
        # Work in small batches so a long transcript cannot block dragging.
        self.render(incremental=True)

    def render(self,incremental=False):
        if not self.plain and len(self.rows)>100:
            self._virtual_render();return
        if self._virtual is not None:
            self.delete('text');self._row_items=[];self._virtual=None;self._virtual_records={}
        self._render_all(incremental)

    def _render_all(self,incremental=False):
        if self._reflow_pending:self.after_cancel(self._reflow_pending);self._reflow_pending=None
        if self._layout_job:self.after_cancel(self._layout_job);self._layout_job=None
        colors=palette(self)
        self.cards=[];self.texts={};self.hit_rows=[]
        width=max(260,self.winfo_width());y=24
        self._render_width=width
        if self.plain:
            text='\n'.join(row.get('text','') for row in self.rows)
            existing=self.find_withtag('message')
            if existing:
                item=existing[0];self.itemconfigure(item,text=text,width=width-8,fill=colors['ink'])
            else:
                item=self.create_text(4,4,text=text,anchor='nw',width=width-8,fill=colors['ink'],
                                      font=FONT,tags=('text','message'))
            self.texts[item]=text
            bounds=self.bbox(item) or (0,0,width,20)
            if self.rows:self.hit_rows=[(0,bounds[3]+6,self.rows[0])]
            self.content_height=bounds[3]+6
            self.configure(scrollregion=(0,0,width,self.content_height))
            if self._follow_end:self.yview_moveto(1);self._follow_end=False
            self.paint();return
        self.delete('empty')
        for record in self._row_items[len(self.rows):]:
            for item in record['items']:self.delete(item)
        del self._row_items[len(self.rows):]
        if not self.rows:
            self.create_text(24,y,text='这里还没有符合条件的对话。',anchor='nw',fill=colors['muted'],font=FONT,tags=('text','empty'))
            y+=80
        def layout_row(index,row,y):
            user=row.get('role')=='user';label='你' if user else 'Shizuka' if row.get('role')=='assistant' else '记录'
            if row.get('kind')=='notification':label=('已读 · ' if row.get('read') else '● 未读 · ')+row.get('source','通知')
            stamp=time.strftime('%m-%d %H:%M',time.localtime(row.get('created',0)))
            x=28;maximum=width-56
            if index==len(self._row_items):
                items=(self.create_text(0,0,anchor='nw',font=(FONT[0],10,'bold'),tags='text'),
                       self.create_text(0,0,anchor='ne',font=(FONT[0],9,'bold'),tags='text'),
                       self.create_text(0,0,anchor='nw',font=FONT,tags=('text','message')),
                       self.create_line(0,0,0,0,width=1,tags='text'))
                self._row_items.append({'items':items,'key':None})
            record=self._row_items[index];heading,date,item,line=record['items']
            key=(label,stamp,row.get('text',''),width,tuple(colors.items()),self.all_selected)
            if key!=record['key']:
                self.itemconfigure(heading,text=label,fill=colors['accent'] if user else colors['ink'])
                self.itemconfigure(date,text=stamp,fill=colors['muted'])
                self.itemconfigure(item,text=row.get('text',''),width=maximum,
                                   fill=colors['accent'] if self.all_selected else colors['ink'])
                bounds=self.bbox(item)
                record['height']=(bounds[3]-bounds[1] if bounds else 23)+55
                self.itemconfigure(line,fill=colors['line']);record['key']=key
            bottom=y+record['height']
            location=(width,y,bottom)
            if location!=record.get('location'):
                self.coords(heading,x,y);self.coords(date,width-28,y+2);self.coords(item,x,y+32)
                self.coords(line,x,bottom,width-28,bottom);record['location']=location
            self.hit_rows.append((y,bottom,row))
            self.texts[item]=row.get('text','');return bottom+24
        rows=list(self.rows);position=[0,y]
        def batch():
            self._layout_job=None;start=time.perf_counter()
            while position[0]<len(rows):
                index=position[0];position[1]=layout_row(index,rows[index],position[1]);position[0]+=1
                if incremental and time.perf_counter()-start>.008:break
            if position[0]<len(rows):self._layout_job=self.after(1,batch)
            else:
                self.configure(scrollregion=(0,0,width,position[1]))
                if self._follow_end:self.yview_moveto(1);self._follow_end=False
                if self._pending_focus is not None:
                    ident=self._pending_focus;self._pending_focus=None;self.focus_row(ident)
                self.paint()
        batch()

    def paint(self):
        if not self.winfo_exists():return
        width,height=max(1,self.winfo_width()),max(1,self.winfo_height())
        size=(width,height)
        if not self.photos or self._paint_source is not self.art or self._paint_size!=size:
            art=self.art if self.art is not None else Image.new('RGB',size,palette(self)['bg'])
            art=fit_image(art,size)
            if self.photos and self._paint_size==size:self.photos[0].paste(art)
            else:self.photos=[ImageTk.PhotoImage(art,master=self)]
            self._paint_source=self.art;self._paint_size=size
        x,top=self.canvasx(0),self.canvasy(0)
        if self.find_withtag('art'):
            self.coords('art',x,top);self.itemconfigure('art',image=self.photos[0])
        else:self.create_image(x,top,image=self.photos[0],anchor='nw',tags='art')
        self.tag_lower('art')

    def scroll(self,amount,units='units'):
        self._follow_end=False;self._pending_focus=None
        super().yview_scroll(amount,units)
        self._virtual_present();self.paint();return 'break'

    def yview(self,*args):
        if args:self._follow_end=False;self._pending_focus=None
        value=super().yview(*args)
        if args:self._virtual_present();self.paint()
        return value

    def yview_moveto(self,fraction):return self.yview('moveto',fraction)

    def yview_scroll(self,number,what):return self.scroll(number,what)

    def wheel(self,event):return self.scroll(-max(1,abs(event.delta)//120) if event.delta>0 else max(1,abs(event.delta)//120))

    def select_start(self,event):
        if self.all_selected:self.itemconfigure('message',fill=palette(self)['ink'])
        self.focus_set();self.all_selected=False;self.select_clear();self.selecting=None
        x,y=self.canvasx(event.x),self.canvasy(event.y)
        for item in self.find_overlapping(x,y,x,y):
            if item in self.texts:
                self.selecting=item;self.select_from(item,'@%d,%d'%(x,y));break

    def select_move(self,event):
        if getattr(self,'selecting',None):
            self.select_to(self.selecting,'@%d,%d'%(self.canvasx(event.x),self.canvasy(event.y)))

    def select_all(self):
        self.all_selected=True;self.itemconfigure('message',fill=palette(self)['accent']);return 'break'

    def get(self,start='1.0',end='end-1c'):
        if start=='sel.first' and not self.all_selected:
            item=self.select_item()
            if not item:raise tk.TclError('No selection')
            return self.texts.get(item,'')[self.index(item,'sel.first'):self.index(item,'sel.last')+1]
        if self.plain:return '\n'.join(r.get('text','') for r in self.rows)
        return '\n\n'.join(('你' if r.get('role')=='user' else 'Shizuka')+'：'+r.get('text','') for r in self.rows)

    def copy(self,all_text=False):
        try:text=self.get() if all_text else self.get('sel.first','sel.last')
        except tk.TclError:return 'break'
        self.clipboard_clear();self.clipboard_append(text);return 'break'
