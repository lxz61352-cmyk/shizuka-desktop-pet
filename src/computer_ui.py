"""Tk controls for explicit local file tasks. No imports from pet.py."""
import os
from pathlib import Path
import random
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
from computer_agent import ComputerAgent, DshInstallation, load_config, save_config

# 文件任务耗时较长：先以静香口吻应一声，完成后按人设汇报（纯话术，不改任务事实）
COMPUTER_START_LINES = (
    "好，我去看看这些文件，弄好了就回来跟你说。",
    "交给我吧，先动手处理，进度可以在「电脑助手」里看。",
    "收到，这就去整理文件，完成后再跟你汇报。",
    "明白，我先去处理文件，你等我一下。",
    "行，这些文件我来弄，你去忙别的吧。",
)
COMPUTER_DONE_LEADS = {
    "completed": ("弄好了，跟你说下结果：", "搞定，汇报一下：", "处理完了，情况是这样：", "文件那边弄完了，你看看："),
    "failed": ("这次没弄成，情况是：", "没做成功，你看下这个：", "卡住了，没能完成："),
    "cancelled": ("好，我停下来了。", "行，收手了。"),
    "timeout": ("等太久了，我先停手。", "这个任务拖太久，我先停下。"),
}
COMPUTER_DONE_TAILS = (
    "还有要改的地方，随时叫我。",
    "需要别的整理就再跟我说。",
    "有不对的地方我再帮你调。",
    "别的文件要收拾也尽管说。",
)


def computer_command(text):
    match = re.match(r"^/(?:电脑|文件|dsh)(?=$|\s|[:：])(?:[\s:：]*)(.*)$", text.strip(), re.S | re.I)
    return match.group(1).strip() if match else None


