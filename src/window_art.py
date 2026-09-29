"""Local, sourced artwork and per-window backgrounds. No runtime network access."""
from functools import lru_cache
import json
from pathlib import Path
import random
import time
import tkinter as tk
from PIL import Image, ImageDraw, ImageOps, ImageTk, ImageFilter

ART_DIR = Path(__file__).resolve().parents[1]/'assets/backgrounds/shizuka'
PREFERENCES={'background_file':'','blur':8,'darkness':.64}
TIMINGS=[]


def set_preferences(value):
    PREFERENCES.update({k:value[k] for k in PREFERENCES if k in value})


def performance():
    if not TIMINGS:return '本次启动尚无绘制样本'
    return f'最近 {len(TIMINGS)} 次平均 {sum(TIMINGS)/len(TIMINGS):.0f} ms；最近一次 {TIMINGS[-1]:.0f} ms；缓存命中 {rendered_background.cache_info().hits}'


@lru_cache(maxsize=1)
def catalog():
    try:
        rows = json.loads((ART_DIR/'manifest.json').read_text('utf-8'))['cards']
        return tuple(row for row in rows if Path(row['file']).name == row['file']
                     and (ART_DIR/row['file']).is_file())
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def choose(previous=None):
    cards = catalog()
    fixed=next((c for c in cards if c['file']==PREFERENCES['background_file']),None)
    if fixed:return fixed
    candidates = [card for card in cards if card['file'] != previous]
    return random.choice(candidates or cards) if cards else None


@lru_cache(maxsize=8)
def artwork(filename):
    with Image.open(ART_DIR/filename) as image:
        image=image.convert('RGB')
        image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
        return image


@lru_cache(maxsize=12)
def rendered_background(filename,width,height,blur=8,darkness=.64):
    cover=ImageOps.fit(artwork(filename),(width,height),centering=(.5,.5))
    # Blur at a bounded resolution, then enlarge the already defocused image.
    scale=min(1,800/max(width,height))
    small=cover.resize((max(1,round(width*scale)),max(1,round(height*scale))),Image.Resampling.BILINEAR)
    small=small.filter(ImageFilter.GaussianBlur(blur*scale))
    cover=small.resize((width,height),Image.Resampling.BILINEAR)
    return Image.blend(cover,Image.new('RGB',(width,height),'#101824'),darkness)


def background(card, width, height, header=0):
    """One dark, defocused card, including every gutter behind the controls."""
    width,height=max(1,width),max(1,height)
    paper=Image.new('RGB',(width,height),'#101824')
    if card:
        try:
            return rendered_background(card['file'],width,height,PREFERENCES['blur'],PREFERENCES['darkness'])
        except (OSError,ValueError):pass
    return paper


class WindowBackdrop:
    def __init__(self,window):
        self.window=window;self.card=choose();self.pending=None;self.size=None
        self.decorations={};self.image=None;self.rendering=False;self.signature=None
        self.canvas=tk.Label(window,highlightthickness=0,bd=0,bg='#101824')
        self.canvas._art_decoration=True
        self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
        window.tk.call('lower',self.canvas._w)
        self.canvas.bind('<Configure>',self.schedule)
        window.bind('<Configure>',self.schedule,add='+')
        window.bind('<Destroy>',self.dispose,add='+')
        self.schedule()

    def shuffle(self):
        self.card=choose(self.card['file'] if self.card else None);self.size=None;self.signature=None;self.schedule()

    def reload_preferences(self):
        self.card=choose();self.size=None;self.signature=None;self.schedule()

    def schedule(self,event=None):
        if self.rendering:return
        if event is not None and getattr(event.widget,'_art_decoration',False) and event.widget is not self.canvas:return
        if self.pending:return
        self.pending=self.window.after_idle(self.draw) if self.image is None else self.window.after(24,self.draw)

    def layout_signature(self):
        rows=[]
        def visit(widget):
            if getattr(widget,'_art_decoration',False) or isinstance(widget,tk.Toplevel):return
            if widget.winfo_ismapped():
                rows.append((str(widget),widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height(),
                             getattr(widget,'_glass_panel',None),widget.canvasy(0) if isinstance(widget,tk.Canvas) else None))
            for child in widget.winfo_children():visit(child)
        for child in self.window.winfo_children():visit(child)
        return tuple(rows)

    def crop(self,widget,wash=0):
        x=widget.winfo_rootx()-self.window.winfo_rootx()
        y=widget.winfo_rooty()-self.window.winfo_rooty()
        size=(max(1,widget.winfo_width()),max(1,widget.winfo_height()))
        image=self.image.crop((x,y,x+size[0],y+size[1]))
        if wash:image=Image.blend(image,Image.new('RGB',size,'#52647c'),wash)
        return image

    def panels(self):
        """Composite glass once; all children then sample this exact same image."""
        image=self.base_image.copy().convert('RGBA')
        layer=Image.new('RGBA',image.size);draw=ImageDraw.Draw(layer)
        def visit(widget):
            if isinstance(widget,tk.Toplevel) or getattr(widget,'_art_decoration',False):return
            panel=getattr(widget,'_glass_panel',None)
            if panel and widget.winfo_ismapped():
                x=widget.winfo_rootx()-self.window.winfo_rootx();y=widget.winfo_rooty()-self.window.winfo_rooty()
                w,h=widget.winfo_width(),widget.winfo_height()
                draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=12,
                    fill=(107,127,155,34),outline=(206,227,249,26))
                if panel=='header':
                    draw.line((x+22,y+h-2,x+w-22,y+h-2),fill=(114,215,247,210),width=1)
            for child in widget.winfo_children():visit(child)
        for child in self.window.winfo_children():visit(child)
        return Image.alpha_composite(image,layer).convert('RGB')

    def draw(self):
        self.pending=None
        if not self.window.winfo_exists():return
        size=(self.window.winfo_width(),self.window.winfo_height())
        if min(size)<2:return
        self.rendering=True
        started=time.perf_counter()
        try:
            changed=size!=self.size
            signature=self.layout_signature()
            if not changed and signature==self.signature:return
            if changed:
                self.size=size;self.base_image=background(self.card,*size)
            self.image=self.panels()
            self.photo=ImageTk.PhotoImage(self.image,master=self.window)
            self.canvas.configure(image=self.photo)
            from backdrop_widgets import paint_children
            paint_children(self.window,self.image,self.decorations)
            self.signature=signature
        finally:
            self.rendering=False
            TIMINGS.append((time.perf_counter()-started)*1000)
            del TIMINGS[:-30]

    def dispose(self,event):
        if event.widget is self.window and self.pending:
            self.window.after_cancel(self.pending);self.pending=None


def attach(window):
    if getattr(window,'_art_backdrop',None):
        window._art_backdrop.schedule();return
    if getattr(window,'_compact_surface',False) or window.overrideredirect():return
    width=max(window.winfo_width(),window.winfo_reqwidth())
    height=max(window.winfo_height(),window.winfo_reqheight())
    if width<350 or height<180:return
    window._art_backdrop=WindowBackdrop(window)
