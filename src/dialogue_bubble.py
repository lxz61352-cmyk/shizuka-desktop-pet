"""Bounded, scrollable and selectable speech panel for short and long replies."""
import math,os,time,tkinter as tk
from tkinter import font as tkfont
from PIL import Image
from ui_theme import copy_bindings,copy_text
import layered_window

_ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BOX_IMG=os.path.join(_ROOT,"assets","bubble_box.png")
_MID_IMG=os.path.join(_ROOT,"assets","bubble_mid.png")

# 气泡外框：整张框在 BUBBLE_CUT 处剪成上下两片，中间用 bubble_mid 上下拉伸填满。
# 上中下三片按同一比例横向缩放，左右两条竖边框就自然对齐，接缝不会错位。
# 外框走「分层窗口」贴原图（真逐像素 alpha），内容（文字+按钮）是另一个不透明小窗，
# 盖在内框区域上——色键只能全透/全不透，会把柔光糊掉，所以不用色键。
BUBBLE_W=460             # 显示宽度（素材按这个宽度等比缩放）
BUBBLE_CUT=394           # 裁剪线（原图上那条黑线）：上半片 0..393
MID_TOP,MID_BOTTOM=395,436
MID_X=(103,1544)         # 中段填充条的左右范围，竖边框就在这两条线上
CONTENT_TOP,CONTENT_BOTTOM=203,773   # 内框以内、可以放文字的范围
PANEL_BG='#E5EFFC'        # 内容窗/Canvas 底色 = 素材内框色，铺在花纹上等于看不见
TEXT_BG='#FFFFFF'        # 文字圆角框的底色（和输入框一个风格）
BOX_RADIUS=9             # 文字框圆角
BOX_PAD_X=8              # 文字框到内容窗边的距离（大一点，文字框整体更小）
BOX_PAD_TOP=16           # 白框上边距（内缩 6 + 16 = 22，躲开探进来的星星/音符）
BOX_PAD_BOTTOM=8         # 白框底到按钮条
BOX_INSET=8              # 文字离圆角框边的距离（>= 圆角半径，圆角才不会被文字框盖住）
BOX_TOP_PAD=0            # 文字控件内部不再额外留白
TEXT_FG='#22406e'
LINK_FG='#3b6ea5'
LINK_OFF='#9fb4cc'
BTN_FONT=('Microsoft YaHei UI',9)
BAR_H=20                 # 底部按钮条高度
INSET_SIDE=6           # 内容窗离内框的边距（面板是透明的，只为容纳内容）
INSET_TOP=6
INSET_BOTTOM=6
                         # 但拖动/改尺寸时两个窗有一两帧不同步也不会露到边框外面
TEXT_PAD_BOTTOM=6        # 文字框底到按钮条之间留白
BAR_RIGHT_GAP=36         # 按钮条右端再往里收一点：贴到内框右边会压到右下角的缎带花纹
_metrics=None
_slice_cache=None


def _resize(img,size):
    """预乘 alpha 再缩放：透明像素的 RGB 常常是黑的，直接缩会把黑/杂色渗进边缘。"""
    return img.convert("RGBa").resize(size,Image.Resampling.LANCZOS).convert("RGBA")


def _debug(line):
    """气泡的窗口/位图尺寸对不上时用来查问题：只留最近 64KB。"""
    try:
        import pet as engine
        path=os.path.join(engine.DATA_DIR,"bubble.log")
        if os.path.exists(path) and os.path.getsize(path)>65536:
            os.remove(path)
        with open(path,"a",encoding="utf-8") as stream:
            stream.write(time.strftime("%H:%M:%S ")+line+"\n")
    except Exception:
        pass


def _round_points(x1,y1,x2,y2,r,steps=8):
    """圆角矩形的顶点：必须把圆弧采样成多点，create_polygon 的 smooth 只切 1~2px。"""
    pts=[]
    r=max(0,min(r,(x2-x1)/2,(y2-y1)/2))
    for cx,cy,start in ((x2-r,y1+r,-90),(x2-r,y2-r,0),(x1+r,y2-r,90),(x1+r,y1+r,180)):
        for i in range(steps+1):
            ang=math.radians(start+90.0*i/steps)
            pts.extend((cx+r*math.cos(ang),cy+r*math.sin(ang)))
    return pts


