"""Bound canvas item count to the viewport, keeping complete message data."""
import math
import time
import tkinter as tk
from tkinter import font as tkfont
from ui_theme import FONT,palette


class RowHeights:
    """Prefix heights and pixel-to-row lookup, with logarithmic corrections."""
    def __init__(self,heights):
        self.heights=list(heights);self.tree=[0,*self.heights]
        for index in range(1,len(self.tree)):
            parent=index+(index&-index)
            if parent<len(self.tree):self.tree[parent]+=self.tree[index]

    def prefix(self,count):
        total=0
        while count:total+=self.tree[count];count-=count&-count
        return total

    def set(self,index,height):
        delta=height-self.heights[index];self.heights[index]=height;index+=1
        while index<len(self.tree):self.tree[index]+=delta;index+=index&-index

    def index_at(self,y):
        index=0;bit=1<<(len(self.heights).bit_length()-1) if self.heights else 0
        while bit:
            other=index+bit
            if other<len(self.tree) and self.tree[other]<=y:y-=self.tree[other];index=other
            bit>>=1
        return min(index,len(self.heights)-1)


class VirtualTranscriptMixin:
    def _virtual_render(self):
        for name in ('_layout_job','_reflow_pending'):
            if getattr(self,name,None):self.after_cancel(getattr(self,name));setattr(self,name,None)
        anchor=None
        if self._virtual is not None and not self._follow_end:
            top=self.canvasy(0);index=self._virtual.index_at(max(0,top-24))
            anchor=(index,top-24-self._virtual.prefix(index))
        self.delete('text');self._row_items=[];self._virtual_records={}
        self._render_width=max(260,self.winfo_width());maximum=self._render_width-56
        font=tkfont.Font(root=self,font=FONT)
        line=font.metrics('linespace')+3;latin=font.measure('abcdefghijklm')/13;wide=font.measure('汉')
        cache=getattr(self,'_measured_heights',{});self._measured_heights=cache
        estimates={}
        def estimate(text):
            key=(self._render_width,text)
            if key in cache:return cache[key]
            if text not in estimates:
                lines=0
                for paragraph in text.split('\n'):
                    pixels=sum(wide if ord(char)>255 else latin*4 if char=='\t' else latin for char in paragraph)
                    lines+=max(1,math.ceil(pixels/max(1,maximum)))
                estimates[text]=max(23,lines*line)+79
            return estimates[text]
        self._virtual=RowHeights(estimate(row.get('text','')) for row in self.rows)
        self._virtual_ids={row['id']:index for index,row in enumerate(self.rows) if 'id' in row}
        self.configure(scrollregion=(0,0,self._render_width,24+self._virtual.prefix(len(self.rows))))
        if anchor is not None:
            index,offset=anchor;index=min(index,len(self.rows)-1)
            tk.Canvas.yview(self,'moveto',(24+self._virtual.prefix(index)+offset)/(24+self._virtual.prefix(len(self.rows))))
        self._virtual_present();self.paint()

    def _virtual_present(self):
        if self._virtual is None or getattr(self,'_virtual_layout',False):return
        self._virtual_layout=True
        try:
            heights=self._virtual;colors=palette(self);width=self._render_width
            top=self.canvasy(0);anchor=heights.index_at(max(0,top-24));offset=top-24-heights.prefix(anchor)
            follow=self._follow_end or tk.Canvas.yview(self)[1]>=.999
            focus=getattr(self,'_virtual_focus',None)
            for attempt in range(3):
                total=24+heights.prefix(len(self.rows));self.content_height=total
                self.configure(scrollregion=(0,0,width,total))
                if focus is not None:destination=max(0,24+heights.prefix(focus)-30)
                elif follow:destination=max(0,total-self.winfo_height())
                else:destination=max(0,24+heights.prefix(anchor)+min(offset,heights.heights[anchor]-1))
                tk.Canvas.yview(self,'moveto',destination/max(1,total))
                top=self.canvasy(0);end=top+self.winfo_height()+180
                start=heights.index_at(max(0,top-24-180));wanted=[]
                for index in range(start,len(self.rows)):
                    if 24+heights.prefix(index)>end and wanted:break
                    wanted.append(index)
                previous=self._virtual_records
                spare=[record for index,record in previous.items() if index not in wanted]
                current={};changed=False
                for index in wanted:
                    record=previous.get(index)
                    if record is None:
                        if spare:
                            record=spare.pop()
                            if self.select_item()==record['items'][2]:self.select_clear();self.selecting=None
                        else:
                            record={'items':(self.create_text(0,0,anchor='nw',font=(FONT[0],10,'bold'),tags='text'),
                                self.create_text(0,0,anchor='ne',font=(FONT[0],9,'bold'),tags='text'),
                                self.create_text(0,0,anchor='nw',font=FONT,tags=('text','message')),
                                self.create_line(0,0,0,0,width=1,tags='text')),'key':None}
                    row=self.rows[index];user=row.get('role')=='user'
                    label='你' if user else 'Shizuka' if row.get('role')=='assistant' else '记录'
                    if row.get('kind')=='notification':label=('已读 · ' if row.get('read') else '● 未读 · ')+row.get('source','通知')
                    text=row.get('text','');stamp=time.strftime('%m-%d %H:%M',time.localtime(row.get('created',0)))
                    key=(index,label,stamp,text,width,self.all_selected,tuple(colors.items()))
                    heading,date,item,rule=record['items']
                    if record['key']!=key:
                        self.itemconfigure(heading,text=label,fill=colors['accent'] if user else colors['ink'])
                        self.itemconfigure(date,text=stamp,fill=colors['muted'])
                        self.itemconfigure(item,text=text,width=width-56,fill=colors['accent'] if self.all_selected else colors['ink'])
                        self.itemconfigure(rule,fill=colors['line']);record['key']=key
                        bounds=self.bbox(item);height=max(23,bounds[3]-bounds[1] if bounds else 23)+79
                        if heights.heights[index]!=height:heights.set(index,height);changed=True
                        if len(self._measured_heights)>=2048:self._measured_heights.pop(next(iter(self._measured_heights)))
                        self._measured_heights[(width,text)]=height
                    current[index]=record
                for record in spare:
                    for item in record['items']:self.delete(item)
                self._virtual_records=current
                if not changed:break
            self.texts={};self.hit_rows=[]
            for index,record in current.items():
                y=24+heights.prefix(index);bottom=y+heights.heights[index]-24
                heading,date,item,rule=record['items']
                self.coords(heading,28,y);self.coords(date,width-28,y+2);self.coords(item,28,y+32)
                self.coords(rule,28,bottom,width-28,bottom)
                row=self.rows[index];self.texts[item]=row.get('text','');self.hit_rows.append((y,bottom,row))
            self._row_items=list(current.values());self._follow_end=False;self._virtual_focus=None
        finally:self._virtual_layout=False
