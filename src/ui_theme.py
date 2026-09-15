"""Quiet ivory/slate controls shared by the conversation and todo panels."""
import math
import tkinter as tk
from tkinter import ttk

BG='#F3F3F0';CARD='#FFFFFF';INK='#29343B';MUTED='#697780';ACCENT='#486773';LINE='#DFE4E4'
FONT=('Microsoft YaHei UI',10)
TRANS_COLOR='#000001'   # 色键透明（与 pet.TRANS_COLOR 一致）


def _rounded_points(x1,y1,x2,y2,r,steps=6):
    """圆角矩形的顶点。必须自己把圆弧采样成很多点——之前用 create_polygon(smooth=True)
    只给了 4 个角点，Tk 的样条只在角上切掉约 1~2px，等于没有圆角。"""
    pts=[]
    corners=[(x2-r,y1+r,-90),(x2-r,y2-r,0),(x1+r,y2-r,90),(x1+r,y1+r,180)]
    for cx,cy,start in corners:
        for i in range(steps+1):
            ang=math.radians(start+90.0*i/steps)
            pts.append((cx+r*math.cos(ang),cy+r*math.sin(ang)))
    return pts


def round_window(win,radius=8):
    """给窗口加一点小圆角。Tk 的窗口是方的，做法是：
    窗口背景设成色键透明 → 用 Canvas 画一个圆角矩形当底 → 调用方把内容用
    padx/pady=radius 往里缩，四角才会露出来（露出的部分就是透明的）。"""
    canvas=tk.Canvas(win,bg=TRANS_COLOR,highlightthickness=0,bd=0)
    canvas.place(x=0,y=0,relwidth=1,relheight=1)
    try:
        win.configure(bg=TRANS_COLOR)
        win.attributes('-transparentcolor',TRANS_COLOR)
    except Exception:
        pass
    # 注意：Canvas.lower 被重载成「canvas 内部图元」的操作，压不动这个控件本身，
    # 得走 tk.Misc.lower 把它压到同级控件的最下面，否则会盖住后建的内容（聊天框就是这么被挡住的）。
    try:
        tk.Misc.lower(canvas)
    except Exception:
        pass

    def redraw(event=None):
        try:
            w=max(1,win.winfo_width());h=max(1,win.winfo_height())
            r=max(0,min(radius,w//2,h//2))
            canvas.delete('bg')
            pts=_rounded_points(0,0,w,h,r)
            canvas.create_polygon([v for p in pts for v in p],fill=CARD,outline=LINE,
                                  width=1,tags='bg')
            canvas.lower('bg')
        except Exception:
            pass

    win.bind('<Configure>',redraw)
    try:
        win.after(0,redraw)
    except Exception:
        pass
    return canvas

def configure(root):
    style=ttk.Style(root)
    for name,color in [('Pet.TFrame',BG),('Pet.Card.TFrame',CARD)]:style.configure(name,background=color)
    style.configure('Pet.TLabel',background=BG,foreground=INK,font=FONT)
    style.configure('Pet.Muted.TLabel',background=BG,foreground=MUTED,font=FONT)
    style.configure('Pet.Title.TLabel',background=BG,foreground=INK,font=('Microsoft YaHei UI',17,'bold'))
    style.configure('Pet.TButton',font=FONT,padding=(12,7))
    style.configure('Pet.TCheckbutton',background=BG,foreground=INK,font=FONT,padding=5)
    style.configure('Pet.TNotebook',background=BG,borderwidth=0)
    style.configure('Pet.TNotebook.Tab',padding=(20,9),font=FONT)
    style.configure('Pet.Treeview',font=FONT,rowheight=34,background=CARD,fieldbackground=CARD,foreground=INK,borderwidth=0)
    style.configure('Pet.Treeview.Heading',font=('Microsoft YaHei UI',10,'bold'),foreground=MUTED,padding=9)
    style.map('Pet.Treeview',background=[('selected','#DCE7E9')],foreground=[('selected',INK)])

def apply(window):
    configure(window);window.configure(bg=BG)
    styles={'TFrame':'Pet.TFrame','TLabel':'Pet.TLabel','TButton':'Pet.TButton',
            'TCheckbutton':'Pet.TCheckbutton','TNotebook':'Pet.TNotebook','Treeview':'Pet.Treeview'}
    def visit(widget):
        name=widget.winfo_class()
        if name in styles and not str(widget.cget('style')).startswith('Pet.'):
            widget.configure(style=styles[name])
        if isinstance(widget,tk.Text):
            widget.configure(bg=CARD,fg=INK,insertbackground=INK,selectbackground='#DCE7E9',selectforeground=INK,
                             relief='flat',highlightthickness=1,highlightbackground=LINE,padx=10,pady=8,font=FONT)
        for child in widget.winfo_children():visit(child)
    visit(window)

def copy_text(widget,all_text=False):
    try:text=widget.get('1.0','end-1c') if all_text else widget.get('sel.first','sel.last')
    except tk.TclError:return 'break'
    widget.clipboard_clear();widget.clipboard_append(text)
    return 'break'

def copy_bindings(widget):
    # 这些回调偶尔会被 Tk 无参调用（例如控件销毁/无事件触发），一律给默认参数兜底，
    # 否则会往 error.log 里写 "missing 1 required positional argument: 'e'"。
    widget.bind('<Control-c>',lambda e=None:copy_text(widget));widget.bind('<Control-C>',lambda e=None:copy_text(widget))
    def select_all(event=None):
        widget.tag_add('sel','1.0','end-1c');widget.mark_set('insert','1.0');return 'break'
    widget.bind('<Control-a>',select_all);widget.bind('<Control-A>',select_all)
    menu=tk.Menu(widget,tearoff=False)
    menu.add_command(label='复制所选',command=lambda:copy_text(widget))
    menu.add_command(label='全选',command=select_all)
    menu.add_command(label='复制全部',command=lambda:copy_text(widget,True))
    widget.bind('<Button-3>',lambda e=None:menu.tk_popup(e.x_root,e.y_root) if e is not None else None)
    return menu
