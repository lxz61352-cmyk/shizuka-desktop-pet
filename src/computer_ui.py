"""Tk controls for explicit local file tasks. No imports from pet.py."""
import os
from pathlib import Path
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox,ttk
from tkinter.scrolledtext import ScrolledText
from computer_agent import ComputerAgent, DshInstallation, load_config, save_config, MODEL_CHOICES, resolved_task_model
from computer_progress import ComputerProgressMixin,PendingQuestions


def computer_command(text):
    match = re.match(r"^/(?:电脑|文件|dsh)(?=$|\s|[:：])(?:[\s:：]*)(.*)$", text.strip(), re.S | re.I)
    return match.group(1).strip() if match else None


class ComputerAssistantMixin(ComputerProgressMixin):
    def _computer_data_dir(self):
        raise NotImplementedError

    def _computer_init(self):
        if not hasattr(self, "_computer_agent"):
            self._computer_agent = ComputerAgent(self._computer_data_dir())
            self._computer_state = {"status": "就绪", "output": "", "busy": False}
            self._computer_cancel = None
        if not hasattr(self,"_computer_job_lock"):
            self._computer_job_lock=threading.Lock()
            self._computer_questions=PendingQuestions(self._computer_agent)

    def _cancel_computer_task(self):
        event = getattr(self, "_computer_cancel", None)
        if event:
            event.set()
            if hasattr(self,'_computer_state'):self._computer_state['status']=self._scene('file_task_cancel_requested')

    def _start_computer_task(self, task, my_conv):
        self._computer_init()
        # Keep task evidence out of the automatic personal-conversation summaries.
        with self._chat_lock:
            for row in reversed(self._chat_log):
                if row.get("role")=="user" and row.get("text","").endswith(task):
                    row["kind"]="computer_task"
                    self._write_chatlog(list(self._chat_log))
                    break
        try:
            config = load_config(self._computer_data_dir())
        except Exception as exc:
            self._close_think_bubble()
            self.say("电脑助手配置无法读取：" + str(exc))
            return
        if not config.get("enabled", True):
            self._close_think_bubble()
            self.say("电脑助手已关闭，可以从菜单里的“电脑助手”开启。")
            return
        token = threading.Event()
        if not self._computer_claim(token):
            self._close_think_bubble();self.say("上一件事还在处理，等我把它做完。",source="文件任务");return
        self._computer_state = {"status": "任务已经接下，正在启动执行器。", "output": "", "busy": True,
                                "task": task, "workspace": config["workspace"]}
        self._close_think_bubble()
        self.say(self._scene('file_start'),source="文件任务")
        self._computer_open_progress(task,token)

        def progress(state):
            self._computer_receive_progress(state,token)

        def worker():
            try:
                result = self._computer_agent.run(task, config, cancel=token, progress=progress)
            except Exception as exc:
                result = {"status": "failed", "error": str(exc), "output": "", "stderr": ""}
            self._ui(lambda:self._computer_execution_finished(token))
            if result['status']=='completed':self._ui(lambda:self._computer_finish_progress(result,token))
            if self._computer_can_reply(my_conv,token):
                self._ui(lambda:self._computer_state.update(status='执行已经返回，我在整理结果。') if self._computer_cancel is token else None)
                result['spoken_reply']=self._file_reply(result)
            self._ui(lambda: self._computer_task_done(task, result, my_conv, token))
        threading.Thread(target=worker, name="deskpet-computer-task", daemon=True).start()

    def _computer_task_done(self, task, result, my_conv, token):
        status = result["status"]
        output = result.get("output", "").strip()
        error = result.get("error") or result.get("stderr", "").strip()
        if status == "completed":
            summary = output or "本机助手已返回，未提供文字结果。请查看任务记录核对。"
            label = "本机助手已返回"
        elif status == "cancelled":
            summary = "文件任务已停止。已经完成的文件更改会保留，详情见执行过程。"
            label = "已停止"
        elif status == "timeout":
            summary = "文件任务达到时限，已停止本次执行。可能已有部分更改，详情见执行过程。"
            label = "已超时"
        else:
            summary = "文件任务未完成。" + (error or output or "请查看任务记录。")[:350]
            label = "未完成"
        if self._computer_cancel is token:
            self._computer_state.update(status=label, busy=False, executing=False, output=output or summary,
                                        error=error, directory=result.get("directory", ""))
        self._computer_finish_progress(result,token)
        self._computer_release(token)
        if status=='completed' and self._should_sound(event='file_complete'):
            self._ui(self.play_sound)
        if not self._computer_can_reply(my_conv,token):
            return
        from dialogue_style import file_result
        summary=result.get('spoken_reply') or file_result(result,self._dialogue_style())
        brief = summary
        self.say(brief,source="文件任务")
        # 文件内容只是本轮任务证据：这条路径不调 _post_memory，不会被提炼成长期记忆。

    def show_computer_assistant(self):
        self.close_popup()
        self._computer_init()
        existing = getattr(self, "_computer_win", None)
        if existing is not None and existing.winfo_exists():
            self._move_dialog(existing, 720, 670)
            return
        try:
            config = load_config(self._computer_data_dir())
        except Exception as exc:
            messagebox.showerror("电脑助手配置", str(exc), parent=self.pet)
            return
        win = tk.Toplevel(self.root)
        self._computer_win = win
        win.title("电脑助手 · 本机文件任务")
        win.minsize(540, 500)
        self._place_dialog(win, 720, 670)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(5, weight=1)
        top = tk.Frame(win, padx=16, pady=14)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        tk.Label(top, text="电脑助手", font=("Microsoft YaHei UI", 16, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        enabled = tk.BooleanVar(value=config.get("enabled", True))
        tk.Checkbutton(top, text="启用文件任务", variable=enabled).grid(row=0, column=1)
        tk.Label(top, text="由本机 dsh 执行。选择工作文件夹后，可以读取、创建、编辑和整理文件。", anchor="w", wraplength=640).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        paths = tk.Frame(win, padx=16)
        paths.grid(row=1, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        variables = {}
        scopes={'当前账户可访问的目录':'danger-full-access','仅工作文件夹内写入':'workspace-write'}
        scope=tk.StringVar(value=next((label for label,mode in scopes.items() if mode==config.get('permission_mode','workspace-write')),'仅工作文件夹内写入'))
        tk.Label(paths,text='文件操作范围',anchor='w').grid(row=3,column=0,sticky='w',pady=6)
        ttk.Combobox(paths,textvariable=scope,values=tuple(scopes),state='readonly',width=27).grid(row=3,column=1,sticky='ew',padx=8)
        # 任务模型：选项值 → 显示名；下面实时显示这次任务实际会用的模型
        model_labels={value:label for value,label in MODEL_CHOICES.items()}
        model=tk.StringVar(value=model_labels.get(config.get('model','follow-chat'),model_labels['follow-chat']))
        resolved=tk.StringVar()
        def show_model(*_):
            value=next((k for k,v in model_labels.items() if v==model.get()),'follow-chat')
            resolved.set('实际使用：'+resolved_task_model(value,self._computer_data_dir()))
        tk.Label(paths,text='任务模型',anchor='w').grid(row=4,column=0,sticky='w',pady=6)
        box=ttk.Combobox(paths,textvariable=model,values=tuple(model_labels.values()),state='readonly',width=27)
        box.grid(row=4,column=1,sticky='ew',padx=8);box.bind('<<ComboboxSelected>>',show_model)
        show_model()
        for row, (key, title) in enumerate((("workspace", "工作文件夹"), ("node", "Node 路径（可留空）"), ("dsh_cli", "dsh bin.js（可留空）"))):
            tk.Label(paths, text=title, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
            value = tk.StringVar(value=config.get(key, ""))
            variables[key] = value
            tk.Entry(paths, textvariable=value).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        def browse():
            folder = filedialog.askdirectory(parent=win, title="选择本轮文件任务的工作文件夹", initialdir=variables["workspace"].get())
            if folder:
                variables["workspace"].set(folder)
        tk.Button(paths, text="选择…", command=browse).grid(row=0, column=2)
        connection = tk.StringVar(value="")
        def save():
            value=next((k for k,v in model_labels.items() if v==model.get()),'follow-chat')
            updated = {**config, **{k: v.get().strip() for k, v in variables.items()}, "enabled": enabled.get(),
                       'permission_mode':scopes[scope.get()], 'model':value}
            try:
                saved = save_config(self._computer_data_dir(), updated)
                installation = DshInstallation.discover(saved)
                connection.set("已保存 · 已找到本机 dsh")
                show_model()
                return saved
            except Exception as exc:
                connection.set(str(exc))
                return None
        tk.Button(paths, text="保存设置", command=save).grid(row=5, column=0, sticky="w", pady=8)
        tk.Label(paths, textvariable=connection, anchor="w", wraplength=480).grid(row=5, column=1, columnspan=2, sticky="w")
        tk.Label(paths, textvariable=resolved, anchor="w", fg="#7a7a7a").grid(row=6, column=1, columnspan=2, sticky="w")
        try:
            DshInstallation.discover(config)
            connection.set("已找到本机 dsh；使用它现有的登录/API 配置")
        except Exception as exc:
            connection.set(str(exc))
        input_frame = tk.Frame(win, padx=16, pady=10)
        input_frame.grid(row=2, column=0, sticky="ew")
        tk.Label(input_frame, text="文件任务", anchor="w").pack(fill="x")
        task_box = tk.Text(input_frame, height=4, wrap="word")
        task_box.pack(fill="x", pady=6)
        tk.Label(input_frame, text="例如：列出文件夹中的文件；把笔记整理为 Markdown。也可在聊天中输入 /电脑 加任务内容。", anchor="w", wraplength=640).pack(fill="x")
        controls = tk.Frame(win, padx=16)
        controls.grid(row=3, column=0, sticky="ew")
        def execute():
            task = task_box.get("1.0", "end").strip()
            if task and save():
                self.on_chat_submit("/电脑 " + task)
        start = tk.Button(controls, text="执行任务", command=execute)
        start.pack(side="left")
        stop = tk.Button(controls, text="停止任务", command=self._cancel_computer_task)
        stop.pack(side="left", padx=8)
        def open_folder(logs=False):
            folder = self._computer_state.get("directory") if logs else variables["workspace"].get()
            if folder and Path(folder).is_dir() and os.name == "nt":
                os.startfile(str(Path(folder).resolve()))
        tk.Button(controls, text="打开工作文件夹", command=open_folder).pack(side="left", padx=4)
        tk.Button(controls, text="打开任务记录", command=lambda: open_folder(True)).pack(side="left", padx=4)
        status_text = tk.StringVar()
        tk.Label(win, textvariable=status_text, anchor="w", padx=16, pady=10).grid(row=4, column=0, sticky="ew")
        output_box = ScrolledText(win, wrap="word", state="disabled", height=12)
        output_box.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 16))
        previous = [None]
        def refresh():
            if not win.winfo_exists():
                return
            state = self._computer_state
            status_text.set(state.get("status", "就绪"))
            start.configure(state="disabled" if state.get("busy") else "normal")
            stop.configure(state="normal" if state.get("busy") else "disabled")
            output = state.get("output", "")
            if state.get("error"):
                output += "\n\n执行信息：\n" + state["error"]
            if previous[0] != output:
                output_box.configure(state="normal")
                output_box.delete("1.0", "end")
                output_box.insert("1.0", output)
                output_box.configure(state="disabled")
                previous[0] = output
            win.after(500, refresh)
        refresh()
