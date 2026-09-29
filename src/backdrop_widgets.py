"""Paint each native widget from the same window image, including ttk padding.

An image *element* covers a ttk widget's complete rectangle. A child Label does
not: ttk clips children to its padded content area, leaving opaque gutters.
"""
import io
from itertools import count
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
from ui_theme import palette

_elements=count()


def _replace(layout, names, element):
    result=[]
    for name, options in layout:
        options=dict(options)
        if 'children' in options:
            options['children']=_replace(options['children'],names,element)
        result.append((element if name in names else name,options))
    return result


def paint_ttk(widget,image):
    kind=widget.winfo_class()
    colors=palette(widget)
    targets={
        'TFrame':{'Frame.border'}, 'TLabelframe':{'Labelframe.border'},
        'TLabel':{'Label.border'}, 'TEntry':{'Entry.field'},
        'TCombobox':{'Combobox.field'}, 'TButton':{'Button.border'},
        'TScrollbar':{'Vertical.Scrollbar.trough','Horizontal.Scrollbar.trough'},
        'TCheckbutton':{'Checkbutton.padding'},
        'TRadiobutton':{'Radiobutton.padding'},
    }
    if kind not in targets:return False
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
    if kind in ('TEntry','TCombobox'):
        # The field has only a fine outline; its interior is the actual card.
        ImageDraw.Draw(art).rounded_rectangle((0,0,art.width-1,art.height-1),radius=5,outline=colors['line'])
    elif kind=='TButton':
        from glass_button import button_bitmap
        art=button_bitmap(art,hover=widget.instate(('active',)),focus=widget.instate(('focus',)),dark=colors['dark'])
    stream=io.BytesIO();art.save(stream,format='PNG',compress_level=1)
    widget._backdrop_photo.configure(data=stream.getvalue(),format='png')
    if kind=='TCombobox':
        arrow=art.crop((max(0,art.width-20),0,art.width,art.height))
        cy=arrow.height//2
        ImageDraw.Draw(arrow).line([(6,cy-2),(10,cy+2),(14,cy-2)],fill=colors['muted'],width=1)
        stream=io.BytesIO();arrow.save(stream,format='PNG')
        widget._backdrop_arrow.configure(data=stream.getvalue(),format='png')
    # Unselected entry text must not receive the native white field fill.
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


def paint_native_button(widget,image):
    """Keep native command/focus bindings while using the common button skin."""
    if widget.cget('image') and not getattr(widget,'_backdrop_button',False):return
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
    if not getattr(widget,'_backdrop_label',False):
        # Native Label width changes from character units to pixels when an image
        # is assigned. Preserve the measured size (especially usage app names).
        widget.configure(width=widget.winfo_reqwidth(),height=widget.winfo_reqheight())
    widget._backdrop_label=True
    widget._backdrop_photo=ImageTk.PhotoImage(image,master=widget)
    widget.configure(image=widget._backdrop_photo,compound='center',bd=0,highlightthickness=0,
                     padx=0,pady=0)


def paint_children(window,image,decorations):
    """Apply exact crops; keep decorative children invisible to app refresh code."""
    def crop(widget):
        x=widget.winfo_rootx()-window.winfo_rootx();y=widget.winfo_rooty()-window.winfo_rooty()
        return image.crop((x,y,x+max(1,widget.winfo_width()),y+max(1,widget.winfo_height())))
    def visit(widget):
        if getattr(widget,'_art_decoration',False) or isinstance(widget,tk.Toplevel):return
        if not widget.winfo_ismapped() or min(widget.winfo_width(),widget.winfo_height())<3:return
        if hasattr(widget,'set_backdrop'):
            widget.set_backdrop(crop(widget));return
        if isinstance(widget,ttk.Widget):
            paint_ttk(widget,crop(widget))
        elif isinstance(widget,(tk.Frame,tk.LabelFrame)):
            key=str(widget);label=decorations.get(key)
            if label is None or not label.winfo_exists():
                if not getattr(widget,'_art_children_filtered',False):
                    original=widget.winfo_children
                    widget.winfo_children=lambda original=original:[child for child in original() if not getattr(child,'_art_decoration',False)]
                    widget._art_children_filtered=True
                label=tk.Label(widget,bd=0,highlightthickness=0)
                label._art_decoration=True
                label.place(x=0,y=0,relwidth=1,relheight=1,bordermode='outside');label.lower()
                decorations[key]=label
            label._art_photo=ImageTk.PhotoImage(crop(widget),master=widget)
            label.configure(image=label._art_photo)
        elif isinstance(widget,tk.Label):paint_native_label(widget,crop(widget))
        elif isinstance(widget,tk.Button):paint_native_button(widget,crop(widget))
        elif isinstance(widget,tk.Canvas):
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
        for child in widget.winfo_children():visit(child)
    for child in window.winfo_children():visit(child)
    for key,label in list(decorations.items()):
        if not label.winfo_exists():decorations.pop(key,None)
