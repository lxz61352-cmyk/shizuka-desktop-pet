"""Selectable dialogue rows, separated by fine rules over full-window artwork."""
import tkinter as tk
from tkinter import font as tkfont
import time
from PIL import Image, ImageTk
from ui_theme import FONT,palette


class ArtTranscript(tk.Canvas):
    def __init__(self,parent,plain=False,**kwargs):
        colors=palette(parent)
        super().__init__(parent,highlightthickness=0,bd=0,bg=colors['bg'],
                         selectbackground=colors['selected'],selectforeground=colors['ink'],**kwargs)
        self.rows=[];self.art=None;self.photos=[];self.cards=[];self.texts={};self.all_selected=False
        self.plain=plain
        self.bind('<Configure>',lambda e:self.render())
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
        self.rows=list(rows);self.render();self.yview_moveto(1);self.paint()

    def open_row(self,event):
        y=self.canvasy(event.y)
        row=next((r for top,bottom,r in self.hit_rows if top<=y<=bottom),None)
        if row and hasattr(self,'on_context'):self.on_context(row)

    def focus_row(self,ident):
        found=next(((top,bottom) for top,bottom,r in self.hit_rows if r.get('id')==ident),None)
        if found:
            height=float(self.cget('scrollregion').split()[-1]);self.yview('moveto',max(0,found[0]-30)/max(1,height))

    def set_backdrop(self,image):
        self.art=image;self.paint()

    def render(self):
        colors=palette(self)
        self.delete('all');self.cards=[];self.texts={};self.all_selected=False;self.hit_rows=[]
        width=max(260,self.winfo_width());y=24
        font=tkfont.Font(root=self,font=FONT)
        if self.plain:
            text='\n'.join(row.get('text','') for row in self.rows)
            item=self.create_text(4,4,text=text,anchor='nw',width=width-8,fill=colors['ink'],
                                  font=FONT,tags=('text','message'))
            self.texts[item]=text
            bounds=self.bbox(item) or (0,0,width,20)
            if self.rows:self.hit_rows=[(0,bounds[3]+6,self.rows[0])]
            self.content_height=bounds[3]+6
            self.configure(scrollregion=(0,0,width,self.content_height))
            self.paint();return
        if not self.rows:
            self.create_text(24,y,text='这里还没有符合条件的对话。',anchor='nw',fill=colors['muted'],font=FONT,tags='text')
            y+=80
        for row in self.rows:
            user=row.get('role')=='user';label='你' if user else '静香' if row.get('role')=='assistant' else '记录'
            if row.get('kind')=='notification':label=('已读 · ' if row.get('read') else '● 未读 · ')+row.get('source','通知')
            stamp=time.strftime('%m-%d %H:%M',time.localtime(row.get('created',0)))
            x=28;maximum=width-56
            self.create_text(x,y,text=label,anchor='nw',fill=colors['accent'] if user else colors['ink'],
                             font=(FONT[0],10,'bold'),tags='text')
            self.create_text(width-28,y+2,text=stamp,anchor='ne',fill=colors['muted'],
                             font=(FONT[0],9),tags='text')
            item=self.create_text(x,y+32,text=row.get('text',''),anchor='nw',width=maximum,
                                  fill=colors['ink'],font=FONT,tags=('text','message'))
            bounds=self.bbox(item);bottom=(bounds[3] if bounds else y+55)+23
            self.hit_rows.append((y,bottom,row))
            self.create_line(x,bottom,width-28,bottom,fill=colors['line'],width=1,tags='text')
            self.texts[item]=row.get('text','');y=bottom+24
        self.configure(scrollregion=(0,0,width,y))
        self.paint()

    def paint(self):
        if not self.winfo_exists():return
        self.delete('art');self.photos=[]
        width,height=max(1,self.winfo_width()),max(1,self.winfo_height())
        art=self.art if self.art is not None else Image.new('RGB',(width,height),palette(self)['bg'])
        if art.size!=(width,height):art=art.resize((width,height))
        top=self.canvasy(0)
        photo=ImageTk.PhotoImage(art,master=self);self.photos.append(photo)
        self.create_image(0,top,image=photo,anchor='nw',tags='art')
        self.tag_lower('art')

    def scroll(self,amount,units='units'):
        super().yview_scroll(amount,units);self.paint();return 'break'

    def yview(self,*args):
        value=super().yview(*args)
        if args:self.paint()
        return value

    def wheel(self,event):return self.scroll(-max(1,abs(event.delta)//120) if event.delta>0 else max(1,abs(event.delta)//120))

    def select_start(self,event):
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
        return '\n\n'.join(('你' if r.get('role')=='user' else '静香')+'：'+r.get('text','') for r in self.rows)

    def copy(self,all_text=False):
        try:text=self.get() if all_text else self.get('sel.first','sel.last')
        except tk.TclError:return 'break'
        self.clipboard_clear();self.clipboard_append(text);return 'break'