def _layout_metrics():
    global _metrics
    if _metrics is None:
        box=Image.open(_BOX_IMG)
        s=BUBBLE_W/float(box.width)
        left=int(MID_X[0]*s)          # 向下取整：素材里这条竖边框落在半像素上，取整会整体偏右
        right=round(MID_X[1]*s)
        _metrics={'scale':s,'top_h':round(BUBBLE_CUT*s),
                  'natural_mid':round((MID_BOTTOM-MID_TOP)*s),
                  'bot_h':round((box.height-MID_BOTTOM)*s),
                  'left':left,'right':right,'mid_w':max(1,right-left),
                  'content_top':round(CONTENT_TOP*s),
                  'content_bottom_off':round((CONTENT_BOTTOM-MID_BOTTOM)*s),
                  'content_w':max(1,right-left)}
    return _metrics


def _source_slices():
    """上片/下片/中段样本，都按显示宽度缩放好，之后只做拉伸。"""
    global _slice_cache
    if _slice_cache is None:
        M=_layout_metrics()
        box=Image.open(_BOX_IMG).convert("RGBA")
        top=_resize(box.crop((0,0,box.width,BUBBLE_CUT)),(BUBBLE_W,M['top_h']))
        bot=_resize(box.crop((0,MID_BOTTOM,box.width,box.height)),(BUBBLE_W,M['bot_h']))
        mid=Image.open(_MID_IMG).convert("RGBA")
        _slice_cache=(top,bot,mid)
    return _slice_cache


def bubble_frame(extra=0):
    """拼出整张外框。extra = 中段比原始比例额外拉长的高度（像素）。
    做法：在**素材尺度**上把中段（MID_TOP..MID_BOTTOM）上下拉伸，最后整张缩到显示宽度。
    只经过一次重采样，左右竖边框在接缝处严丝合缝；分开贴中段会有半像素偏移（看着就是接缝没对齐）。"""
    M=_layout_metrics();s=M['scale']
    src=Image.open(_BOX_IMG).convert("RGBA")
    grow=int(round(max(0,extra)/s))                       # 显示高度换算回素材像素
    band=src.crop((0,MID_TOP,src.width,MID_BOTTOM))
    if grow>0:
        band=_resize(band,(src.width,band.height+grow))   # 只上下拉伸
    out=Image.new("RGBA",(src.width,src.height+grow),(0,0,0,0))
    out.paste(src.crop((0,0,src.width,MID_TOP)),(0,0))
    out.paste(band,(0,MID_TOP))
    out.paste(src.crop((0,MID_BOTTOM,src.width,src.height)),(0,MID_TOP+band.height))
    # 目标高度按布局参数算死，保证和内容窗的排版基准一致（差 1px 会让内框和内容错开）
    target=M['top_h']+M['natural_mid']+max(0,int(extra))+M['bot_h']
    return _resize(out,(BUBBLE_W,target))


