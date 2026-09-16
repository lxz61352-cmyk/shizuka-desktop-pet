"""Bounded, scrollable and selectable speech panel for short and long replies."""
import math,tkinter as tk
from tkinter import ttk,font as tkfont
from ui_theme import BG,CARD,INK,MUTED,LINE,copy_bindings,copy_text,round_window

BUBBLE_RADIUS=12  # 气泡圆角

def make_bubble(parent,**unused):
    win=tk.Toplevel(parent);win.withdraw();win.overrideredirect(True);win.attributes('-topmost',True)
    round_window(win,BUBBLE_RADIUS)   # 小圆角：内容往里缩 R，四角露透明
    panel=tk.Frame(win,bg=CARD);panel.pack(fill='both',expand=True,padx=BUBBLE_RADIUS,pady=BUBBLE_RADIUS)
    width=min(460,max(280,parent.winfo_screenwidth()-80))
    frame=tk.Frame(panel,bg=CARD);frame.pack(fill='both',expand=True,padx=(12,6),pady=(12,4))
    font=tkfont.Font(family='Microsoft YaHei UI',size=12)
    box=tk.Text(frame,width=38,height=2,wrap='word',bg=CARD,fg=INK,font=font,
        relief='flat',bd=0,highlightthickness=0,selectbackground='#DCE7E9',selectforeground=INK,
        spacing1=2,spacing3=5,state='disabled',cursor='arrow',exportselection=False)
    bar=ttk.Scrollbar(frame,orient='vertical',command=box.yview);bar.pack(side='right',fill='y')
    box.configure(yscrollcommand=bar.set);box.pack(side='left',fill='both',expand=True)
    copy_bindings(box)
    foot=tk.Frame(panel,bg=CARD);foot.pack(fill='x',padx=12,pady=(0,8))
    tk.Label(foot,text='静香',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='left')
    tk.Button(foot,text='收起',bg=CARD,fg=MUTED,relief='flat',bd=0,command=win.withdraw).pack(side='right')
    tk.Button(foot,text='复制',bg=CARD,fg=MUTED,relief='flat',bd=0,
              command=lambda:copy_text(box,True)).pack(side='right')
    show=tk.Button(foot,text='显示全部',bg=CARD,fg=MUTED,relief='flat',bd=0,
                   command=lambda:getattr(win,'_reveal_all',lambda:None)())
    show.pack(side='right',padx=8)
    win._text_box=box;win._show_all_button=show
    max_lines=max(4,min(14,(parent.winfo_screenheight()//2-70)//max(1,font.metrics('linespace')+7)))
    state={'text':''}
    def set_text(value):
        value=value or '…';previous=state['text']
        follow=box.yview()[1]>=.985
        box.configure(state='normal')
        if value.startswith(previous):box.insert('end',value[len(previous):])
        else:box.delete('1.0','end');box.insert('1.0',value)
        box.configure(state='disabled');state['text']=value
        lines=sum(max(1,math.ceil(font.measure(line)/max(1,width-65))) for line in value.split('\n'))
        box.configure(height=min(max_lines,max(2,lines)))
        if follow:box.see('end')
        show.configure(state='normal' if hasattr(win,'_reveal_all') else 'disabled')
        win.update_idletasks();win.geometry(f'{width}x{win.winfo_reqheight()}')
    set_text('…')
    return win,set_text