class ComputerAssistantMixin:
    def _computer_data_dir(self):
        raise NotImplementedError

    def _computer_init(self):
        if not hasattr(self, "_computer_agent"):
            self._computer_agent = ComputerAgent(self._computer_data_dir())
            self._computer_state = {"status": "就绪", "output": "", "busy": False}
            self._computer_cancel = None

    def _cancel_computer_task(self):
        event = getattr(self, "_computer_cancel", None)
        if event:
            event.set()

    def _computer_busy(self):
        """本机文件任务进行中（含微信侧发起的）→ 主动搭话先让路。"""
        state = getattr(self, "_computer_state", None)
        if state and state.get("busy"):
            return True
        agent = getattr(self, "_computer_agent", None)
        return bool(agent and agent.guard.locked())

    def _start_computer_task(self, task, my_conv):
        self._computer_init()
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
        self._cancel_computer_task()
        self._computer_cancel = token
        self._computer_state = {"status": "正在启动本机 dsh…", "output": "", "busy": True,
                                "task": task, "workspace": config["workspace"]}
        self._close_think_bubble()
        self.say(random.choice(COMPUTER_START_LINES))

        def progress(state):
            def update():
                if self._computer_cancel is token:
                    self._computer_state["status"] = f"正在处理文件 · {state['elapsed']} 秒"
            self._ui(update)

        def worker():
            try:
                result = self._computer_agent.run(task, config, cancel=token, progress=progress)
            except Exception as exc:
                result = {"status": "failed", "error": str(exc), "output": "", "stderr": ""}
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
            summary = "已经改动过的文件会保留，后面的没有再动。详情见电脑助手。"
            label = "已停止"
        elif status == "timeout":
            summary = "可能已经有部分改动，建议去电脑助手核对一下。"
            label = "已超时"
        else:
            summary = "文件任务未完成。" + (error or output or "请查看任务记录。")[:350]
            label = "未完成"
        if self._computer_cancel is token:
            self._computer_state.update(status=label, busy=False, output=output or summary,
                                        error=error, directory=result.get("directory", ""))
            self._computer_cancel = None
        if my_conv != self._conv_id:
            return
        body = summary if len(summary) <= 500 else summary[:500] + "\n（完整结果见“电脑助手”）"
        brief = random.choice(COMPUTER_DONE_LEADS.get(status, COMPUTER_DONE_LEADS["failed"])) + "\n" + body
        if status == "completed" and len(brief) <= 600:
            brief += "\n" + random.choice(COMPUTER_DONE_TAILS)
        self.say(brief)
        # File contents are task evidence, not candidates for automatic memories.
        self._append_history(task, brief)

    def show_computer_assistant(self):
        self.close_popup()
        self._computer_init()
        existing = getattr(self, "_computer_win", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        try:
            config = load_config(self._computer_data_dir())
        except Exception as exc:
            messagebox.showerror("电脑助手配置", str(exc), parent=self.root)
            return
        win = tk.Toplevel(self.root)
        self._computer_win = win
        win.title("电脑助手 · 本机文件任务")
        win.geometry("720x670")
        win.minsize(540, 500)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(5, weight=1)
        top = tk.Frame(win, padx=16, pady=14)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        tk.Label(top, text="电脑助手", font=("Microsoft YaHei UI", 16, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        enabled = tk.BooleanVar(value=config.get("enabled", True))
        tk.Checkbutton(top, text="启用文件任务", variable=enabled).grid(row=0, column=1)
        tk.Label(top, text="由本机 dsh 执行。选择工作文件夹后，可以读取、创建、编辑和整理文件。", anchor="w", wraplength=640).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        detected, detection_error = None, ""
        try:
            detected = DshInstallation.discover(config)
        except Exception as exc:
            detection_error = str(exc)
        paths = tk.Frame(win, padx=16)
        paths.grid(row=1, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        variables = {}
        presets = {"node": detected.node if detected else "", "dsh_cli": detected.cli if detected else ""}
        for row, (key, title) in enumerate((("workspace", "工作文件夹"), ("node", "Node 路径（可留空自动检测）"), ("dsh_cli", "dsh 入口 lib\\bin.js（可留空自动检测）"))):
            tk.Label(paths, text=title, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
            value = tk.StringVar(value=config.get(key) or presets.get(key, ""))
            variables[key] = value
            tk.Entry(paths, textvariable=value).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        connection = tk.StringVar(value="")
        def browse_workspace():
            folder = filedialog.askdirectory(parent=win, title="选择本轮文件任务的工作文件夹", initialdir=variables["workspace"].get())
            if folder:
                variables["workspace"].set(folder)
        def browse_node():
            chosen = filedialog.askopenfilename(parent=win, title="选择 node.exe",
                filetypes=[("Node", "node.exe"), ("可执行文件", "*.exe"), ("全部文件", "*.*")])
            if chosen:
                variables["node"].set(chosen)
        def browse_dsh():
            chosen = filedialog.askopenfilename(parent=win, title="选择 dsh 的 lib\\bin.js（也可以选 dsh 文件夹）",
                filetypes=[("dsh 入口", "bin.js"), ("JavaScript", "*.js *.mjs"), ("全部文件", "*.*")])
            if chosen:
                variables["dsh_cli"].set(chosen)
        tk.Button(paths, text="选择…", command=browse_workspace).grid(row=0, column=2)
        tk.Button(paths, text="浏览…", command=browse_node).grid(row=1, column=2)
        tk.Button(paths, text="浏览…", command=browse_dsh).grid(row=2, column=2)
        def save():
            updated = {**config, **{k: v.get().strip() for k, v in variables.items()}, "enabled": enabled.get()}
            try:
                saved = save_config(self._computer_data_dir(), updated)
                installation = DshInstallation.discover(saved)
                variables["node"].set(installation.node)
                variables["dsh_cli"].set(installation.cli)
                connection.set("已保存 · 已连接本机 dsh")
                return saved
            except Exception as exc:
                connection.set(str(exc))
                return None
        def autodetect():
            try:
                installation = DshInstallation.discover({**config, "node": variables["node"].get().strip(), "dsh_cli": variables["dsh_cli"].get().strip()})
            except Exception as exc:
                connection.set(str(exc))
                return
            variables["node"].set(installation.node)
            variables["dsh_cli"].set(installation.cli)
            save()
        buttons = tk.Frame(paths)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
        tk.Button(buttons, text="保存设置", command=save).pack(side="left")
        tk.Button(buttons, text="自动检测 dsh", command=autodetect).pack(side="left", padx=8)
        tk.Label(paths, textvariable=connection, anchor="w", wraplength=640).grid(row=4, column=0, columnspan=3, sticky="w")
        connection.set("已找到本机 dsh；使用它现有的登录/API 配置" if detected else detection_error)
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
