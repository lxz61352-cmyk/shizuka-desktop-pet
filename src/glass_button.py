"""Native keyboard-accessible buttons with backdrop-matched frosted fills."""
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image,ImageDraw,ImageTk
from ui_theme import FONT,palette


def button_bitmap(image,primary=False,hover=False,focus=False,dark=False):
    art=image.convert('RGB');width,height=art.size
    if min(width,height)<4:return art
    tint=('#dceaf6' if primary else '#687f9c') if dark else '#f7fbff'
    opacity=(.91 if primary else .46 if hover else .25) if dark else (.72 if primary else .26 if hover else .06)
    layer=Image.blend(art,Image.new('RGB',art.size,tint),opacity)
    mask=Image.new('L',art.size,0)
    ImageDraw.Draw(mask).rounded_rectangle((1,1,width-2,height-2),radius=5,fill=255)
    art.paste(layer,(0,0),mask)
    ImageDraw.Draw(art).rounded_rectangle((1,1,width-2,height-2),radius=5,
                                         outline=('#79d8fa' if focus else '#a9c9de' if primary else '#61778f') if dark
                                         else '#527da9' if focus or primary else '#92abc7',width=1)
    return art


class GlassButton(tk.Button):
    def __init__(self,parent,text,command,primary=False,**kwargs):
        self.primary=primary;self.hover=False;self.art=None;self.pending=None
        self._glass_button=True
        colors=palette(parent)
        font=tkfont.Font(root=parent,family=FONT[0],size=10)
        width=font.measure(text)+30;height=font.metrics('linespace')+16
        ink=colors['primary_ink'] if primary else colors['ink']
        super().__init__(parent,text=text,command=command,font=font,fg=ink,bg=colors['bg'],
                         activeforeground=ink,activebackground=colors['bg'],bd=0,relief='flat',
                         padx=0,pady=0,highlightthickness=0,cursor='hand2',compound='center',takefocus=True,**kwargs)
        self.nominal=(width,height)
        self._photo=ImageTk.PhotoImage(Image.new('RGB',self.nominal,colors['bg']),master=self)
        super().configure(image=self._photo,width=width,height=height)
        self.bind('<Configure>',self.queue,add='+');self.bind('<Map>',self.queue,add='+')
        self.bind('<Enter>',lambda e=None:self.enter(True),add='+');self.bind('<Leave>',lambda e=None:self.enter(False),add='+')
        self.bind('<FocusIn>',self.queue,add='+');self.bind('<FocusOut>',self.queue,add='+')
        self.bind('<Return>',lambda e=None:self.invoke())
        self.bind('<Destroy>',self.destroy_timer,add='+')
        self.winfo_toplevel().bind('<<SurfaceChanged>>',self.queue,add='+')

    def enter(self,active):self.hover=active;self.queue()

    def queue(self,event=None):
        if not self.winfo_exists():return
        if self.pending is None:self.pending=self.after_idle(self.draw)

    def set_backdrop(self,image):self.art=image;self.queue()

    def draw(self):
        self.pending=None
        if not self.winfo_exists():return
        width,height=self.winfo_width(),self.winfo_height()
        if width<2 or height<2:width,height=self.nominal
        top=self.winfo_toplevel();source=getattr(top,'_surface_image',None)
        if source is not None:
            x=self.winfo_rootx()-top.winfo_rootx();y=self.winfo_rooty()-top.winfo_rooty()
            art=source.crop((x,y,x+width,y+height))
        elif self.art is not None:art=self.art.resize((width,height))
        else:art=Image.new('RGB',(width,height),palette(self)['bg'])
        art=button_bitmap(art,self.primary,self.hover,self.focus_get() is self,dark=palette(self)['dark'])
        self._photo=ImageTk.PhotoImage(art,master=self)
        super().configure(image=self._photo)

    def destroy_timer(self,event):
        if event.widget is self and self.pending:
            self.after_cancel(self.pending);self.pending=None
