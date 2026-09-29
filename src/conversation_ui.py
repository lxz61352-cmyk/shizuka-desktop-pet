"""Selectable conversation history and a multiline, lightweight composer."""
import os
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from ui_theme import INK,MUTED,ACCENT,apply,copy_bindings,copy_text,page_header
import layered_window

# 新的输入框素材：整张边框图 + 发送键（常态/按下带阴影）
CHAT_BOX_IMG=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"assets","chat_box.png")
CHAT_SEND_IMG=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"assets","chat_send.png")
CHAT_SEND_PRESS_IMG=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"assets","chat_send_press.png")
CHAT_BOX_W=460          # 输入框显示宽度（图按比例缩放）
CHAT_INK='#1a3f8f'      # 输入文字的深蓝色
CHAT_SEND_RATIO=0.24     # 发送键宽度 = 输入框宽度的 24%
CHAT_SEND_H_RATIO=0.2928 # 发送键高/宽（按浅色那张定死，两态同尺寸才不会错位）
CHAT_SEND_RIGHT=0.885    # 发送键右边缘（对齐文字区右边）
CHAT_SEND_MID_Y=0.70     # 发送键垂直中心（素材下半条带）
CHAT_TEXT_FILL='#ffffff'  # 文字区的底色（和素材内框一致）
CHAT_GLOW_CUT=10          # 低于这个 alpha 的柔光抹掉（只清掉几乎看不见的噪声，别削掉花纹里的柔光）
CHAT_TOOL_W=56            # 「截图 / 文件」按钮宽度
CHAT_TOOL_GAP=8           # 按钮之间的间距
CHAT_ATTACH_MAX=6         # 一次最多带几个附件或PDF页面
CHAT_FILE_MAX=6000        # 文本附件最多读多少字
CHAT_IMG_EXT=('.png','.jpg','.jpeg','.gif','.bmp','.webp','.tif','.tiff')
_chat_images=None
_chat_visible=None

def chat_images():
    """(边框, 发送键, 发送键按下) 三张图，按 CHAT_BOX_W 缩放后缓存。
    两张发送键统一缩到同一尺寸——素材本身宽高比不同，只按宽度缩会一高一矮。"""
    global _chat_images
    if _chat_images is None:
        from PIL import Image
        lut=[0]*CHAT_GLOW_CUT+list(range(CHAT_GLOW_CUT,256))
        def cut(img):
            img.putalpha(img.getchannel("A").point(lut))
            return img
        def resize(img,size):
            # 预乘 alpha 再缩放：透明像素的 RGB 常常是黑的，直接缩会把黑边渗进边缘（看着像锯齿）
            return img.convert("RGBa").resize(size,Image.Resampling.LANCZOS).convert("RGBA")
        box=Image.open(CHAT_BOX_IMG).convert("RGBA")
        scale=CHAT_BOX_W/float(box.width)
        box=cut(resize(box,(CHAT_BOX_W,max(1,round(box.height*scale)))))
        width=round(CHAT_BOX_W*CHAT_SEND_RATIO)
        height=max(1,round(width*CHAT_SEND_H_RATIO))
        def button(path):
            img=Image.open(path).convert("RGBA")
            bbox=img.getchannel("A").getbbox()
            if bbox:img=img.crop(bbox)
            return cut(resize(img,(width,height)))
        _chat_images=(box,button(CHAT_SEND_IMG),button(CHAT_SEND_PRESS_IMG))
    return _chat_images

def chat_text_rect(width,height,box=None):
    """文字区：素材里那个内框按比例换算成显示坐标（0.0853~0.8966 宽、0.2809~0.5975 高）。
    自己重新出图时不用改代码——按同一比例画内框即可。"""
    return (round(width*0.0853),round(height*0.2809),round(width*0.8966),round(height*0.5975))

def chat_visible_rect():
    """显示图里"看得见的那块"（alpha>=128）。素材上下都留着一圈透明柔光，
    窗口比可见内容大，贴桌宠时要按这个矩形算，不然框底会凭空多出几十像素。"""
    global _chat_visible
    if _chat_visible is None:
        box=chat_images()[0]
        _chat_visible=(box.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
                       or (0,0,box.width,box.height))
    return _chat_visible

