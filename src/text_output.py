"""Incremental, selectable task output and labels that wrap to their container."""
import tkinter as tk


def adaptive_label(parent,**options):
    options.setdefault('justify','left')
    label=tk.Label(parent,**options)
    def resize(event):
        width=max(1,event.width-2*int(label.cget('padx'))-2*int(label.cget('borderwidth')))
        if int(label.cget('wraplength'))!=width:label.configure(wraplength=width)
    label.bind('<Configure>',resize,add='+')
    return label


def update_output(widget,previous,current):
    """Append without disturbing selection; follow only an existing bottom view.

    A task can also replace its output on completion. Keep the common prefix
    and update its tail, preserving selections in text that still exists.
    """
    previous=previous or ''
    if previous==current:return False
    follow=not previous or widget.yview()[1]>=.999
    top=widget.index('@0,0');state=widget.cget('state')
    widget.configure(state='normal')
    try:
        if current.startswith(previous):widget.insert('end-1c',current[len(previous):])
        else:
            prefix=0
            for old,new in zip(previous,current):
                if old!=new:break
                prefix+=1
            # Text's 'chars' modifier counts code points, unlike Tcl string
            # length and numeric columns in Tk 8.6. Keep emoji intact.
            start=f'1.0 + {prefix} chars'
            widget.delete(start,'end-1c');widget.insert(start,current[prefix:])
        if follow:widget.yview_moveto(1)
        else:widget.yview(top)
    finally:widget.configure(state=state)
    return True
