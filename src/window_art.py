"""Local, sourced artwork and per-window backgrounds. No runtime network access."""
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import time
import tkinter as tk
from PIL import Image, ImageDraw, ImageOps, ImageTk, ImageFilter
from backdrop_frame import frame_update

REVISION = 'opaque-resize-v4'

ART_DIR = Path(__file__).resolve().parents[1]/'assets/backgrounds/shizuka'
PREFERENCES={'background_file':'','blur':8,'darkness':.64}
TIMINGS=[]
# Workers only decode/process PIL images. All Tk calls and PhotoImages stay on
# the UI thread. Each window keeps at most one outstanding request.
_WORKER=ThreadPoolExecutor(max_workers=2,thread_name_prefix='window-art')


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
def rendered_background(filename,width,height,blur=8,darkness=.64,resolution=800):
    # Crop centrally at the working resolution, avoiding a full-size resize
    # immediately followed by a downsize. An unblurred image keeps its detail.
    scale=min(1,resolution/max(width,height)) if blur else 1
    size=(max(1,round(width*scale)),max(1,round(height*scale)))
    small=ImageOps.fit(artwork(filename),size,centering=(.5,.5))
    if blur:small=small.filter(ImageFilter.GaussianBlur(blur*scale))
    # The constant tint commutes with scaling. Blend at working resolution,
    # avoiding two full-window buffers and a full-resolution blend on the UI.
    if darkness:small=Image.blend(small,Image.new('RGB',size,'#101824'),darkness)
    return small.resize((width,height),Image.Resampling.BILINEAR)


def background(card, width, height, header=0):
    """One dark, defocused card, including every gutter behind the controls."""
    width,height=max(1,width),max(1,height)
    paper=Image.new('RGB',(width,height),'#101824')
    if card:
        try:
            return rendered_background(card['file'],width,height,PREFERENCES['blur'],PREFERENCES['darkness'])
        except (OSError,ValueError):pass
    return paper


def _prepare(request):
    filename,width,height,blur,darkness=request
    if filename:
        try:return rendered_background(filename,width,height,blur,darkness)
        except (OSError,ValueError):pass
    return Image.new('RGB',(width,height),'#101824')


