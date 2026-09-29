"""Dark artwork windows, with a separate light palette for decorated chat skins."""
import tkinter as tk
import sys
from tkinter import ttk
from tkinter import font as tkfont

BG='#101824';CARD='#202D40';INK='#F0F5FC';MUTED='#CAD6E6';ACCENT='#79D8FA';LINE='#52667E'
FONT=('Microsoft YaHei UI',10)
TITLE_FONT=(FONT[0],16,'bold')
SECTION_FONT=(FONT[0],11,'bold')
CAPTION_FONT=(FONT[0],9)
PAGE_X=22
HEADER_PADDING=(PAGE_X,18,PAGE_X,14)
WINDOW_BORDER='#193653'
WINDOW_CAPTION='#142C46'
LIGHT_INK='#263E58';LIGHT_MUTED='#62778E'
DARK=dict(bg=BG,card=CARD,ink=INK,muted=MUTED,accent=ACCENT,line=LINE,
          selected='#365B7A',button='#334359',primary='#DCEAF6',primary_ink='#20374A',dark=True)
LIGHT=dict(bg='#F6F9FD',card='#FFFFFF',ink=LIGHT_INK,muted=LIGHT_MUTED,
           accent='#426C9C',line='#92ABC7',selected='#D7E7F9',button='#E8F0FA',
           primary='#F7FBFF',primary_ink=LIGHT_INK,dark=False)


def palette(widget):
    return LIGHT if getattr(widget.winfo_toplevel(),'_compact_surface',False) else DARK


def page_header(window, text):
    """Same title baseline/inset in every normal dialog; caller chooses pack/grid."""
    head=ttk.Frame(window,padding=HEADER_PADDING,style='Pet.TFrame')
    head._glass_panel='header'
    label=ttk.Label(head,text=text,style='Pet.Title.TLabel',font=TITLE_FONT,anchor='w')
    label._type_role='title'
    label.pack(side='left',anchor='n')
    head.title_label=label
    window._page_header=head
    return head


def native_chrome(window):
    """Color only this window's native frame/caption, not entry or button borders.

    DWM attributes 34/35/36 require Windows 11; older systems retain dark mode.
    https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
    """
    if sys.platform!='win32' or window.overrideredirect():return
    try:
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        user32.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
        user32.GetAncestor.restype=wintypes.HWND
        hwnd=user32.GetAncestor(wintypes.HWND(window.winfo_id()),2)
        if not hwnd:return
        if getattr(window,'_chrome_handle',None)==hwnd:return
        color=lambda value:int(value[5:7]+value[3:5]+value[1:3],16)
        results={}
        for attribute,value in ((20,1),(34,color(WINDOW_BORDER)),(35,color(WINDOW_CAPTION)),(36,color(INK))):
            native=ctypes.c_uint32(value)
            results[attribute]=ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd),attribute,
                ctypes.byref(native),ctypes.sizeof(native))==0
        window._chrome_handle=hwnd
        window._chrome_attributes=results
    except (AttributeError,OSError,ValueError,tk.TclError):pass


def configure(root):
    # Widgets must measure with the final font before flow/pack/grid layout.
    root.option_add('*Font',FONT)
    style=ttk.Style(root)
    if style.theme_use() != 'clam':style.theme_use('clam')
    style.configure('.',font=FONT)
    for name,color in [('Pet.TFrame',BG),('Pet.Card.TFrame',CARD)]:style.configure(name,background=color)
    style.configure('Pet.TLabel',background=BG,foreground=INK,font=FONT)
    style.configure('Pet.Muted.TLabel',background=BG,foreground=MUTED,font=FONT)
    style.configure('Pet.Title.TLabel',background=BG,foreground=INK,font=TITLE_FONT)
    style.configure('Pet.Section.TLabel',background=BG,foreground=INK,font=SECTION_FONT)
    style.configure('Pet.Caption.TLabel',background=BG,foreground=MUTED,font=CAPTION_FONT)
    style.configure('Pet.TButton',font=FONT,padding=(15,8))
    style.configure('Pet.TButton',background=DARK['button'],foreground=INK,borderwidth=0)
    style.map('Pet.TButton',background=[('active','#405872'),('pressed','#294158')],foreground=[('disabled','#8998AA')])
    style.configure('Pet.TEntry',font=FONT,fieldbackground=CARD,foreground=INK,padding=6,bordercolor=LINE)
    style.configure('Pet.TCombobox',font=FONT,fieldbackground=CARD,foreground=INK,padding=5)
    style.configure('Pet.TSpinbox',font=FONT,fieldbackground=CARD,foreground=INK,arrowcolor=MUTED,
                    background=DARK['button'],bordercolor=LINE,padding=5)
    style.map('Pet.TSpinbox',fieldbackground=[('disabled',BG)],foreground=[('disabled','#91A1B7')])
    style.map('Pet.TCombobox',fieldbackground=[('readonly',CARD)],selectbackground=[('readonly',CARD)],selectforeground=[('readonly',INK)])
    style.configure('Pet.TLabelframe',background=BG,bordercolor=LINE)
    style.configure('Pet.TLabelframe.Label',background=BG,foreground=MUTED,font=FONT)
    style.configure('Pet.TRadiobutton',background=BG,foreground=INK,font=FONT,padding=4)
    for direction in ('Vertical','Horizontal'):
        style.configure(f'Pet.{direction}.TScrollbar',background=ACCENT,troughcolor=BG,borderwidth=0,arrowsize=7)
    style.configure('Pet.TCheckbutton',background=BG,foreground=INK,font=FONT,padding=5)
    style.configure('Pet.TNotebook',background=BG,borderwidth=0)
    style.configure('Pet.TNotebook.Tab',padding=(20,9),font=FONT)
    style.map('Pet.TNotebook.Tab',background=[('selected',CARD),('!selected',BG)],foreground=[('selected',ACCENT),('!selected',MUTED)])
    style.configure('Pet.Treeview',font=FONT,rowheight=34,background=CARD,fieldbackground=CARD,foreground=INK,borderwidth=0)
    style.configure('Pet.Treeview.Heading',font=('Microsoft YaHei UI',10,'bold'),background=CARD,foreground=MUTED,padding=9)
    style.map('Pet.Treeview.Heading',background=[('active',DARK['button'])])
    style.map('Pet.Treeview',background=[('selected',DARK['selected'])],foreground=[('selected',INK)])

