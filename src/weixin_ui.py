"""Weixin pairing panel and a task adapter for the existing pet brain/dsh."""
import json
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
from computer_agent import load_config
from computer_ui import computer_command
from weixin_channel import BASE_URL, ILinkClient, ProtectedStore, WeixinChannel, session_from_login, trusted_base, IMAGE_BLOCK_MARK

IMAGE_BLOCK_LINE_RE = re.compile(r"^-\s*图\d+（[^）]*）=\s*(.+)$", re.M)


def weixin_image_paths(text):
    """从「[图片]（… - 图3（20260916）= C:\\…jpg）」提示块里取出真实图片路径。"""
    return [m.group(1).strip().rstrip("）") for m in IMAGE_BLOCK_LINE_RE.finditer(text or "")]


def weixin_visible_text(text):
    """去掉图片提示块之后，用户真正说的那句话。"""
    value = text or ""
    cut = value.find(IMAGE_BLOCK_MARK)
    return (value[:cut] if cut >= 0 else value).strip()


_IMAGE_URL_CACHE = {}   # path -> (data_url, 生成时间)：同一张图短时间内别反复解码/编码
IMAGE_URL_TTL = 600     # 缓存 10 分钟，够覆盖「讲下图3」→「那第二问呢」这种追问


def local_image_data_url(path, limit=(1024, 1024), quality=85):
    """本地图片 → data URL（让模型直接看图）。先缩略再解码，别把整张大图全解进内存；
    统一转 JPEG 控制体积。读不出来返回空串。"""
    now = time.time()
    hit = _IMAGE_URL_CACHE.get(path)
    if hit and now - hit[1] < IMAGE_URL_TTL:
        return hit[0]
    try:
        import base64, io
        im = Image.open(path)
        im.thumbnail(limit)          # 内部走 draft/增量解码，比 load() 整幅解码省内存
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
    for old in [key for key, value in _IMAGE_URL_CACHE.items() if now - value[1] >= IMAGE_URL_TTL]:
        _IMAGE_URL_CACHE.pop(old, None)
    _IMAGE_URL_CACHE[path] = (data_url, now)
    return data_url