class WindowBackdrop:
    def __init__(self,window):
        self.window=window;self.card=choose();self.pending=None;self.size=None
        self.background_file=PREFERENCES['background_file']
        self.decorations={};self.image=None;self.rendering=False;self.signature=None
        self.future=None;self.request=None;self.prepared=None;self.panel_signature=None
        self.disposed=False;self.resize_pending=None;self.preview_request=None
        self.canvas=tk.Canvas(window,highlightthickness=0,bd=0,bg='#101824')
        self.background_item=self.canvas.create_image(0,0,anchor='nw')
        self.canvas._art_decoration=True
        self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
        window.tk.call('lower',self.canvas._w)
        self.canvas.bind('<Configure>',self.schedule)
        window.bind('<Configure>',self.schedule,add='+')
        window.bind('<Destroy>',self.dispose,add='+')
        self.schedule()

    def shuffle(self):
        self.card=choose(self.card['file'] if self.card else None);self.prepared=None;self.signature=None;self.schedule()

    def reload_preferences(self):
        if self.background_file!=PREFERENCES['background_file']:
            self.background_file=PREFERENCES['background_file'];self.card=choose()
        self.prepared=None;self.signature=None;self.schedule()

    def schedule(self,event=None):
        if self.rendering or self.disposed:return
        if event is not None and getattr(event.widget,'_art_decoration',False) and event.widget is not self.canvas:return
        if event is not None and event.widget is self.window:
            if (event.width,event.height)==self.size and self.image is not None and self.image.size==self.size:return
        if event is not None and event.widget in (self.window,self.canvas) and self.image is not None:
            self.resize_surface()
        if event is not None:
            if self.image is not None and self.resize_pending is None:
                self.resize_pending=self.window.after_idle(self.resize_preview)
        if self.pending:return
        self.pending=self.window.after_idle(self.draw) if self.image is None else self.window.after(24,self.draw)

    def resize_surface(self):
        """Cover new client bounds before idle child layout/worker completion.

        A maximize changes the native surface immediately. Waiting until idle
        leaves the enlarged canvas uncovered. Upload only its proportional
        background now; normal preview processing then updates child crops.
        """
        size=(self.window.winfo_width(),self.window.winfo_height())
        if min(size)<2 or self.image.size==size:return
        request=(self.card['file'] if self.card else None,*size,PREFERENCES['blur'],PREFERENCES['darkness'])
        if request==self.prepared:self.base_image=self.prepared_image
        else:
            try:self.base_image=rendered_background(*request,resolution=400) if request[0] else Image.new('RGB',size,'#101824')
            except (OSError,ValueError):self.base_image=Image.new('RGB',size,'#101824')
        self.image=self.base_image
        self.rendering=True
        try:
            with frame_update(self.window):
                # Retain the old texture until the replacement is connected,
                # then finish Canvas's idle paint before returning from resize.
                previous_photo=self.photo
                photo=ImageTk.PhotoImage(self.image,master=self.window)
                self.canvas.itemconfigure(self.background_item,image=photo)
                self.photo=photo
                self.preview_request=None if request==self.prepared else request
                self.signature=None;self.panel_signature=None
        finally:self.rendering=False

    def resize_preview(self):
        """Keep correct source proportions while the full-quality worker catches up."""
        self.resize_pending=None
        if self.rendering or self.disposed or not self.window.winfo_exists() or not self.window.winfo_ismapped():return
        size=(self.window.winfo_width(),self.window.winfo_height())
        if min(size)<2:return
        request=(self.card['file'] if self.card else None,*size,PREFERENCES['blur'],PREFERENCES['darkness'])
        signature=self.layout_signature()
        if (self.image is not None and self.image.size==size and signature==self.signature
                and request in (self.preview_request,self.prepared)):return
        if request==self.preview_request and self.image is not None and self.image.size==size:
            if signature!=self.signature:self.present(size,signature,False)
            return
        # Fit the original artwork, never stretch the previous window crop.
        # Low-resolution blur is cheap; only detail changes in the final frame.
        changed=(self.image is None or self.image.size!=size
                 or request not in (self.prepared,self.preview_request))
        if request==self.prepared:
            self.base_image=self.prepared_image
        elif request[0]:
            try:self.base_image=rendered_background(*request,resolution=400)
            except (OSError,ValueError):self.base_image=Image.new('RGB',size,'#101824')
        else:self.base_image=Image.new('RGB',size,'#101824')
        self.preview_request=None if request==self.prepared else request
        self.present(size,signature,changed)

    def present(self,size,signature,changed):
        self.rendering=True;started=time.perf_counter()
        try:
            with frame_update(self.window):
                panels=tuple(row[1:6] for row in signature if row[5])
                if changed or panels!=self.panel_signature or self.image is None:
                    self.image=self.panels(panels)
                    if hasattr(self,'photo') and (self.photo.width(),self.photo.height())==size:
                        self.photo.paste(self.image)
                    else:
                        self.photo=ImageTk.PhotoImage(self.image,master=self.window)
                        self.canvas.itemconfigure(self.background_item,image=self.photo)
                    self.panel_signature=panels
                from backdrop_widgets import paint_children
                paint_children(self.window,self.image,self.decorations,self.photo)
                self.signature=signature
        finally:
            self.rendering=False
            TIMINGS.append((time.perf_counter()-started)*1000)
            del TIMINGS[:-30]
        if self.image.size!=(self.window.winfo_width(),self.window.winfo_height()) or self.signature!=self.layout_signature():
            # Draining Tk paints can also finish a queued geometry pass. Cover
            # that final layout at idle, rather than exposing it for 24 ms.
            if self.resize_pending is None:self.resize_pending=self.window.after_idle(self.resize_preview)
            self.schedule()

    def layout_signature(self):
        rows=[]
        ox,oy=self.window.winfo_rootx(),self.window.winfo_rooty()
        def visit(widget,clip):
            if (getattr(widget,'_art_decoration',False) or getattr(widget,'_art_hidden',False)
                    or isinstance(widget,tk.Toplevel)):return
            if widget.winfo_ismapped():
                x,y=widget.winfo_rootx()-ox,widget.winfo_rooty()-oy
                bounds=(x,y,x+widget.winfo_width(),y+widget.winfo_height())
                visible=(max(clip[0],bounds[0]),max(clip[1],bounds[1]),min(clip[2],bounds[2]),min(clip[3],bounds[3]))
                if visible[2]<=visible[0] or visible[3]<=visible[1]:return
                rows.append((widget,x,y,widget.winfo_width(),widget.winfo_height(),
                             getattr(widget,'_glass_panel',None),(widget.canvasx(0),widget.canvasy(0)) if isinstance(widget,tk.Canvas) else None))
                for child in widget.winfo_children():visit(child,visible)
        clip=(0,0,self.window.winfo_width(),self.window.winfo_height())
        for child in self.window.winfo_children():visit(child,clip)
        return tuple(rows)

    def ready(self):
        request=(self.card['file'] if self.card else None,self.window.winfo_width(),
                 self.window.winfo_height(),PREFERENCES['blur'],PREFERENCES['darkness'])
        # Configure/Map can enqueue an unchanged-frame check during native
        # redraw. Readiness describes the pixels and layout already presented,
        # rather than requiring that harmless bookkeeping queue to be empty.
        if (self.rendering or self.image is None or self.prepared!=request
                or self.preview_request not in (None,self.prepared)
                or self.size!=(self.window.winfo_width(),self.window.winfo_height())
                or self.signature!=self.layout_signature()):return False
        # A canvas/table may still be laying out text; do not fade a partially
        # built child just because the outer artwork has finished.
        return not any(any(getattr(row[0],name,None) for name in
                           ('pending','_layout_job','_reflow_pending'))
                       for row in self.signature if hasattr(row[0],'set_backdrop'))

    def crop(self,widget,wash=0):
        x=widget.winfo_rootx()-self.window.winfo_rootx()
        y=widget.winfo_rooty()-self.window.winfo_rooty()
        size=(max(1,widget.winfo_width()),max(1,widget.winfo_height()))
        image=self.image.crop((x,y,x+size[0],y+size[1]))
        if wash:image=Image.blend(image,Image.new('RGB',size,'#52647c'),wash)
        return image

    def panels(self,panels):
        """Composite glass once; all children then sample this exact same image."""
        if not panels:return self.base_image
        image=self.base_image.copy().convert('RGBA')
        layer=Image.new('RGBA',image.size);draw=ImageDraw.Draw(layer)
        for x,y,w,h,panel in panels:
            if w>1 and h>1:
                draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=12,
                    fill=(107,127,155,34),outline=(206,227,249,26))
                if panel=='header':
                    draw.line((x+22,y+h-2,x+w-22,y+h-2),fill=(114,215,247,210),width=1)
        return Image.alpha_composite(image,layer).convert('RGB')

    def draw(self):
        self.pending=None
        if self.disposed or not self.window.winfo_exists() or not self.window.winfo_ismapped():return
        size=(self.window.winfo_width(),self.window.winfo_height())
        if min(size)<2:return
        request=(self.card['file'] if self.card else None,*size,PREFERENCES['blur'],PREFERENCES['darkness'])
        # A previous render can finish during dragging. Show the latest crop
        # before waiting for another worker, without drawing stale dimensions.
        if self.image is not None and self.image.size!=size and self.resize_pending is None:
            self.resize_preview()
        changed=request!=self.prepared
        if changed:
            if self.future is not None and self.future.done():
                completed=self.future;self.future=None
                if self.request==request:
                    self.prepared_image=completed.result();self.prepared=request
            if self.prepared!=request:
                if self.future is None:
                    self.request=request;self.future=_WORKER.submit(_prepare,request)
                self.pending=self.window.after(12,self.draw)
                return
        changed=changed or self.preview_request is not None or self.image is None or self.image.size!=size
        self.base_image=self.prepared_image;self.size=size;self.preview_request=None
        signature=self.layout_signature()
        if not changed and signature==self.signature:return
        self.present(size,signature,changed)

    def dispose(self,event):
        if event.widget is self.window:
            self.disposed=True
            if self.pending:self.window.after_cancel(self.pending);self.pending=None
            if self.resize_pending:self.window.after_cancel(self.resize_pending);self.resize_pending=None
            if self.future:self.future.cancel();self.future=None
            self.signature=None;self.decorations.clear()
            if hasattr(self,'photo'):
                self.photo.__del__();del self.photo


def attach(window):
    if getattr(window,'_art_backdrop',None):
        window._art_backdrop.schedule();return
    if getattr(window,'_compact_surface',False) or window.overrideredirect():return
    # Explicit dialogs (including the small calendar) always use artwork.
    # Unmanaged tiny popups are also used as native menu/test containers.
    if not getattr(window,'_opening_started',False):
        width=max(window.winfo_width(),window.winfo_reqwidth())
        height=max(window.winfo_height(),window.winfo_reqheight())
        if width<350 or height<180:return
    window._art_backdrop=WindowBackdrop(window)