def _pil_font(size=15):
    from PIL import ImageFont
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_tool_button(img, x, y, w, h, label):
    """在外框图上画一个小按钮（浅蓝底 + 深蓝字），和发送键同一行。"""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=8,
                        fill=(234, 243, 255, 255), outline=(127, 178, 240, 255), width=1)
    font = _pil_font()
    d.text((x + w / 2, y + h / 2), label, font=font, fill=(26, 63, 143, 255), anchor="mm")


def _thumb(img, w, h):
    """按比例缩到 w×h 里，居中放在白底上（截图这种宽图不会被拉变形）。"""
    from PIL import Image
    box = Image.new("RGB", (w, h), (255, 255, 255))
    if img.width <= 0 or img.height <= 0:
        return box
    s = min(w / img.width, h / img.height)
    small = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.Resampling.LANCZOS)
    box.paste(small, ((w - small.width) // 2, (h - small.height) // 2))
    return box


def _draw_attach_previews(img, right, y, height, atts):
    """在按钮左边画附件预览（图片=缩略图，文件=名字条），返回 [(index, x1,y1,x2,y2), ...]。"""
    from PIL import ImageDraw
    font = _pil_font(13)
    rects = []
    x = right
    for index in list(range(len(atts)))[-CHAT_ATTACH_MAX:][::-1]:
        att = atts[index]
        if att.get("kind") == "image" and att.get("image") is not None:
            w = int(height * 1.4)
            x1 = x - w
            box = _thumb(att["image"], w - 2, height - 2)
            img.paste(box, (x1 + 1, y + 1))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((x1, y, x1 + w - 1, y + height - 1), radius=6,
                                outline=(127, 178, 240, 255), width=1)
        else:
            label = att.get("name", "文件")
            if len(label) > 6:
                label = label[:6] + "…"
            d = ImageDraw.Draw(img)
            w = int(d.textlength(label, font=font)) + 20
            x1 = x - w
            d.rounded_rectangle((x1, y, x1 + w - 1, y + height - 1), radius=8,
                                fill=(255, 255, 255, 240), outline=(150, 190, 240, 255), width=1)
            d.text((x1 + 8, y + height / 2), label, font=font, fill=(26, 63, 143, 255), anchor="lm")
        rects.append((index, x1, y, x1 + w, y + height))
        x = x1 - 6
        if x < 8:
            break
    return rects


def _read_text_file(path):
    """按常见编码试读文本文件；二进制/读不出来返回 ''。"""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(400000)
    except Exception:
        return ""
    if b"\x00" in raw[:2000]:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def image_data_url(img):
    """PIL 图 → data:image/png;base64,...（给视觉模型用）。"""
    import base64, io as _io
    buf=_io.BytesIO();img.save(buf,format="PNG")
    return "data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode("ascii")


class Composer(ScrolledText):
    def get(self,*args):return super().get(*(args or ('1.0','end-1c')))

class ConversationUIMixin:
    def open_chat_input(self,prefill='',interrupt=True):
        from desktop_surface import surface,button,SURFACE
        from ui_theme import LIGHT_INK as INK,LIGHT_MUTED as MUTED
        from PIL import ImageTk
        self._cancel_chat_click();self._wake_pet()
        if self._chat_win is not None:
            self._chat_win.lift();self._refocus_chat_entry();return
        if interrupt:self._cancel_reply()
        self.close_popup()
        width=min(460,max(320,self.root.winfo_screenwidth()-40))
        win,canvas,resize=surface(self.root,width,280,'发消息给静香')
        entry=Composer(win,height=4,width=38,wrap='word',bg=SURFACE,fg=INK,
                       insertbackground=INK,relief='flat',bd=0,padx=12,pady=10,
                       highlightthickness=0,
                       font=('Microsoft YaHei UI',11),spacing3=4)
        entry.place(x=44,y=72,width=width-88,height=106)
        entry.frame.configure(bg=SURFACE)
        entry.vbar.configure(bg=SURFACE,troughcolor=SURFACE,bd=0,highlightthickness=0,width=9)
        entry.insert('1.0',prefill or getattr(self,'_chat_text',''));copy_bindings(entry)
        atts=getattr(self,'_chat_attachment_draft',[]);self._chat_attachment_draft=atts
        previews=ttk.Frame(win)
        tools=ttk.Frame(win)
        actions=ttk.Frame(win)
        def close():
            self._chat_text=entry.get();self._save_chat_draft(self._chat_text);self.close_chat_win()
        def send(event=None):
            text=entry.get().strip();payload=list(atts)
            if not text and not payload:return 'break'
            if payload:
                try:self._remember_attachments(payload)
                except Exception:self._record_notice('这次附件未能存入最近材料；本轮仍会发送。','附件')
                text=(text or '请看看这些材料。')+'\n[附件：'+'；'.join(r.get('name','图片') for r in payload)+']'
            self._chat_text='';atts.clear();entry.delete('1.0','end');self.close_chat_win()
            self._last_chat_submission={'text':text,'attachments':payload}
            self._save_chat_draft('')
            self.on_chat_submit(text,attachments=payload)
            return 'break'
        def remove(index):
            if 0<=index<len(atts):del atts[index]
            refresh();self._refocus_chat_entry()
        def refresh():
            for child in previews.winfo_children():child.destroy()
            photos=[]
            for index,att in enumerate(atts[:2]):
                label=str(index+1)+'. '+att.get('name','图片')[:10]
                chip=tk.Button(previews,text=label,command=lambda:self.manage_attachments(atts,refresh),
                               bg=SURFACE,fg=INK,relief='flat',bd=0,font=('Microsoft YaHei UI',9),cursor='hand2')
                if att.get('image') is not None:
                    photo=ImageTk.PhotoImage(_thumb(att['image'],34,26),master=win);photos.append(photo)
                    chip.configure(image=photo,compound='left',padx=4,pady=1)
                chip.pack(side='left',padx=(0,6))
            if len(atts)>2:
                button(previews,'共'+str(len(atts))+'份',lambda:self.manage_attachments(atts,refresh)).pack(side='left')
            self._chat_photos=photos
            height=360 if atts else 320
            resize(height)
            if atts:previews.place(x=44,y=184,width=width-88,height=34)
            else:previews.place_forget()
            tools.place(x=40,y=height-77,width=width-80,height=36)
            actions.place(x=44,y=height-112,width=width-88,height=28)
            hint.place_configure(y=height-35)
            self.update_chat_pos()
        button(tools,'文件',lambda:self.attach_file(atts,refresh)).pack(side='left',padx=(0,6))
        button(tools,'截图',lambda:self.attach_screenshot(atts,refresh)).pack(side='left')
        button(tools,'材料',lambda:self.manage_attachments(atts,refresh)).pack(side='left',padx=4)
        button(tools,'粘贴图',lambda:self.paste_attachment(atts,refresh)).pack(side='left')
        button(tools,'发送',send,primary=True).pack(side='right',padx=(10,4))
        task=tk.StringVar(value='选择材料操作…')
        choose=ttk.Combobox(actions,textvariable=task,state='readonly',values=('看看这些材料','讲解题目','提取文字','翻译内容','总结要点','比较所选图片'),width=18)
        choose.pack(side='left');ttk.Label(actions,text='可继续补充问题',font=('Microsoft YaHei UI',8)).pack(side='left',padx=6)
        def task_selected(event=None):
            existing=entry.get().strip()
            entry.insert('end',('\n' if existing else '')+task.get());self._refocus_chat_entry()
        choose.bind('<<ComboboxSelected>>',task_selected)
        hint=ttk.Label(win,text='Ctrl+V 可粘贴图片 · Shift+Enter 换行',foreground=MUTED,font=('Microsoft YaHei UI',8))
        hint.place(x=48,y=245)
        close_btn=button(win,'×',close);close_btn.place(x=width-63,y=26,width=27,height=27)
        entry.bind('<Return>',send)
        entry.bind('<Control-v>',lambda e:self.paste_attachment(atts,refresh))
        entry.bind('<Control-V>',lambda e:self.paste_attachment(atts,refresh))
        draft_timer=[None]
        def save_draft(event=None):
            if draft_timer[0] is not None:win.after_cancel(draft_timer[0])
            draft_timer[0]=win.after(500,lambda:self._save_chat_draft(entry.get()))
        entry.bind('<KeyRelease>',save_draft,add='+')
        win.bind('<Destroy>',lambda e:win.after_cancel(draft_timer[0]) if e.widget is win and draft_timer[0] is not None else None,add='+')
        entry.bind('<Shift-Return>',lambda e:(entry.insert('insert','\n'),'break')[-1])
        win.bind('<Escape>',lambda e:close())
        self._chat_win=win;self._chat_entry=entry;self._chat_canvas=canvas
        refresh();win.update_idletasks();self.update_chat_pos()
        win.deiconify();win.lift();entry.focus_force()
        for delay in (0,60,200):win.after(delay,self.update_chat_pos)
        win.after(120,lambda:self._poll_chat_outside(win))

    def _refocus_chat_entry(self):
        """选完附件/点了外框按钮之后，把键盘焦点还给输入框——不然就打不了字了。"""
        try:
            entry=getattr(self,"_chat_entry",None)
            if entry is not None and entry.winfo_exists():
                entry.focus_force()
        except Exception:
            pass

    def attach_screenshot(self,atts,on_change):
        """全屏遮罩里框选一块 → 作为待发送图片附件。Esc 取消。"""
        try:
            from PIL import ImageGrab
        except Exception:
            return
        if len(atts)>=CHAT_ATTACH_MAX:
            self.say("一次最多带 %d 个附件哦。" % CHAT_ATTACH_MAX);return
        self._chat_attach_busy=True          # 框选期间别让"点外面"把输入框关掉
        try:
            left=self.root.winfo_vrootx();top=self.root.winfo_vrooty()
            right=left+self.root.winfo_vrootwidth();bottom=top+self.root.winfo_vrootheight()
            overlay=tk.Toplevel(self.root);overlay.overrideredirect(True);overlay.attributes('-topmost',True)
            try:overlay.attributes('-alpha',0.28)
            except Exception:pass
            overlay.configure(bg='#0d1420')
            overlay.geometry("%dx%d+%d+%d" % (right-left,bottom-top,left,top))
            canvas=tk.Canvas(overlay,bg='#0d1420',highlightthickness=0,cursor='crosshair')
            canvas.pack(fill='both',expand=True)
            canvas.create_text((right-left)//2,46,text='拖拽框选要给她看的部分（Esc 取消）',
                               fill='#ffffff',font=('Microsoft YaHei UI',13))
            st={'x0':0,'y0':0,'rect':None,'done':False}
            def finish(bbox):
                if st['done']:return
                st['done']=True
                try:overlay.destroy()
                except Exception:pass
                if bbox is None:return
                try:img=ImageGrab.grab(bbox=bbox)
                except Exception:img=None
                if img is None or img.width<4 or img.height<4:return
                atts.append({'kind':'image','name':'截图','data_url':image_data_url(img),'image':img})
                on_change()
            def down(e):
                st['x0'],st['y0']=e.x,e.y
                st['rect']=canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='#4aa3ff',width=2)
            def move(e):
                if st['rect'] is not None:canvas.coords(st['rect'],st['x0'],st['y0'],e.x,e.y)
            def up(e):
                x0,x1=sorted((st['x0'],e.x));y0,y1=sorted((st['y0'],e.y))
                finish(None if (x1-x0<6 or y1-y0<6) else (left+x0,top+y0,left+x1,top+y1))
            canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up)
            overlay.bind('<Escape>',lambda e:finish(None))
            overlay.focus_force()
        except Exception:
            self.say("截图没打开，再试一次？")
        finally:
            self._chat_attach_busy=False
            self._refocus_chat_entry()

    def attach_file(self,atts,on_change):
        """选一个文件：图片当图片带，文本读进来当资料带。"""
        from tkinter import filedialog
        if len(atts)>=CHAT_ATTACH_MAX:
            self.say("一次最多带 %d 个附件哦。" % CHAT_ATTACH_MAX);return
        self._chat_attach_busy=True          # 选文件期间别让"点外面"把输入框关掉
        try:
            path=filedialog.askopenfilename(parent=self.pet,title="选一个文件给静香看",
                filetypes=[("图片","*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                           ("文本/代码","*.txt *.md *.py *.json *.csv *.log *.yaml *.yml *.ini *.bat *.ps1"),
                           ("所有文件","*.*")])
        except Exception:
            return
        if not path:return
        name=os.path.basename(path);ext=os.path.splitext(path)[1].lower()
        try:
            if ext in CHAT_IMG_EXT:
                try:
                    from PIL import Image
                    img=Image.open(path).convert("RGB")
                except Exception:
                    self.say("这张图我打不开呢。");return
                atts.append({'kind':'image','name':name,'data_url':image_data_url(img),'image':img})
                on_change();return
            text=_read_text_file(path)
            if not text.strip():
                self.say("这个格式我读不了（现在只认文本和图片）。");return
            atts.append({'kind':'text','name':name,'text':text[:CHAT_FILE_MAX]})
            on_change()
        finally:
            self._chat_attach_busy=False
            self._refocus_chat_entry()

    def show_chat_log(self,event=None,mode=None):
        from glass_button import GlassButton
        old=getattr(self,'_chatlog_win',None)
        if old is not None and old.winfo_exists():
            if mode:getattr(self,'_chatlog_mode').set(mode);self._chatlog_refresh()
            self._move_dialog(old,820,650);return
        win=self._chatlog_win=tk.Toplevel(self.root);win.title('静香 · 对话');win.minsize(620,460);self._place_dialog(win,820,650)
        win.attributes('-topmost',True)
        head=page_header(win,'对话记录');head.pack(fill='x')
        GlassButton(head,text='继续聊',command=self.open_chat_input,primary=True).pack(side='right')
        row=ttk.Frame(win,padding=(18,12));row.pack(fill='x',padx=14,pady=(0,10));row._glass_panel='controls'
        query=tk.StringVar();field=ttk.Entry(row,textvariable=query);field.pack(side='left',fill='x',expand=True)
        mode=self._chatlog_mode=tk.StringVar(value=mode or '对话');ttk.Combobox(row,textvariable=mode,values=('对话','通知','全部记录'),state='readonly',width=11).pack(side='left',padx=(8,0))
        from art_transcript import ArtTranscript
        body=ttk.Frame(win,padding=(8,4));body.pack(fill='both',expand=True,padx=14);body._glass_panel='content'
        box=ArtTranscript(body)
        box.on_feedback=self.show_reply_feedback
        box.on_context=lambda row:self.show_notice(row) if row.get('kind')=='notification' else self.show_chat_context(row)
        bar=ttk.Scrollbar(body,orient='vertical',command=box.yview,style='Pet.Vertical.TScrollbar')
        box.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');box.pack(fill='both',expand=True)
        self._chatlog_text=box
        def shuffle():
            art=getattr(win,'_art_backdrop',None)
            if art:art.shuffle()
        GlassButton(head,text='换张背景',command=shuffle).pack(side='right',padx=8)
        GlassButton(head,text='反馈记录',command=self.show_feedback).pack(side='right',padx=8)
        foot=ttk.Frame(win,padding=(22,12));foot.pack(fill='x')
        status=tk.StringVar();ttk.Label(foot,textvariable=status,style='Pet.Muted.TLabel').pack(side='left')
        GlassButton(foot,text='复制所选',command=lambda:copy_text(box)).pack(side='right')
        GlassButton(foot,text='复制全部',command=lambda:copy_text(box,True)).pack(side='right',padx=8)
        def refresh():
            if not win.winfo_exists():return
            with self._chat_lock:rows=list(self._chat_log)
            if mode.get()=='通知':rows=self._workflow().notices()
            elif mode.get()=='全部记录':rows=sorted(rows+self._workflow().notices(),key=lambda r:r.get('created',0))
            search=query.get().strip().casefold()
            if mode.get()=='对话':rows=[r for r in rows if r.get('role') in ('user','assistant') and r.get('kind')!='memory_summary']
            if search:rows=[r for r in rows if search in r.get('text','').casefold()]
            visible=rows[-500:]
            box.set_rows(visible)
            status.set(f'{len(rows)} 条记录'+(' · 显示最近500条' if len(rows)>500 else '')+' · 双击展开')
        self._chatlog_refresh=refresh
        GlassButton(row,text='查找 / 刷新',command=refresh).pack(side='left',padx=(8,0))
        field.bind('<Return>',lambda e:refresh());mode.trace_add('write',lambda *a:refresh())
        win.protocol('WM_DELETE_WINDOW',self._close_chat_log);win.bind('<Escape>',lambda e:self._close_chat_log())
        apply(win);refresh()
