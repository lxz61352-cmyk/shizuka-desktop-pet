"""Decorated, resizable chat skins; one native window and no card artwork."""
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from PIL import Image,ImageTk
from ui_theme import LIGHT_INK as INK,FONT

KEY='#01FE02'
SURFACE='#F6F9FE'
SKIN_DIR=Path(__file__).resolve().parents[1]/'assets/ui/ornamental-v2'

@lru_cache(maxsize=2)
def skin(kind):
    with Image.open(SKIN_DIR/f'{kind}.png') as source:return source.convert('RGBA')

def skin_bitmap(kind,width,height):
    """Nine-slice the original: ornaments and speech tail keep their shape."""
    source=skin(kind);sw,sh=source.size;scale=width/sw
    left,right,top,bottom=320,360,360,350 if kind=='composer' else 390
    dl,dr,dt,db=[round(n*scale) for n in (left,right,top,bottom)]
    if dt+db>=height:
        ratio=(height-1)/(dt+db);dt=int(dt*ratio);db=int(db*ratio)
    sx=(0,left,sw-right,sw);sy=(0,top,sh-bottom,sh)
    dx=(0,dl,width-dr,width);dy=(0,dt,height-db,height)
    result=Image.new('RGBA',(width,height))
    for col in range(3):
        for row in range(3):
            tile=source.crop((sx[col],sy[row],sx[col+1],sy[row+1]))
            tile=tile.convert('RGBa').resize((dx[col+1]-dx[col],dy[row+1]-dy[row]),Image.Resampling.LANCZOS).convert('RGBA')
            result.paste(tile,(dx[col],dy[row]))
    return result

def surface(parent,width,height,title,kind='composer'):
    window=tk.Toplevel(parent);window.withdraw();window.overrideredirect(True)
    window._compact_surface=True;window._surface_kind=kind
    window.configure(bg=KEY);window.attributes('-topmost',True)
    try:window.attributes('-transparentcolor',KEY)
    except tk.TclError:window.configure(bg=SURFACE)
    canvas=tk.Canvas(window,bg=KEY,highlightthickness=0,bd=0)
    canvas._art_decoration=True;canvas.pack(fill='both',expand=True)
    decorations={};pending=None;painting=False
    def repaint():
        nonlocal pending,painting
        pending=None
        if not window.winfo_exists():return
        painting=True
        try:
            from backdrop_widgets import paint_children
            paint_children(window,window._surface_image,decorations)
        finally:painting=False
    def schedule(event=None):
        nonlocal pending
        if painting or getattr(getattr(event,'widget',None),'_art_decoration',False):return
        if pending:window.after_cancel(pending)
        pending=window.after(35,repaint)
    def dispose(event):
        nonlocal pending
        if event.widget is window and pending:
            window.after_cancel(pending);pending=None
    def resize(new_height):
        window._frame_offset=(0,0);window._frame_size=(width,new_height)
        window.geometry(f'{width}x{new_height}')
        rgba=skin_bitmap(kind,width,new_height)
        mask=rgba.getchannel('A').point(lambda a:255 if a>=128 else 0)
        window._frame_visible=mask.getbbox() or (0,0,width,new_height)
        # Tk color-key is binary; never blend soft edges against chroma green.
        art=Image.new('RGB',rgba.size,KEY);art.paste(rgba.convert('RGB'),(0,0),mask)
        window._surface_image=art
        window._surface_photo=ImageTk.PhotoImage(art,master=window)
        canvas.delete('decoration')
        canvas.create_image(0,0,image=window._surface_photo,anchor='nw',tags='decoration')
        if title:
            canvas.create_text(86,37,text=title,anchor='w',fill=INK,font=(FONT[0],10,'bold'),tags='decoration')
        canvas.tag_lower('decoration')
        window.event_generate('<<SurfaceChanged>>',when='tail');schedule()
    window.bind('<Configure>',schedule,add='+');window.bind('<Map>',schedule,add='+')
    window.bind('<Destroy>',dispose,add='+')
    resize(height)
    return window,canvas,resize

def button(parent,text,command,primary=False):
    from glass_button import GlassButton
    return GlassButton(parent,text,command,primary=primary)