def apply(window,artwork=True):
    configure(window);window.configure(bg=BG,bd=0,highlightthickness=0)
    native_chrome(window)
    styles={'TFrame':'Pet.TFrame','TLabel':'Pet.TLabel','TButton':'Pet.TButton',
            'TCheckbutton':'Pet.TCheckbutton','TNotebook':'Pet.TNotebook','Treeview':'Pet.Treeview',
            'TEntry':'Pet.TEntry','TCombobox':'Pet.TCombobox','TLabelframe':'Pet.TLabelframe',
            'TRadiobutton':'Pet.TRadiobutton','TSpinbox':'Pet.TSpinbox'}
    def visit(widget):
        if getattr(widget,'_compact_surface',False) or getattr(widget,'_art_decoration',False) or getattr(widget,'_glass_button',False):return
        name=widget.winfo_class()
        if name=='TScrollbar' and not str(widget.cget('style')).startswith('Pet.'):
            widget.configure(style=f"Pet.{str(widget.cget('orient')).capitalize()}.TScrollbar")
        if name in styles and not str(widget.cget('style')).startswith('Pet.'):
            widget.configure(style=styles[name])
        if isinstance(widget,ttk.Widget):
            if name=='TLabel':
                role=str(widget.cget('style'))
                semantic=getattr(widget,'_type_role',None)
                if semantic is None:
                    semantic=next((key for key in ('Title','Section','Caption') if '.'+key+'.' in role),'Body').lower()
                    widget._type_role=semantic
                fonts={'title':TITLE_FONT,'section':SECTION_FONT,'caption':CAPTION_FONT}
                widget.configure(font=fonts.get(semantic,FONT))
            for child in widget.winfo_children():visit(child)
            return
        if isinstance(widget,tk.Text):
            widget.configure(bg=CARD,fg=INK,insertbackground=INK,selectbackground=DARK['selected'],selectforeground=INK,
                             relief='flat',highlightthickness=1,highlightbackground=LINE,padx=14,pady=10,font=FONT,
                             spacing1=3,spacing3=6)
        elif isinstance(widget,(tk.Frame,tk.LabelFrame)):
            widget.configure(bg=BG)
        elif isinstance(widget,tk.Label):
            previous=tkfont.Font(root=window,font=widget.cget('font'))
            role=getattr(widget,'_type_role','body')
            fonts={'title':TITLE_FONT,'section':SECTION_FONT,'caption':CAPTION_FONT}
            widget.configure(bg=BG,fg=INK,font=fonts.get(role,(FONT[0],FONT[1],previous.cget('weight'))))
        elif isinstance(widget,tk.Button):
            widget.configure(bg=DARK['button'],fg=INK,activebackground='#405872',activeforeground=INK,
                             relief='flat',bd=0,cursor='hand2',font=FONT)
        elif isinstance(widget,(tk.Entry,tk.Listbox)):
            widget.configure(bg=CARD,fg=INK,font=FONT,relief='flat',highlightthickness=1,highlightbackground=LINE,
                             selectbackground=DARK['selected'],selectforeground=INK)
        elif isinstance(widget,tk.Spinbox):
            widget.configure(bg=CARD,fg=INK,buttonbackground=DARK['button'],insertbackground=INK,
                             relief='flat',highlightthickness=1,highlightbackground=LINE,font=FONT)
        elif isinstance(widget,(tk.Checkbutton,tk.Radiobutton)):
            widget.configure(bg=BG,fg=INK,activebackground=BG,selectcolor=CARD,font=FONT)
        elif isinstance(widget,tk.Scrollbar):
            widget.configure(bg=ACCENT,activebackground=ACCENT,troughcolor=BG,bd=0,relief='flat',
                             highlightthickness=0,width=9)
        elif isinstance(widget,tk.Canvas) and widget.cget('bg') in ('#2b2b3a','#f0f0f0'):
            widget.configure(bg=BG)
        for child in widget.winfo_children():visit(child)
    visit(window)
    if artwork:
        from window_art import attach
        attach(window)


def install(root):
    """Theme ordinary dialogs and later-created controls; leave the pet/capture overlay alone."""
    configure(root)
    def mapped(event):
        widget=event.widget
        if getattr(widget,'_art_decoration',False):return
        try:
            window=widget.winfo_toplevel()
            if not isinstance(window,tk.Toplevel) or window.overrideredirect() or getattr(window,'_compact_surface',False):return
            if getattr(window,'_theme_pending',False):return
            window._theme_pending=True
            def refresh():
                window._theme_pending=False
                if window.winfo_exists():apply(window)
            window.after_idle(refresh)
        except tk.TclError:pass
    root.bind_all('<Map>',mapped,add='+')

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
