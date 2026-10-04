"""Paint each native widget from the same window image, including ttk padding.

An image *element* covers a ttk widget's complete rectangle. A child Label does
not: ttk clips children to its padded content area, leaving opaque gutters.
"""
from itertools import count
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk
from ui_theme import palette

_elements=count()


def translucent_text(widget):
    """Transparent field backgrounds, with opaque text and native bindings.

    A colour key removes only the field fill. Empty pixels forward mouse
    events back to the original editor. Existing explicit opacity choices
    (computer task controls) retain their selected translucency.
    """
    import sys
    opacity=getattr(widget,'_glass_text_opacity',None)
    if sys.platform!='win32':return
    handle=widget.winfo_id()
    if opacity is None:
        color=widget.cget('bg') if not isinstance(widget,ttk.Widget) else palette(widget)['card']
        color=widget.winfo_rgb(color)
        key=(color[0]//257)|((color[1]//257)<<8)|((color[2]//257)<<16)
        alpha,flags=255,1
    else:key,alpha,flags=0,round(255*max(.1,min(1,opacity))),2
    if (getattr(widget,'_glass_text_handle',None)==handle
            and getattr(widget,'_glass_text_parameters',None)==(key,alpha,flags)):return
    import ctypes
    from ctypes import wintypes
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.GetWindowLongW.argtypes=(wintypes.HWND,ctypes.c_int)
    user32.GetWindowLongW.restype=ctypes.c_long
    user32.SetWindowLongW.argtypes=(wintypes.HWND,ctypes.c_int,ctypes.c_long)
    user32.SetWindowLongW.restype=ctypes.c_long
    user32.SetLayeredWindowAttributes.argtypes=(wintypes.HWND,wintypes.COLORREF,ctypes.c_ubyte,wintypes.DWORD)
    user32.SetLayeredWindowAttributes.restype=wintypes.BOOL
    style=user32.GetWindowLongW(handle,-20)
    user32.SetWindowLongW(handle,-20,style|0x80000)
    if user32.SetLayeredWindowAttributes(handle,key,alpha,flags):
        widget._glass_text_handle=handle
        widget._glass_text_alpha=alpha
        widget._glass_text_parameters=(key,alpha,flags)
        if flags==1:
            from glass_editors import register
            register(widget)
    else:user32.SetWindowLongW(handle,-20,style)


def manage_images(widget):
    """Release Tk resources on Destroy, before a worker can collect a cycle."""
    if getattr(widget,'_backdrop_cleanup_bound',False):return
    widget._backdrop_cleanup_bound=True
    def cleanup(event):
        if event.widget is not widget:return
        for name in ('_backdrop_photo','_backdrop_arrow','_art_photo'):
            photo=getattr(widget,name,None)
            if photo is not None:
                # ImageTk clears its underlying Tk image name in __del__;
                # plain Tk PhotoImage needs the name cleared explicitly.
                photo.__del__()
                if isinstance(photo,tk.PhotoImage):photo.name=None
                setattr(widget,name,None)
        widget._backdrop_source=None
    widget.bind('<Destroy>',cleanup,add='+')


def _replace(layout, names, element):
    result=[]
    for name, options in layout:
        options=dict(options)
        if 'children' in options:
            options['children']=_replace(options['children'],names,element)
        result.append((element if name in names else name,options))
    return result


def paint_ttk(widget,image,source_photo=None,bounds=None):
    kind=widget.winfo_class()
    colors=palette(widget)
    targets={
        'TFrame':{'Frame.border'}, 'TLabelframe':{'Labelframe.border'},
        'TLabel':{'Label.border'}, 'TEntry':{'Entry.field'},
        'TCombobox':{'Combobox.field'}, 'TSpinbox':{'Spinbox.field'}, 'TButton':{'Button.border'},
        'TScrollbar':{'Vertical.Scrollbar.trough','Horizontal.Scrollbar.trough'},
        'TCheckbutton':{'Checkbutton.padding'},
        'TRadiobutton':{'Radiobutton.padding'},
    }
    if kind not in targets:return False
    manage_images(widget)
    theme=ttk.Style(widget)
    if not hasattr(widget,'_backdrop_photo'):
        base=widget.cget('style') or kind
        if kind=='TScrollbar' and base=='TScrollbar':
            base=str(widget.cget('orient')).capitalize()+'.TScrollbar'
        serial=next(_elements)
        style=f'Pet.Art{serial}.{base}'
        element=f'Pet.art{serial}'
        photo=tk.PhotoImage(master=widget)
        # Zero requested size preserves intrinsic text sizing and frame padding.
        theme.element_create(element,'image',photo,sticky='nswe',width=0,height=0)
        layout=_replace(theme.layout(base),targets[kind],element)
        if kind=='TCombobox':
            arrow=tk.PhotoImage(master=widget);arrow_name=element+'.downarrow'
            theme.element_create(arrow_name,'image',arrow,sticky='nswe',width=20,height=0)
            widget._backdrop_arrow=arrow
            layout=[(element,{'sticky':'nswe','children':[
                (arrow_name,{'side':'right','sticky':'ns'}),
                ('Combobox.padding',{'sticky':'nswe','children':[('Combobox.textarea',{'sticky':'nswe'})]})]})]
        elif kind=='TButton':
            layout=[(element,{'sticky':'nswe','children':[
                ('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})]
        elif kind=='TLabel':
            # An image border must not consume the label's text cavity.
            layout=[(element,{'sticky':'nswe','children':[
                ('Label.padding',{'sticky':'nswe','children':[('Label.label',{'sticky':'nswe'})]})]})]
        elif kind=='TScrollbar':
            direction=str(widget.cget('orient')).capitalize()
            layout=[(element,{'sticky':'nswe','children':[
                (direction+'.Scrollbar.thumb',{'sticky':'nswe','expand':1})]})]
        theme.layout(style,layout)
        widget._backdrop_photo=photo
        widget._backdrop_style=style
        widget.configure(style=style)
    art=image.copy().convert('RGB')
    if kind in ('TEntry','TCombobox','TSpinbox'):
        # The field has only a fine outline; its interior is the actual card.
        ImageDraw.Draw(art).rounded_rectangle((0,0,art.width-1,art.height-1),radius=5,outline=colors['line'])
    elif kind=='TButton':
        from glass_button import button_bitmap
        art=button_bitmap(art,hover=widget.instate(('active',)),focus=widget.instate(('focus',)),dark=colors['dark'])
    # Tk accepts raw PPM pixels. PNG compression/decompression here used to
    # block the UI for every label, frame and entry on every repaint.
    if (source_photo is not None and kind not in ('TEntry','TCombobox','TSpinbox','TButton')
            and bounds[0]>=0 and bounds[1]>=0
            and bounds[2]<=source_photo.width() and bounds[3]<=source_photo.height()):
        # Copy from the one already-uploaded window texture inside Tk. Avoid
        # serialising/decoding another full RGB buffer for each neutral widget.
        widget._backdrop_photo.copy_replace(source_photo,from_coords=bounds,shrink=True)
    else:update_photo(widget._backdrop_photo,art)
    if kind=='TCombobox':
        arrow=art.crop((max(0,art.width-20),0,art.width,art.height))
        cy=arrow.height//2
        ImageDraw.Draw(arrow).line([(6,cy-2),(10,cy+2),(14,cy-2)],fill=colors['muted'],width=1)
        update_photo(widget._backdrop_arrow,arrow)
    # Unselected entry text must not receive the native white field fill.
    from window_art import PREFERENCES
    appearance=(tuple(colors.items()),tuple(PREFERENCES.items()))
    if getattr(widget,'_backdrop_appearance',None)==appearance:return True
    widget._backdrop_appearance=appearance
    sample='#%02x%02x%02x'%image.resize((1,1)).convert('RGB').getpixel((0,0))
    theme.configure(widget._backdrop_style,background=sample,fieldbackground=sample,
                    foreground=colors['ink'],borderwidth=0,lightcolor=sample,darkcolor=sample,
                    arrowcolor=colors['muted'],insertcolor=colors['ink'])
    if kind=='TCombobox':
        theme.map(widget._backdrop_style,fieldbackground=[('readonly',sample)],
                  selectbackground=[('readonly',sample)],selectforeground=[('readonly',colors['ink'])])
    elif kind=='TScrollbar':
        theme.configure(widget._backdrop_style,background=colors['accent'],bordercolor=colors['accent'],
                        lightcolor=colors['accent'],darkcolor=colors['accent'],width=7,arrowsize=7)
    return True


def update_photo(photo,image):
    rgb=image if image.mode=='RGB' else image.convert('RGB')
    header=f'P6\n{rgb.width} {rgb.height}\n255\n'.encode('ascii')
    photo.configure(data=header+rgb.tobytes(),format='PPM')


def paint_native_button(widget,image):
    """Keep native command/focus bindings while using the common button skin."""
    if widget.cget('image') and not getattr(widget,'_backdrop_button',False):return
    manage_images(widget)
    from glass_button import button_bitmap
    if not getattr(widget,'_backdrop_button',False):
        # Once an image is assigned Tk interprets width/height as pixels.
        width,height=widget.winfo_reqwidth(),widget.winfo_reqheight()
        widget._backdrop_button=True
        widget.configure(width=width,height=height,padx=0,pady=0,compound='center',highlightthickness=0)
    art=button_bitmap(image,focus=widget.focus_get() is widget,dark=palette(widget)['dark'])
    widget._backdrop_photo=ImageTk.PhotoImage(art,master=widget)
    widget.configure(image=widget._backdrop_photo)


def paint_native_label(widget,image):
    if widget.cget('image') and not getattr(widget,'_backdrop_label',False):return
    manage_images(widget)
    if not getattr(widget,'_backdrop_label',False):
        # Native Label width changes from character units to pixels when an image
        # is assigned. Preserve the measured size (especially usage app names).
        widget.configure(width=widget.winfo_reqwidth(),height=widget.winfo_reqheight())
    widget._backdrop_label=True
    widget._backdrop_photo=ImageTk.PhotoImage(image,master=widget)
    widget.configure(image=widget._backdrop_photo,compound='center',bd=0,highlightthickness=0,
                     padx=0,pady=0)


def paint_children(window,image,decorations,source_photo=None):
    """Apply exact crops; keep decorative children invisible to app refresh code."""
    origin=(window.winfo_rootx(),window.winfo_rooty())
    def visit(widget,clip):
        if (getattr(widget,'_art_decoration',False) or getattr(widget,'_art_hidden',False)
                or isinstance(widget,tk.Toplevel)):return
        if not widget.winfo_ismapped() or min(widget.winfo_width(),widget.winfo_height())<3:return
        x=widget.winfo_rootx()-origin[0];y=widget.winfo_rooty()-origin[1]
        bounds=(x,y,x+widget.winfo_width(),y+widget.winfo_height())
        visible=(max(clip[0],bounds[0]),max(clip[1],bounds[1]),min(clip[2],bounds[2]),min(clip[3],bounds[3]))
        if visible[2]<=visible[0] or visible[3]<=visible[1]:return
        if isinstance(widget,tk.Canvas):
            fonts=getattr(widget,'_backdrop_bold_fonts',{})
            widget._backdrop_bold_fonts=fonts
            for item in widget.find_all():
                if widget.type(item)!='text':continue
                original=widget.itemcget(item,'font')
                if original not in fonts:
                    actual=tkfont.Font(root=widget,font=original).actual()
                    fonts[original]=None if actual['weight']=='bold' else (actual['family'],actual['size'],'bold')
                if fonts[original]:widget.itemconfigure(item,font=fonts[original])
        unchanged=(getattr(widget,'_backdrop_source',None) is image
                   and getattr(widget,'_backdrop_bounds',None)==bounds)
        # A changed label need not repaint every sibling. Canvas scrolling only
        # moves the existing background item; its pixels stay screen-relative.
        if unchanged:
            if isinstance(widget,tk.Canvas) and getattr(widget,'_backdrop_canvas',False):
                widget.coords('window-backdrop',widget.canvasx(0),widget.canvasy(0))
            for child in widget.winfo_children():visit(child,visible)
            return
        widget._backdrop_source=image;widget._backdrop_bounds=bounds
        crop=lambda unused=None:image.crop(bounds)
        if hasattr(widget,'set_backdrop'):
            widget.set_backdrop(crop(widget));return
        if isinstance(widget,ttk.Widget):
            paint_ttk(widget,crop(widget),source_photo,bounds)
            if isinstance(widget,ttk.Treeview):translucent_text(widget)
        elif isinstance(widget,(tk.Frame,tk.LabelFrame)):
            key=str(widget);label=decorations.get(key)
            if label is None or not label.winfo_exists():
                if not getattr(widget,'_art_children_filtered',False):
                    original=widget.winfo_children
                    widget.winfo_children=lambda original=original:[child for child in original() if not getattr(child,'_art_decoration',False)]
                    widget._art_children_filtered=True
                label=tk.Label(widget,bd=0,highlightthickness=0)
                label._art_decoration=True
                manage_images(label)
                label.place(x=0,y=0,relwidth=1,relheight=1,bordermode='outside');label.lower()
                decorations[key]=label
            label._art_photo=ImageTk.PhotoImage(crop(widget),master=widget)
            label.configure(image=label._art_photo)
        elif isinstance(widget,tk.Label):paint_native_label(widget,crop(widget))
        elif isinstance(widget,tk.Button):paint_native_button(widget,crop(widget))
        elif isinstance(widget,(tk.Text,tk.Entry,tk.Spinbox,tk.Listbox,ttk.Treeview)):translucent_text(widget)
        elif isinstance(widget,tk.Canvas):
            manage_images(widget)
            if not getattr(widget,'_backdrop_canvas',False):
                original_bbox=widget.bbox
                def content_bbox(*args,original=original_bbox,canvas=widget):
                    if args==('all',):
                        items=[item for item in canvas.find_all() if 'window-backdrop' not in canvas.gettags(item)]
                        return original(*items) if items else None
                    return original(*args)
                widget.bbox=content_bbox;widget._backdrop_canvas=True
                positions={}
                for axis in ('x','y'):
                    previous=widget.cget(axis+'scrollcommand')
                    def scroll_changed(first,last,canvas=widget,old=previous,key=axis,seen=positions):
                        if old:canvas.tk.call(*canvas.tk.splitlist(old),first,last)
                        if seen.get(key)==(first,last):return
                        seen[key]=(first,last)
                        backdrop=getattr(canvas.winfo_toplevel(),'_art_backdrop',None)
                        if backdrop:backdrop.schedule()
                    widget.configure(**{axis+'scrollcommand':scroll_changed})
            widget._backdrop_photo=ImageTk.PhotoImage(crop(widget),master=widget)
            widget.delete('window-backdrop')
            widget.create_image(widget.canvasx(0),widget.canvasy(0),anchor='nw',
                                image=widget._backdrop_photo,tags='window-backdrop')
            widget.tag_lower('window-backdrop')
        for child in widget.winfo_children():visit(child,visible)
    clip=(0,0,window.winfo_width(),window.winfo_height())
    for child in window.winfo_children():visit(child,clip)
    for key,label in list(decorations.items()):
        if not label.winfo_exists():decorations.pop(key,None)
