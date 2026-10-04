"""Persistent settings layout, with artwork only for the exposed page."""
import tkinter as tk
from tkinter import ttk
from ui_theme import BG


class SettingsPages(ttk.Frame):
    def __init__(self, parent, titles):
        super().__init__(parent)
        self.pages = {}; self.bodies = {}; self.canvases = {}
        self._focus_options = {}
        self.selected = tk.StringVar(self, value=titles[0])
        self.columnconfigure(1, weight=1); self.rowconfigure(0, weight=1)
        navigation = ttk.Frame(self, padding=(0, 6, 16, 0))
        navigation.grid(row=0, column=0, sticky='ns')
        stack = ttk.Frame(self)
        stack.grid(row=0, column=1, sticky='nsew')
        stack.rowconfigure(0, weight=1); stack.columnconfigure(0, weight=1)
        for title in titles:
            ttk.Radiobutton(navigation, text=title, value=title, variable=self.selected,
                            style='Pet.Nav.TRadiobutton',
                            command=lambda name=title:self.select(name)).pack(fill='x', pady=3)
            page = ttk.Frame(stack)
            page.grid(row=0, column=0, sticky='nsew')
            page.rowconfigure(0, weight=1); page.columnconfigure(0, weight=1)
            canvas = tk.Canvas(page, bg=BG, bd=0, highlightthickness=0, yscrollincrement=24)
            canvas.grid(row=0, column=0, sticky='nsew')
            bar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
            bar.grid(row=0, column=1, sticky='ns')
            canvas.configure(yscrollcommand=bar.set)
            body = ttk.Frame(canvas, padding=(16, 10, 16, 20))
            item = canvas.create_window(0, 0, window=body, anchor='nw')
            def fit(event, view=canvas, content=body, item=item):
                if view.itemcget(item, 'width') != str(event.width):
                    view.itemconfigure(item, width=event.width)
                view.configure(scrollregion=(0, 0, event.width, max(event.height, content.winfo_reqheight())))
            def extent(event, view=canvas, content=body):
                view.configure(scrollregion=(0, 0, view.winfo_width(), max(view.winfo_height(), content.winfo_reqheight())))
            canvas.bind('<Configure>', fit)
            body.bind('<Configure>', extent)
            self.pages[title] = page; self.bodies[title] = body; self.canvases[title] = canvas
        self.select(titles[0])
        parent.bind('<MouseWheel>', self._wheel, add='+')

    def select(self, title):
        if title not in self.pages:return
        previous=self.pages.get(getattr(self, '_active_title', None))
        focus=self.focus_get()
        self.selected.set(title)
        self._active_title=title
        # Retain native widgets and scroll offsets without asking Windows to
        # paint seven full pages stacked at the same location.
        target=self.pages[title]
        for name,page in self.pages.items():
            page._art_hidden=name!=title
            if name!=title and page is not previous:page.grid_remove()
        target.grid()
        if previous is not None and previous is not target:
            target.lower(previous)
        backdrop=getattr(self.winfo_toplevel(),'_art_backdrop',None)
        if backdrop and backdrop.image is not None:
            # Measure the newly mapped page behind the old one, then provide
            # its background before revealing it. Never run timed callbacks.
            self.update_idletasks()
            backdrop.resize_preview()
        if previous is not None and previous is not target:previous.grid_remove()
        target.tkraise()
        def focusable(widget, active):
            if 'takefocus' in widget.keys():
                if widget not in self._focus_options:self._focus_options[widget]=widget.cget('takefocus')
                widget.configure(takefocus=self._focus_options[widget] if active else 0)
            for child in widget.winfo_children():focusable(child, active)
        for name,page in self.pages.items():focusable(page, name==title)
        if focus is not None and previous is not self.pages[title] and str(focus).startswith(str(previous)+'.'):
            self.pages[title].focus_set()

    def _wheel(self, event):
        widget = event.widget
        page = self.pages[self.selected.get()]
        if not (widget is page or str(widget).startswith(str(page)+'.')):return
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Combobox, ttk.Spinbox)):return
        delta = int(-event.delta/120) or (-1 if event.delta>0 else 1)
        self.canvases[self.selected.get()].yview_scroll(delta*2, 'units')
        return 'break'
