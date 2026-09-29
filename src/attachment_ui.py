"""Pick, preview, reorder and reuse material without image-number commands."""
import threading,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk,ImageGrab
from attachment_files import (MAX_ATTACH,load_material,image_attachment,pdf_count,pdf_page,page_numbers,AttachmentShelf)
from ui_theme import apply,PAGE_X


class AttachmentMixin:
    def _attachment_shelf(self):
        import pet
        return AttachmentShelf(pet.DATA_DIR)

    def _remember_attachments(self,atts):
        if atts:self._attachment_shelf().remember(atts)

    def attach_file(self,atts,on_change):
        self._chat_attach_busy=True
        try:
            paths=filedialog.askopenfilenames(parent=self._chat_win,title='选取图片、PDF或文本',
                filetypes=[('图片 / PDF / 文本','*.png *.jpg *.jpeg *.webp *.pdf *.txt *.md *.csv *.py'),('所有文件','*.*')])
            self._attach_paths(list(paths),atts,on_change)
        finally:
            if not getattr(self,'_pdf_picker',None):self._chat_attach_busy=False
            self._refocus_chat_entry()

    def _attach_paths(self,paths,atts,on_change):
        while paths:
            if len(atts)>=MAX_ATTACH:
                messagebox.showinfo('附件',f'一次最多{MAX_ATTACH}个附件或PDF页面；余下文件未加入。',parent=self._chat_win);break
            path=paths.pop(0)
            if path.lower().endswith('.pdf'):
                self._pick_pdf_pages(path,atts,on_change,lambda:self._attach_paths(paths,atts,on_change));return
            try:atts.append(load_material(path))
            except Exception as error:messagebox.showerror('附件未加入',str(error),parent=self._chat_win)
        on_change()

    def paste_attachment(self,atts,on_change):
        try:
            value=ImageGrab.grabclipboard()
            if isinstance(value,Image.Image):
                if len(atts)>=MAX_ATTACH:
                    messagebox.showinfo('附件',f'一次最多{MAX_ATTACH}个附件。',parent=self._chat_win);return 'break'
                atts.append(image_attachment(value,'粘贴的图片'));on_change();return 'break'
            if isinstance(value,list):
                self._attach_paths(list(value),atts,on_change);return 'break'
        except Exception as error:messagebox.showerror('粘贴附件',str(error),parent=self._chat_win);return 'break'
        return None # Ordinary text keeps the native paste binding.

    def _pick_pdf_pages(self,path,atts,on_change,after_close=None):
        if getattr(self,'_pdf_picker',None):return
        self._chat_attach_busy=True
        win=tk.Toplevel(self.root);self._pdf_picker=win;win.title('PDF预览与选页');self._place_dialog(win,760,720)
        from ui_theme import page_header
        page_header(win,'PDF · 选择发送的页面').pack(fill='x')
        status=tk.StringVar(value='正在读取页数…');ttk.Label(win,textvariable=status,wraplength=700).pack(fill='x',padx=PAGE_X)
        controls=ttk.Frame(win);controls.pack(fill='x',padx=PAGE_X,pady=8)
        selection=tk.StringVar(value='1');ttk.Label(controls,text='发送页码').pack(side='left')
        ttk.Entry(controls,textvariable=selection,width=15).pack(side='left',padx=8)
        ttk.Label(controls,text='例如 1,3-5；只发送所选页面').pack(side='left')
        preview=ttk.Label(win,anchor='center');preview.pack(fill='both',expand=True,padx=PAGE_X)
        bottom=ttk.Frame(win);bottom.pack(fill='x',padx=PAGE_X,pady=12)
        page=[1];total=[0];busy=[False];generation=[0]
        def close():
            generation[0]+=1;self._pdf_picker=None;self._chat_attach_busy=False;win.destroy();self._refocus_chat_entry()
            if after_close and getattr(self,'_chat_win',None) is not None:self.root.after(0,after_close)
        def job(work,done):
            if busy[0]:return
            busy[0]=True;token=generation[0]
            def worker():
                try:result=work();error=None
                except Exception as exc:result=None;error=str(exc)
                def finish():
                    if not win.winfo_exists() or token!=generation[0]:return
                    busy[0]=False
                    if error:status.set('读取失败：'+error);return
                    done(result)
                self._ui(finish)
            threading.Thread(target=worker,daemon=True).start()
        def show(att):
            im=att['image'].copy();im.thumbnail((660,460));photo=ImageTk.PhotoImage(im,master=win)
            preview.configure(image=photo);preview.image=photo;status.set(f'共{total[0]}页 · 预览第{page[0]}页 · {att["note"]}')
        def turn(delta):
            if busy[0] or not total[0]:return
            page[0]=max(1,min(total[0],page[0]+delta));job(lambda:pdf_page(path,page[0],True),show)
        def add():
            if busy[0] or not total[0]:return
            try:numbers=page_numbers(selection.get(),total[0],MAX_ATTACH-len(atts))
            except ValueError as error:status.set(str(error));return
            status.set('正在准备选中的页面…')
            def accepted(values):atts.extend(values);on_change();close()
            job(lambda:[pdf_page(path,n) for n in numbers],accepted)
        ttk.Button(bottom,text='上一页',command=lambda:turn(-1)).pack(side='left')
        ttk.Button(bottom,text='下一页',command=lambda:turn(1)).pack(side='left',padx=8)
        ttk.Button(bottom,text='加入所选页面',command=add).pack(side='right')
        ttk.Button(bottom,text='取消',command=close).pack(side='right',padx=8)
        def loaded(count):total[0]=count;turn(0)
        win.protocol('WM_DELETE_WINDOW',close);apply(win);job(lambda:pdf_count(path),loaded)

    def manage_attachments(self,atts,on_change):
        win=self._experience_window('_material_manager','本轮附件与最近材料',860,670)
        if win is None:return
        self._chat_attach_busy=True
        def close():self._chat_attach_busy=False;win.destroy();self._refocus_chat_entry()
        win.protocol('WM_DELETE_WINDOW',close);win.bind('<Escape>',lambda e:close())
        book=ttk.Notebook(win);book.pack(fill='both',expand=True,padx=PAGE_X,pady=10)
        current=ttk.Frame(book);recent=ttk.Frame(book);book.add(current,text='本轮待发送');book.add(recent,text='最近30份材料')
        listing=tk.Listbox(current,height=6,exportselection=False);listing.pack(fill='x')
        info=tk.StringVar();ttk.Label(current,textvariable=info,wraplength=730).pack(fill='x',pady=8)
        preview=ttk.Label(current,anchor='center');preview.pack(fill='both',expand=True)
        def render():
            listing.delete(0,'end')
            for i,r in enumerate(atts,1):listing.insert('end',str(i)+'. '+r.get('name','图片')+' · '+r.get('note',''))
            on_change()
        def show(event=None):
            chosen=listing.curselection()
            if not chosen:return
            att=atts[chosen[0]];info.set(att.get('note','')+('；文字已截断' if att.get('truncated') else ''))
            if att.get('image') is not None:
                im=att['image'].copy();im.thumbnail((710,280));photo=ImageTk.PhotoImage(im,master=win)
                preview.configure(image=photo,text='');preview.image=photo
            else:preview.configure(image='',text=att.get('text','')[:700],wraplength=700)
        listing.bind('<<ListboxSelect>>',show)
        controls=ttk.Frame(current);controls.pack(fill='x',pady=8)
        def move(delta):
            chosen=listing.curselection()
            if not chosen:return
            i=chosen[0];j=i+delta
            if 0<=j<len(atts):atts[i],atts[j]=atts[j],atts[i];render();listing.selection_set(j);show()
        def remove():
            chosen=listing.curselection()
            if chosen:atts.pop(chosen[0]);render();preview.configure(image='',text='')
        for label,command in [('上移',lambda:move(-1)),('下移',lambda:move(1)),('移除',remove)]:ttk.Button(controls,text=label,command=command).pack(side='left',padx=4)
        shelf=self._attachment_shelf();rows=list(reversed(shelf.rows()));saved=tk.Listbox(recent,selectmode='extended',exportselection=False)
        saved.pack(fill='both',expand=True)
        for row in rows:saved.insert('end',row['name']+' · '+row.get('note',''))
        def reuse():
            picked=saved.curselection()
            if len(atts)+len(picked)>MAX_ATTACH:messagebox.showinfo('附件',f'一次最多{MAX_ATTACH}个附件。',parent=win);return
            try:values=[shelf.get(rows[i]) for i in picked]
            except Exception:messagebox.showerror('附件','缓存材料已不可用，请重新选择原文件。',parent=win);return
            atts.extend(values);render();book.select(current)
        def forget():
            picked=saved.curselection()
            shelf.forget({rows[i]['id'] for i in picked})
            for i in reversed(picked):rows.pop(i);saved.delete(i)
        recent_actions=ttk.Frame(recent);recent_actions.pack(fill='x',pady=8)
        ttk.Button(recent_actions,text='删除所选缓存',command=forget).pack(side='left')
        ttk.Button(recent_actions,text='加入本轮',command=reuse).pack(side='right')
        ttk.Button(win,text='返回聊天',command=close).pack(anchor='e',padx=PAGE_X,pady=12)
        apply(win);render()
