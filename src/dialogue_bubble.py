"""Single-window, selectable speech bubble with bounded streaming layout."""
import math
import tkinter as tk
from tkinter import font as tkfont
from desktop_surface import surface, button, SURFACE
from ui_theme import LIGHT_MUTED as MUTED, FONT, copy_text
from art_transcript import ArtTranscript

BUBBLE_W=440


def make_bubble(parent, **unused):
    width=min(BUBBLE_W,max(280,parent.winfo_screenwidth()-40))
    win,canvas,resize=surface(parent,width,230,'',kind='reply')
    font=tkfont.Font(root=parent,family=FONT[0],size=11)
    line_height=font.metrics('linespace')+7
    box=ArtTranscript(win,plain=True)
    box.place(x=48,y=70,width=width-96,height=32)
    state={'text':'','height':None,'pending':None}
    win._show_all=False;win._text_box=box
    from tkinter import ttk
    footer=ttk.Frame(win)
    footer.place(x=42,y=150,width=width-108,height=35)
    hint=ttk.Label(win,text='',foreground=MUTED,font=(FONT[0],8))
    hint.place(x=48,y=120)
    button(footer,'收起',win.withdraw).pack(side='right')
    button(footer,'复制',lambda:copy_text(box,True)).pack(side='right')

    def expand():
        win._show_all=not win._show_all
        if win._show_all:getattr(win,'_reveal_all',lambda:None)()
        layout()
    expand_button=button(footer,'展开',expand);expand_button.pack(side='right')

    def layout():
        if state['pending'] is not None:win.after_cancel(state['pending'])
        state['pending']=None
        if not win.winfo_exists():return
        text_full_height=max(line_height,getattr(box,'content_height',line_height))
        screen_limit=max(60,parent.winfo_screenheight()-240)
        limit=screen_limit if win._show_all else min(9*line_height,screen_limit)
        text_height=min(text_full_height+4,limit)
        height=max(230,70+text_height+110)
        if height!=state['height']:
            state['height']=height;resize(height)
            box.place_configure(height=text_height)
            footer.place_configure(y=height-86)
            hint.place_configure(y=height-107)
        box.set_backdrop(win._surface_image.crop((48,70,width-48,70+text_height)))
        hint.configure(text='滚动可查看全文' if text_full_height>text_height else '')
        expand_button.configure(text='折叠' if win._show_all else '展开')

    def set_text(value):
        value=value or '…';follow=box.yview()[1]>=.985
        state['text']=value
        box.rows=[{'role':'assistant','text':value}];box.render()
        if state['pending'] is None:state['pending']=win.after(30,layout)
        if follow:box.yview_moveto(1);box.paint()

    def destroy(event):
        if event.widget is win and state['pending'] is not None:
            win.after_cancel(state['pending']);state['pending']=None
    win.bind('<Destroy>',destroy,add='+')
    win.bind('<Escape>',lambda e:win.withdraw())
    win.bind('<Map>',lambda e:layout() if e.widget is win else None,add='+')
    set_text('…');layout()
    return win,set_text