def make_bubble(parent,**unused):
    M=_layout_metrics()
    frame_win=tk.Toplevel(parent);frame_win.withdraw();frame_win.overrideredirect(True)
    frame_win.attributes('-topmost',True)
    win=tk.Toplevel(parent);win.withdraw();win.overrideredirect(True);win.attributes('-topmost',True)
    content_w=M['content_w']-2*INSET_SIDE
    content_h=(M['top_h']+M['natural_mid']+M['content_bottom_off']-M['content_top']
               -INSET_TOP-INSET_BOTTOM)
    # 内容窗和 Canvas 都用素材内框的底色，不要用色键透明：
    # 色键是近黑，Canvas 上文字的抗锯齿会朝它混合 → 字边一圈黑，看着就是重影/阴影。
    # 内容窗比内框再缩一圈（四边各自留够，躲开探进来的花纹），四周都在素材的纯色区域里，同色等于看不见。
    win.configure(bg=PANEL_BG)
    try:
        # 面板色 = 内框色，把它设成色键：面板整块透出外框原图，不再有"浅蓝方框"；
        # 文字抗锯齿是朝这个浅色混合的，也不会像近黑色键那样糊出黑边。
        win.attributes('-transparentcolor',PANEL_BG)
    except Exception:
        pass
    canvas=tk.Canvas(win,width=content_w,height=content_h,bg=PANEL_BG,highlightthickness=0,bd=0)
    canvas.pack(fill='both',expand=True)
    font=tkfont.Font(family='Microsoft YaHei UI',size=12)
    max_lines=max(4,min(14,(parent.winfo_screenheight()//2-70)//max(1,font.metrics('linespace')+7)))
    box=tk.Text(canvas,width=38,height=2,wrap='word',bg=TEXT_BG,fg=TEXT_FG,font=font,
                relief='flat',bd=0,highlightthickness=0,selectbackground='#c7dcf5',selectforeground=TEXT_FG,
                spacing1=2,spacing3=5,state='disabled',cursor='arrow',exportselection=False)
    copy_bindings(box)
    box_item=canvas.create_polygon(_round_points(0,0,10,10,BOX_RADIUS),fill=TEXT_BG,outline='')
    text_item=canvas.create_window(0,0,anchor='nw',window=box,width=60,height=60)
    btn_font=tkfont.Font(family=BTN_FONT[0],size=BTN_FONT[1])
    bar_h=max(BAR_H,btn_font.metrics('linespace')+6)   # 写死高度会把按钮切掉一半

    def close():win.withdraw()
    buttons=[]
    def add_button(label,callback):
        item=canvas.create_text(0,0,anchor='nw',text=label,fill=LINK_FG,font=btn_font)
        canvas.tag_bind(item,'<Button-1>',lambda e=None,cb=callback:cb())
        canvas.tag_bind(item,'<Enter>',lambda e=None:canvas.config(cursor='hand2'))
        canvas.tag_bind(item,'<Leave>',lambda e=None:canvas.config(cursor=''))
        buttons.append((item,btn_font.measure(label)))
        return item

    add_button('收起',close)
    add_button('复制',lambda:copy_text(box,True))
    show_item=add_button('显示全部',lambda:getattr(win,'_reveal_all',lambda:None)())

    def button_bar(content_bottom):
        """三个按钮贴在最下面、紧挨内框：从右往左排（右边留出花纹的宽度）。"""
        x=M['right']-BAR_RIGHT_GAP-M['left']-INSET_SIDE
        y=content_bottom-M['content_top']-INSET_TOP-INSET_BOTTOM-bar_h+3
        for item,w in reversed(buttons):
            x-=w
            canvas.coords(item,x,y)
            x-=14

    shown={'extra':None,'frame':None}

    def paint():
        """把外框贴到分层窗口上。尺寸和位置一起给：只改尺寸会让窗口回到默认位置（左上角），
        看起来就是"内容框挤到边框外面"。位置按内容窗现在的位置反推。
        贴完再补一次 geometry：UpdateLayeredWindow 按位图改窗口尺寸后，Tk 那边的记录可能还停在旧值，
        下次布局把窗口改回去，位图就会被拉伸/裁掉（看起来就是"变形"）。"""
        frame=shown['frame']
        if frame is None:return
        fx,fy=win.winfo_x()-(M['left']+INSET_SIDE),win.winfo_y()-(M['content_top']+INSET_TOP)
        geo=f"{frame.width}x{frame.height}+{fx}+{fy}"
        frame_win.geometry(geo)
        frame_win.update_idletasks()
        ok=layered_window.set_image(frame_win,frame)
        frame_win.geometry(geo)
        if not ok or frame_win.winfo_width()!=frame.width or frame_win.winfo_height()!=frame.height:
            # 尺寸没对上：再贴一次，别让窗口和位图不一致
            frame_win.update_idletasks()
            layered_window.set_image(frame_win,frame)
            frame_win.geometry(geo)
        _debug("paint geo=%s ok=%s win=%dx%d content=%dx%d extra=%s" % (
            geo,ok,frame_win.winfo_width(),frame_win.winfo_height(),
            win.winfo_width(),win.winfo_height(),shown['extra']))

    def relayout(extra):
        content_bottom=M['top_h']+M['natural_mid']+extra+M['content_bottom_off']
        if shown['extra']!=extra:
            frame=bubble_frame(extra)
            shown['extra']=extra
            shown['frame']=frame
            paint()
            win._frame_size=(frame.width,frame.height)
            win._frame_visible=(frame.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
                                or (0,0,frame.width,frame.height))
            win._frame_offset=(M['left']+INSET_SIDE,M['content_top']+INSET_TOP)
            h=content_bottom-M['content_top']-INSET_TOP-INSET_BOTTOM
            canvas.config(width=content_w,height=h)
            win.geometry(f"{content_w}x{h}")
        h=content_bottom-M['content_top']-INSET_TOP-INSET_BOTTOM
        box_x1,box_y1=BOX_PAD_X,BOX_PAD_TOP
        box_x2,box_y2=content_w-BOX_PAD_X,h-bar_h-BOX_PAD_BOTTOM   # 白框只铺中间纯色区，底部留给按钮
        canvas.coords(box_item,*_round_points(box_x1,box_y1,box_x2,box_y2,BOX_RADIUS))
        canvas.coords(text_item,box_x1+BOX_INSET,box_y1+BOX_INSET+BOX_TOP_PAD)
        canvas.itemconfig(text_item,
                          width=max(40,int(box_x2-box_x1-2*BOX_INSET)),
                          height=max(20,int(box_y2-box_y1-2*BOX_INSET)))
        button_bar(content_bottom)
        return content_bottom

    state={'text':''}

    def set_text(value):
        value=value or '…'
        previous=state['text']
        follow=box.yview()[1]>=.985
        box.configure(state='normal')
        if value.startswith(previous):box.insert('end',value[len(previous):])
        else:box.delete('1.0','end');box.insert('1.0',value)
        box.configure(state='disabled');state['text']=value
        line_h=max(1,font.metrics('linespace')+7)
        usable=max(60,content_w-2*(BOX_PAD_X+BOX_INSET))
        lines=sum(max(1,math.ceil(font.measure(line)/usable)) for line in value.split('\n'))
        lines=min(max_lines,max(1,lines))
        content_h=(M['top_h']+M['natural_mid']+M['content_bottom_off']-M['content_top']
                   -INSET_TOP-INSET_BOTTOM)
        need=(INSET_TOP+INSET_BOTTOM+BOX_PAD_TOP+BOX_PAD_BOTTOM+2*BOX_INSET+BOX_TOP_PAD
              +lines*line_h+TEXT_PAD_BOTTOM+bar_h)
        extra=max(0,need-content_h)
        content_bottom=relayout(extra)
        canvas.itemconfig(show_item,fill=LINK_FG if hasattr(win,'_reveal_all') else LINK_OFF)
        if follow:box.see('end')
        win.update_idletasks();win.geometry(f"{content_w}x{content_bottom-M['content_top']-INSET_TOP-INSET_BOTTOM}")
        try:
            _debug("set lines=%d extra=%d content=%dx%d text=%dx%d@%d,%d canvas=%dx%d btn_y=%d scale=%.2f ls=%d" % (
                lines,extra,win.winfo_width(),win.winfo_height(),
                box.winfo_width(),box.winfo_height(),
                canvas.coords(text_item)[0],canvas.coords(text_item)[1],
                canvas.winfo_width(),canvas.winfo_height(),
                canvas.coords(buttons[0][0])[1],
                float(win.tk.call("tk","scaling")),font.metrics("linespace")))
        except Exception:
            pass

    def mirror(event=None):
        try:
            if win.state()=='withdrawn':frame_win.withdraw()
            else:
                frame_win.deiconify()
                paint()          # 重新映射后 Tk 可能把分层表面擦掉，补一次
                win.lift()       # deiconify 会把外框抬到最上面，得把内容窗抬回来，不然文字被盖住
        except Exception:pass

    win.bind('<Map>',mirror);win.bind('<Unmap>',mirror)
    win.bind('<Destroy>',lambda e:frame_win.destroy() if frame_win.winfo_exists() else None)

    set_text('…')
    win._text_box=box
    win._frame_win=frame_win
    return win,set_text