class WeixinMixin:
    def _weixin_init(self):
        if not hasattr(self, "_weixin_store"):
            import pet as engine
            self._weixin_store = ProtectedStore(self._computer_data_dir(), engine._dpapi)
            self._weixin_channel = None
            self._weixin_login_cancel = threading.Event()
            self._weixin_code_queue = queue.Queue()
            self._weixin_state = {"status": "尚未连接", "output": ""}
            self._computer_init()

    def _weixin_boot(self):
        try:
            self._weixin_init()
            if self._weixin_store.data.get("enabled") and self._weixin_store.data.get("session"):
                self._weixin_connect()
        except Exception:
            self._weixin_boot_error = "微信连接配置无法读取，请打开微信连接窗口检查。"

    def _weixin_media_dir(self):
        """微信发来的图片存到「文件工作区\\微信图片」，方便 /电脑 任务直接读取。"""
        config = load_config(self._computer_data_dir())
        target = Path(config["workspace"]) / "微信图片"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _weixin_connect(self):
        self._weixin_init()
        if self._weixin_channel and not self._weixin_channel.stopped.is_set():
            return
        channel = WeixinChannel(self._weixin_store, self._weixin_reply, media_dir=self._weixin_media_dir)
        def status(value):
            def apply():
                if self._weixin_channel is channel:
                    self._weixin_state.update(value)
            self._ui(apply)
        channel.status = status
        channel.answer_pending=lambda text:self._answer_computer_question(text,origin="weixin")
        self._weixin_channel = channel
        self._weixin_store.update(enabled=True)
        channel.start()

    def _weixin_stop(self, persist=False):
        event = getattr(self, "_weixin_login_cancel", None)
        if event:
            event.set()
        channel = getattr(self, "_weixin_channel", None)
        if channel:
            channel.stop()
        if hasattr(self, "_weixin_state"):
            self._weixin_state["status"] = "已断开"
        if persist and hasattr(self, "_weixin_store"):
            self._weixin_store.update(enabled=False)

    def _weixin_reply(self, text, cancel, progress):
        import pet as engine
        self._last_user_dialogue_at=time.monotonic()
        if cancel.is_set():
            return "任务已取消。"
        completion=self._weixin_complete_reply(text,cancel)
        if completion is not None:
            self._log_chat('user',text,kind='weixin_todo');self._log_chat('assistant',completion,kind='weixin_todo')
            return completion
        from todo_model import command as todo_command
        todo_text=todo_command(text)
        if todo_text is not None:
            self._log_chat('user',text,kind='weixin_todo')
            reply=self._weixin_todo_command(todo_text,cancel)
            self._log_chat('assistant',reply,kind='weixin_todo')
            return reply
        # 消息里可能附带图片提示块（[图片]（… - 图3（…）= C:\…jpg））
        image_paths = weixin_image_paths(text)
        visible = weixin_visible_text(text)
        task = computer_command(text)
        if task is None and engine.has_api_key():
            # 用去掉提示块的原话判意图：带上路径会让路由器把「讲下图3」也当成文件任务。
            # 只有明确要读写文件才交给 DSH，普通看图/讲题走聊天，并把图直接附给模型。
            intent = self._classify_intent(visible)
            if (intent or {}).get("action") == "computer_task":
                task = text
        if cancel.is_set():
            return "任务已取消。"
        self._log_chat("user", visible if image_paths else text,
                       kind="weixin_file" if task is not None else "weixin")
        if task is not None:
            if not task:
                return "在 /电脑 后写具体文件任务，例如：/电脑 列出工作文件夹中的文件。"
            if not self._weixin_store.data.get("allow_computer"):
                return "微信文件任务尚未开启，请在电脑的“微信连接”窗口启用。"
            config = load_config(self._computer_data_dir())
            if not config.get("enabled", True):
                return "电脑助手已关闭，请先在电脑端开启。"
            if not self._computer_claim(cancel):return '上一件文件任务还在处理，等我把它做完。'
            self._computer_state={'busy':True,'status':'正在启动 DSH','output':'','task':task}
            if hasattr(self,'root'):self._ui(lambda:self._computer_open_progress(task,cancel))
            channel=getattr(self,'_weixin_channel',None)
            def file_progress(state):
                self._computer_receive_progress(state,cancel,origin='weixin',channel=channel)
                progress({'status':'等待您回复静香' if state.get('waiting') else self._scene('file_running',seconds=state['elapsed'])})
            try:
                result=self._computer_agent.run(task,config,cancel=cancel,progress=file_progress)
            except Exception as exc:result={'status':'failed','error':str(exc),'output':''}
            finally:
                self._computer_execution_finished(cancel)
                self._computer_release(cancel)
            self._computer_state.update(busy=False,status='执行已返回',output=result.get('output',''))
            if hasattr(self,'root'):self._ui(lambda:self._computer_finish_progress(result,cancel))
            progress({"directory": result.get("directory", "")})
            if result["status"] == "completed":
                reply = self._file_reply(result)
            elif result["status"] == "cancelled":
                reply = self._scene('file_cancelled')
            elif result["status"] == "timeout":
                reply = self._scene('file_timeout')
            else:
                reply = self._file_reply(result)
            if result['status']=='completed' and self._should_sound(event='file_complete'):self._ui(self.play_sound)
            self._log_chat("assistant", reply[:1500], kind="weixin_file")
            return reply
        if not engine.has_api_key():
            return "请先在电脑桌宠中设置聊天 API Key。已有 dsh 配置时，仍可使用 /电脑 文件任务。"
        option = getattr(engine, "character_option", lambda key, default: default)
        system = engine.load_persona() + option("chat_style", engine.CHAT_STYLE_HINT)
        from conversation_memory import CONTINUATION_HINT
        system+='\n'+CONTINUATION_HINT
        system+='\n'+self._capability_context()
        notes=self._todo_note_context(visible,channel='weixin',cancel=cancel.is_set)
        if cancel.is_set():return '本轮回复已停止。'
        system+='\n只有应用明确回传保存成功时才能说已增加待办备注。'
        if notes:system+='\n'+notes
        system += ("\n当前通过手机微信交流：屏幕小、打字慢，能用一两句说清的就别写成一段。"
                   "只回复需要发给用户的文字；没有调用文件执行器时，不要声称已读取或修改电脑文件。"
                   "文件操作请让用户发 /电脑 加具体任务。")
        memory = self._get_memory_block(visible)
        if memory:
            system += "\n\n" + memory
        messages = [{"role": "system", "content": system}]
        messages.extend(self._recent_messages(current_text=visible,channel='weixin'))
        parts = [{"type": "text", "text": visible or "（图片）"}]
        attached = 0
        for path in image_paths:
            data_url = local_image_data_url(path)
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
                attached += 1
        if attached:
            # 只有真的把图附上去了才这么说，否则模型会硬说「我看到了」
            system += "\n本轮用户发来的图片已经直接附在消息里，直接看图回答，不要说看不到图片。"
            messages[0] = {"role": "system", "content": system}
        messages.append({"role": "user", "content": parts if attached else visible})
        output = []
        client = engine.get_client()
        with client.chat.completions.create(model=engine.api_model(), messages=messages,
                temperature=.7, max_tokens=3200, stream=True) as stream:
            for chunk in stream:
                if cancel.is_set():
                    return "本轮回复已停止。"
                if chunk.choices:
                    output.append(chunk.choices[0].delta.content or "")
        reply = engine.clean_reply_style("".join(output)).strip() or "刚才没有收到完整回复，请再试一次。"
        if not cancel.is_set():
            self._log_chat("assistant", reply, kind="weixin")
            # Plain conversation shares long-term memory; file results bypass this path.
            def remember():
                try:
                    self._refresh_memories(reply)
                    engine.get_memory().save()
                    self._maybe_review_memory()
                except Exception:
                    pass
            threading.Thread(target=remember, daemon=True).start()
        return reply

    def _weixin_begin_login(self):
        self._weixin_stop()
        cancel = threading.Event()
        self._weixin_login_cancel = cancel
        self._weixin_code_queue = queue.Queue()
        self._weixin_state.update(status="正在获取微信二维码…", qr=None, verify=False)
        def update(**values):
            def apply():
                if self._weixin_login_cancel is cancel:
                    self._weixin_state.update(values)
            self._ui(apply)
        def login():
            try:
                client = ILinkClient()
                qr = client.qr()
                update(qr=qr["qrcode_img_content"], status="请用手机微信扫码，并按手机提示确认")
                deadline, verify = time.monotonic() + 300, ""
                while not cancel.is_set() and time.monotonic() < deadline:
                    try:
                        state = client.qr_status(qr["qrcode"], verify)
                    except (ConnectionError, TimeoutError):
                        cancel.wait(1)
                        continue
                    if cancel.is_set():
                        return
                    status = state.get("status")
                    if status == "confirmed":
                        session = session_from_login(state)
                        def finish():
                            if self._weixin_login_cancel is not cancel or cancel.is_set():
                                return
                            self._weixin_store.update(session=session, cursor="", seen={}, enabled=True, last_result="",notification_context=None)
                            self._weixin_state.update(qr=None, verify=False, status="已绑定，正在连接…")
                            self._weixin_connect()
                        self._ui(finish)
                        return
                    if status == "need_verifycode":
                        update(verify=True, status="请把手机微信显示的配对数字填入下方，然后点“提交配对码”")
                        while not cancel.is_set() and time.monotonic() < deadline:
                            try:
                                verify = self._weixin_code_queue.get(timeout=.3)
                                break
                            except queue.Empty:
                                continue
                        continue
                    if status == "scaned":
                        verify = ""
                        update(verify=False, status="已扫码，等待手机确认…")
                    elif status == "scaned_but_redirect":
                        client.base = trusted_base("https://" + str(state.get("redirect_host", "")))
                    elif status in ("expired", "verify_code_blocked"):
                        update(qr=None, verify=False, status="二维码已过期或配对暂不可用，请重新生成二维码")
                        return
                    elif status == "binded_redirect":
                        update(qr=None, verify=False, status="该机器人已绑定；如本机已有绑定记录，请点击连接")
                        return
                    cancel.wait(.5)
                if not cancel.is_set():
                    update(qr=None, verify=False, status="扫码等待超时，请重新生成二维码")
            except Exception as exc:
                update(qr=None, verify=False, status="微信绑定未完成：" + str(exc)[:200])
        threading.Thread(target=login, name="deskpet-weixin-pair", daemon=True).start()

    def show_weixin(self):
        self.close_popup()
        try:
            self._weixin_init()
        except Exception:
            messagebox.showerror("微信连接", "微信配置无法解密或读取，请先保留原文件并检查当前 Windows 用户。", parent=self.pet)
            return
        existing = getattr(self, "_weixin_win", None)
        if existing is not None and existing.winfo_exists():
            self._move_dialog(existing, 660, 800)
            return
        win = tk.Toplevel(self.root)
        self._weixin_win = win
        win.title("微信连接 · 手机聊天与文件任务")
        win.minsize(580, 660)
        self._place_dialog(win, 660, 800)
        top = tk.Frame(win, padx=18, pady=12)
        top.pack(fill="x")
        tk.Label(top, text="把桌宠连到手机微信", font=("Microsoft YaHei UI", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(top, text="手机发消息，桌宠在这台电脑上处理，再回复到微信。电脑和桌宠需要保持运行。", wraplength=610, anchor="w").pack(fill="x", pady=8)
        controls = tk.Frame(top);controls.pack(fill="x")
        tk.Button(controls, text="生成绑定二维码", command=self._weixin_begin_login).pack(side="left")
        def connect():
            try:
                self._weixin_connect()
            except Exception as exc:
                self._weixin_state["status"] = str(exc)
        tk.Button(controls, text="连接", command=connect).pack(side="left", padx=8)
        tk.Button(controls, text="断开", command=lambda: self._weixin_stop(persist=True)).pack(side="left")
        def stop_task():
            if self._weixin_channel:
                self._weixin_channel.cancel_task()
        tk.Button(controls, text="停止当前任务", command=stop_task).pack(side="left", padx=8)
        remote = tk.BooleanVar(value=bool(self._weixin_store.data.get("allow_computer")))
        tk.Checkbutton(top, text="允许绑定的微信账号执行文件任务（使用电脑助手的工作文件夹）", variable=remote,
            command=lambda: self._weixin_store.update(allow_computer=remote.get())).pack(anchor="w", pady=(12, 4))
        tk.Button(top, text="设置文件工作文件夹…", command=self.show_computer_assistant).pack(anchor="w")
        status_label = tk.Label(top, text="", wraplength=610, anchor="w", justify="left")
        status_label.pack(fill="x", pady=8)
        qr_label = tk.Label(win, text="点击上方按钮，用手机微信扫码绑定", width=38, height=2)
        qr_label.pack(pady=4)
        verify_frame = tk.Frame(win)
        tk.Label(verify_frame, text="手机显示的配对码：").pack(side="left")
        code = tk.Entry(verify_frame, width=12)
        code.pack(side="left")
        def submit_code():
            value = code.get().strip()
            if value.isdigit() and len(value) <= 12:
                self._weixin_code_queue.put(value)
                code.delete(0, "end")
                self._weixin_state.update(verify=False, status="正在核对配对码…")
        tk.Button(verify_frame, text="提交配对码", command=submit_code).pack(side="left", padx=8)
        help_label = tk.Label(win, text="微信中可直接聊天，或输入 /电脑 加文件任务。\n/停止 停止任务 · /状态 查看进度 · /结果 查看最近结果", wraplength=610, justify="left")
        help_label.pack(pady=10)
        output = ScrolledText(win, height=8, wrap="word", state="disabled")
        output.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        last = {"qr": None, "output": None}
        def refresh():
            if not win.winfo_exists():
                return
            state = self._weixin_state
            status_label.configure(text=state.get("status", ""))
            qr = state.get("qr")
            if qr != last["qr"]:
                last["qr"] = qr
                if qr:
                    import qrcode
                    code_image = qrcode.QRCode(box_size=1, border=4)
                    code_image.add_data(qr);code_image.make(fit=True)
                    image = code_image.make_image().convert("RGB")
                    size = image.width * max(2, 320 // image.width)
                    image = image.resize((size, size), Image.Resampling.NEAREST)
                    qr_label.image = ImageTk.PhotoImage(image)
                    qr_label.configure(image=qr_label.image, text="", width=0, height=0)
                else:
                    qr_label.configure(image="", text="已保存绑定" if self._weixin_store.data.get("session") else "点击上方按钮生成二维码", width=38, height=2)
                    qr_label.image = None
            if state.get("verify"):
                verify_frame.pack(before=help_label, pady=6)
            else:
                verify_frame.pack_forget()
            text = state.get("output") or self._weixin_store.data.get("last_result", "")
            if text != last["output"]:
                last["output"] = text
                output.configure(state="normal");output.delete("1.0", "end")
                output.insert("1.0", text);output.configure(state="disabled")
            win.after(400, refresh)
        refresh()
