"""番茄钟：图标按钮 → 桌宠头顶面板（开始 / 设置）→ 专注时桌宠隐藏、屏幕左下角浮动倒计时。

「是不是游戏」复用 quiet_mode 的判定：进程名命中就算；全屏但名字不认识时**静默搜一次**再决定
（结果缓存），不是游戏就不管，避免把普通全屏程序误判成游戏。

界面一律用 Canvas 画在表盘图上（窗口走色键透明），所以没有白底、倒计时也没有白框。
"""
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont
from PIL import Image, ImageTk
from ui_theme import INK,page_header,PAGE_X

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POMODORO_CLOCK_PATH = os.path.join(_ROOT, "assets", "pomodoro_clock.png")

FOCUS_DEFAULT = 25        # 专注分钟
BREAK_DEFAULT = 5         # 休息分钟
TICK_MS = 200             # 倒计时刷新间隔
PANEL_CLOCK = 190         # 头顶面板里的表盘边长
FLOAT_CLOCK = 215         # 浮动番茄钟的表盘边长
FLOAT_MARGIN = 26         # 浮动番茄钟离屏幕边角多远
MIN_MINUTES, MAX_MINUTES = 1, 180
POMO_BLUE = "#1a63c8"     # 倒计时和按钮的字色（蓝）
POMO_KEY = "#FF00FE"      # 色键（表盘素材里没有这个颜色）
GAME_CACHE = {}           # 静默搜索的结论：{进程名: True/False}


class PomodoroMixin:
    # ---------------- 初始化 / 设置 ----------------
    def _pomodoro_init(self):
        self._pomo_focus = self._pomo_minutes("pomodoro_focus", FOCUS_DEFAULT)
        self._pomo_break = self._pomo_minutes("pomodoro_break", BREAK_DEFAULT)
        self._pomo_phase = None            # None / 'focus' / 'break'
        self._pomo_end_at = 0.0
        self._pomo_after = None
        self._pomo_panel = None
        self._pomo_panel_canvas = None
        self._pomo_panel_text = None
        self._pomo_float = None
        self._pomo_float_canvas = None
        self._pomo_float_text = None
        self._pomo_float_geo = None
        self._pomo_drag = None
        self._pomo_game_asked = set()
        self._pomo_pending_announce = ""
        self._pomo_game_check_id = None
        self._pomo_outside_id = None
        self._pomo_settings_win = None

    def _pomo_minutes(self, key, default):
        try:
            value = int(self._settings.get(key) or default)
        except (TypeError, ValueError):
            value = default
        return max(MIN_MINUTES, min(MAX_MINUTES, value))

    def _pomo_clock_photo(self, side):
        """表盘素材按需要缩放（缓存，避免每次重建）。"""
        cache = getattr(self, "_pomo_clock_cache", None)
        if cache is None:
            cache = self._pomo_clock_cache = {}
        if side not in cache:
            img = Image.open(POMODORO_CLOCK_PATH).convert("RGBA")
            scale = side / float(max(img.size))
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                             Image.Resampling.LANCZOS)
            cache[side] = ImageTk.PhotoImage(img)
        return cache[side]

    def _pomo_canvas(self, side, with_buttons):
        """建一个「表盘当底、文字/按钮画在上面」的透明窗口。返回 (win, canvas, 文字id, 按钮表)。"""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=POMO_KEY)
        try:
            win.attributes("-transparentcolor", POMO_KEY)
        except Exception:
            pass
        canvas = tk.Canvas(win, width=side, height=side, bg=POMO_KEY, highlightthickness=0, bd=0)
        canvas.pack()
        photo = self._pomo_clock_photo(side)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._ph = photo
        # Canvas dimensions are pixels; a positive font size is points and gets
        # enlarged again by Tk scaling. Fit the longest supported timer in pixels.
        size=round(side*.17)
        font=tkfont.Font(root=win,family='Microsoft YaHei UI',size=-size,weight='bold')
        while font.measure('180:00')>side*.68 and size>12:
            size-=1;font.configure(size=-size)
        canvas._timer_font=font
        text = canvas.create_text(side / 2, side * 0.44, text="25:00", fill=POMO_BLUE, font=font)
        buttons = {}
        if with_buttons:
            small = ("Microsoft YaHei UI", -round(side * 0.075), "bold")
            for index, (key, label) in enumerate((("start", "开始"), ("settings", "设置"))):
                cx = side * (0.32 + index * 0.36)
                cy = side * 0.72
                w, h = side * 0.26, side * 0.16
                rect = canvas.create_rectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2,
                                               fill="#EAF3FF", outline=POMO_BLUE, width=2)
                item = canvas.create_text(cx, cy, text=label, fill=POMO_BLUE, font=small)
                for part in (rect, item):
                    canvas.tag_bind(part, "<Button-1>", lambda *a, k=key: self._pomo_button(k))
                buttons[key] = (rect, item)
            hover = tuple(part for pair in buttons.values() for part in pair)

            def _pomo_hover(event, canvas=canvas, hover=hover):
                # 鼠标形状统一在画布层处理：物品级 <Enter>/<Leave> 在透明窗口里会被 Tk 用空参数回调
                try:
                    current = canvas.find_withtag("current")
                    canvas.config(cursor="hand2" if current and current[0] in hover else "")
                except Exception:
                    pass

            canvas.bind("<Motion>", _pomo_hover, add="+")
        return win, canvas, text, buttons

    def _pomo_button(self, key):
        if key == "start":
            self._pomo_start("focus")
        else:
            self.show_pomodoro_settings()

    # ---------------- 头顶面板 ----------------
    def show_pomodoro(self, event=None):
        """点图标：露出/收起头顶面板。"""
        if self._pomo_phase is None and hasattr(self,'_workflow') and self._workflow().data.get('focus'):
            self._pomo_offer_recovery();return
        if self._pomo_phase is not None:
            win=self._pomo_float_show() if self._pomo_phase=='focus' else self._pomo_ensure_panel()
            win.attributes('-topmost',True);win.lift();return
        win = self._pomo_panel
        if win is not None and win.winfo_exists():
            self._pomo_hide_panel()
            return
        self._pomo_ensure_panel()

    def _pomo_hide_panel(self):
        if getattr(self,'_pomo_outside_id',None):
            try:self.root.after_cancel(self._pomo_outside_id)
            except tk.TclError:pass
            self._pomo_outside_id=None
        win = self._pomo_panel
        self._pomo_panel = None
        self._pomo_panel_canvas = None
        self._pomo_panel_text = None
        if win is not None:
            try:
                self._stop_follow(win)
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def _pomo_ensure_panel(self):
        win = self._pomo_panel
        if win is not None and win.winfo_exists():
            return win
        win, canvas, text, buttons = self._pomo_canvas(PANEL_CLOCK, with_buttons=True)
        win.bind("<Escape>", lambda *a: self._pomo_hide_panel() if self._pomo_phase is None else self._pomo_ask_stop())
        self._pomo_panel = win
        self._pomo_panel_canvas = canvas
        self._pomo_panel_text = text
        win.update_idletasks()
        self._place_bubble(win)          # 贴桌宠头顶
        self._start_follow(win)
        win.deiconify()
        win.lift()
        self._pomo_refresh_text()
        # Wait for release of the click that opened it, then watch new presses.
        self._pomo_pointer_down=True
        self._pomo_outside_id=self.root.after(80,lambda:self._pomo_poll_outside(win))
        return win

    def _pomo_outside_press(self,x,y):
        """Only the idle chooser dismisses. A running countdown is persistent."""
        if self._pomo_phase is not None:return False
        for window in (self._pomo_panel,getattr(self,'_pomo_settings_win',None)):
            if window is not None and window.winfo_exists():
                if window.winfo_rootx()<=x<window.winfo_rootx()+window.winfo_width() and window.winfo_rooty()<=y<window.winfo_rooty()+window.winfo_height():
                    return False
        self._pomo_hide_panel();return True

    def _pomo_poll_outside(self,win):
        self._pomo_outside_id=None
        if self._pomo_panel is not win or not win.winfo_exists():return
        if self._pomo_phase is not None:return
        try:
            import ctypes
            down=any(ctypes.windll.user32.GetAsyncKeyState(key)&0x8000 for key in (0x01,0x02))
            if down and not self._pomo_pointer_down:
                x,y=win.winfo_pointerxy()
                if self._pomo_outside_press(x,y):return
            self._pomo_pointer_down=down
        except (AttributeError,OSError,tk.TclError):pass
        self._pomo_outside_id=self.root.after(40,lambda:self._pomo_poll_outside(win))

    def _pomo_refresh_text(self):
        label = self._pomo_mmss(self._pomo_left())
        for canvas, item in ((getattr(self, "_pomo_panel_canvas", None), self._pomo_panel_text),
                             (getattr(self, "_pomo_float_canvas", None), self._pomo_float_text)):
            if canvas is None or item is None:
                continue
            try:
                canvas.itemconfig(item, text=label)
            except Exception:
                pass

    def _pomo_left(self):
        if self._pomo_phase is None:
            return self._pomo_focus * 60
        return max(0.0, self._pomo_end_at - time.monotonic())

    @staticmethod
    def _pomo_mmss(seconds):
        seconds = max(0, int(round(seconds)))
        return "%02d:%02d" % (seconds // 60, seconds % 60)

    # ---------------- 设置窗口 ----------------
    def show_pomodoro_settings(self, event=None):
        existing=getattr(self,'_pomo_settings_win',None)
        if existing is not None and existing.winfo_exists():existing.lift();return existing
        win = tk.Toplevel(self.root)
        self._pomo_settings_win=win
        win.title("番茄钟设置")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        page_header(win,'番茄钟设置').pack(fill='x')
        body = tk.Frame(win, bg="#F3F3F0")
        body.pack(fill='x',padx=PAGE_X,pady=(0,14))
        focus = tk.IntVar(value=self._pomo_focus)
        rest = tk.IntVar(value=self._pomo_break)

        def row(index, label, var):
            tk.Label(body, text=label, bg="#F3F3F0", fg=INK,
                     font=("Microsoft YaHei UI", 10)).grid(row=index, column=0, sticky="w", pady=6)
            tk.Spinbox(body, from_=MIN_MINUTES, to=MAX_MINUTES, textvariable=var, width=6).grid(
                row=index, column=1, sticky="w", padx=(10, 0))
            tk.Label(body, text="分钟", bg="#F3F3F0", fg="#697780",
                     font=("Microsoft YaHei UI", 10)).grid(row=index, column=2, sticky="w", padx=(4, 0))

        row(0, "倒计时时间", focus)
        row(1, "休息时间", rest)

        def save():
            try:
                self._pomo_focus = max(MIN_MINUTES, min(MAX_MINUTES, int(focus.get())))
                self._pomo_break = max(MIN_MINUTES, min(MAX_MINUTES, int(rest.get())))
            except Exception:
                pass
            self._save_settings()
            if self._pomo_phase is None:
                self._pomo_refresh_text()
            win.destroy()

        foot = tk.Frame(win, bg="#F3F3F0")
        foot.pack(fill="x", padx=18, pady=(0, 14))
        tk.Button(foot, text="保存", width=8, command=save).pack(side="right")
        tk.Button(foot, text="取消", width=8, command=win.destroy).pack(side="right", padx=8)
        win.bind("<Escape>", lambda *a: win.destroy())
        win.update_idletasks()
        self._place_dialog(win, max(320,win.winfo_reqwidth()), win.winfo_reqheight())
        win.lift()
        return win

    # ---------------- 开始 / 结束 ----------------
    def _pomo_start(self, phase="focus",resume_seconds=None):
        if hasattr(self,'_workflow') and resume_seconds is None:
            if self._workflow().data.get('focus'):
                if self._pomo_phase:self._pomo_checkpoint()
                self._workflow().finish('切换阶段')
            self._workflow().begin(phase,(self._pomo_focus if phase=='focus' else self._pomo_break)*60,
                                   getattr(self,'_pomo_linked_todo',None))
        self._pomo_phase = phase
        self._pomo_pending_announce = ""
        minutes = self._pomo_focus if phase == "focus" else self._pomo_break
        self._pomo_end_at = time.monotonic() + (minutes * 60 if resume_seconds is None else resume_seconds)
        self._pomo_last_tick=time.monotonic();self._pomo_last_saved=time.monotonic()
        self._pomo_hide_panel()
        if phase == "focus":
            self._pomo_float_show()
            try:
                self.hide()                  # 专注期间桌宠躲起来
            except Exception:
                pass
        else:
            self._pomo_float_hide()
            self._pomo_ensure_panel()
        self._pomo_refresh_text()
        self._pomo_schedule()
        try:
            message=('已恢复'+('专注' if phase=='focus' else '休息')+'，还剩 '+self._pomo_mmss(resume_seconds)+'。' if resume_seconds is not None
                     else "番茄钟开始啦，%d 分钟后叫你休息。" % minutes if phase=='focus' else '开始休息，%d 分钟。' % minutes)
            self.say(message, source="番茄钟")
        except Exception:
            pass

    def _pomo_stop(self, message=""):
        if hasattr(self,'_workflow'):
            self._pomo_checkpoint();self._workflow().finish('主动结束')
        self._pomo_linked_todo=None
        self._pomo_phase = None
        self._pomo_pending_announce = ""
        self._pomo_cancel_tick()
        self._pomo_cancel_game_check()
        self._pomo_float_hide()
        self._pomo_hide_panel()
        if message:
            try:
                self.say(message, source="番茄钟")
            except Exception:
                pass

    def _pomo_ask_stop(self):
        """右键提前结束：先确认一下。"""
        try:
            ok = messagebox.askyesno("番茄钟", "要提前结束这次番茄钟吗？", parent=self.pet)
        except Exception:
            ok = True
        if ok:
            self._pomo_stop("番茄钟先停掉了。")

    def _pomo_schedule(self):
        self._pomo_cancel_tick()
        if self._pomo_phase is None:
            return
        try:
            self._pomo_after = self.root.after(TICK_MS, self._pomo_tick)
        except Exception:
            self._pomo_after = None

    def _pomo_cancel_tick(self):
        if self._pomo_after is not None:
            try:
                self.root.after_cancel(self._pomo_after)
            except Exception:
                pass
            self._pomo_after = None

    def _pomo_tick(self):
        self._pomo_after = None
        if self._pomo_phase is None:
            return
        now=time.monotonic()
        if hasattr(self,'_workflow') and now-getattr(self,'_pomo_last_tick',now)>30:
            self._pomo_phase=None;self._pomo_float_hide();self._pomo_hide_panel()
            self._pomo_offer_recovery();return
        self._pomo_last_tick=now
        if hasattr(self,'_workflow') and now-getattr(self,'_pomo_last_saved',0)>=5:
            self._pomo_checkpoint();self._pomo_last_saved=now
        if self._pomo_end_at - time.monotonic() <= 0:
            self._pomo_finish_phase()
            return
        self._pomo_refresh_text()
        self._pomo_schedule()

    def _pomo_finish_phase(self):
        completed=None
        if hasattr(self,'_workflow'):
            self._workflow().checkpoint(0);completed=self._workflow().finish('倒计时结束')
        if self._pomo_phase == "focus":
            self._pomo_phase = "break"
            self._pomo_end_at = time.monotonic() + self._pomo_break * 60
            if hasattr(self,'_workflow'):
                self._workflow().begin('break',self._pomo_break*60,getattr(self,'_pomo_linked_todo',None))
                self.root.after(500,lambda:self._pomo_finished_actions(completed))
            if self._pomo_game_running():
                # 正在打游戏：先不弹出来打扰，等退出游戏再播报（浮动番茄钟继续显示休息倒计时）
                self._pomo_pending_announce = "到休息时间了。"
                self._pomo_float_show()
                self._pomo_game_check_schedule()
            else:
                self._pomo_return_to_pet("到休息时间了。")
        else:
            self._pomo_phase = None
            self._pomo_cancel_tick()
            self._pomo_return_to_pet("休息结束，继续加油。")
            return
        self._pomo_refresh_text()
        self._pomo_schedule()

    def _pomo_return_to_pet(self, message):
        """把番茄钟收回桌宠头顶，桌宠重新出现并播报。"""
        self._pomo_float_hide()
        try:
            if not self.visible:
                self.restore()
        except Exception:
            pass
        self._pomo_ensure_panel()
        self._pomo_refresh_text()
        if message:
            try:
                self.say(message, source="番茄钟")
            except Exception:
                pass

    # ---------------- 浮动番茄钟（可拖动） ----------------
    def _pomo_float_show(self):
        win = self._pomo_float
        if win is not None and win.winfo_exists():
            try:
                win.attributes('-topmost',True);win.deiconify(); win.lift()
            except Exception:
                pass
            return win
        win, canvas, text, _buttons = self._pomo_canvas(FLOAT_CLOCK, with_buttons=False)
        canvas.configure(cursor="fleur")
        canvas.bind("<ButtonPress-1>", self._pomo_drag_start)
        canvas.bind("<B1-Motion>", self._pomo_drag_move)
        canvas.bind("<ButtonRelease-1>", self._pomo_drag_end)
        canvas.bind("<Button-3>", lambda *a: self._pomo_ask_stop())
        self._pomo_float = win
        self._pomo_float_canvas = canvas
        self._pomo_float_text = text
        win.update_idletasks()
        self._pomo_float_place()
        win.deiconify()
        win.lift()
        return win

    def _pomo_float_place(self):
        """默认摆在屏幕左下角（任务栏上方）；拖动过就按上次的位置。"""
        win = self._pomo_float
        if win is None:
            return
        try:
            if self._pomo_float_geo:
                win.geometry(self._pomo_float_geo)
                return
            left, top, right, bottom = self._screen_bounds()
            x = left + FLOAT_MARGIN
            y = bottom - win.winfo_reqheight() - FLOAT_MARGIN
            win.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    def _pomo_float_hide(self):
        win = self._pomo_float
        self._pomo_float = None
        self._pomo_float_canvas = None
        self._pomo_float_text = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _pomo_drag_start(self, event):
        win = self._pomo_float
        if win is None:
            return
        self._pomo_drag = (event.x_root - win.winfo_rootx(), event.y_root - win.winfo_rooty())

    def _pomo_drag_move(self, event):
        win = self._pomo_float
        if win is None or self._pomo_drag is None:
            return
        dx, dy = self._pomo_drag
        win.geometry("+%d+%d" % (event.x_root - dx, event.y_root - dy))

    def _pomo_drag_end(self, event):
        win = self._pomo_float
        self._pomo_drag = None
        if win is None:
            return
        try:
            self._pomo_float_geo = "+%d+%d" % (win.winfo_rootx(), win.winfo_rooty())
        except Exception:
            pass

    # ---------------- 游戏检测 ----------------
    def _pomo_game_running(self):
        """前台是不是游戏。名字不认识且占满屏幕时先按游戏处理，同时后台静默查一次。"""
        try:
            import quiet_mode
            from pet import get_foreground_app
            title, exe = get_foreground_app()
            name = (exe or "").strip().lower()
            if name in quiet_mode.GAME_EXES:
                return True
            if not name or name in quiet_mode.SHELL_EXES:
                return False
            if not quiet_mode.foreground_is_fullscreen():
                return False
            if name in GAME_CACHE:
                return GAME_CACHE[name]
            if name not in self._pomo_game_asked:
                self._pomo_game_asked.add(name)
                threading.Thread(target=self._pomo_classify_game, args=(name, title), daemon=True).start()
            return True      # 结论出来之前先安静点，别打扰
        except Exception:
            return False

    def _pomo_classify_game(self, name, title):
        """静默搜一下这个程序是什么，把「是不是游戏」记下来（不打扰用户）。"""
        try:
            import web_search
            import pet as engine
            query = ((title or "").strip() + " " + name + " 是什么程序").strip()
            cache_file = os.path.join(engine.DATA_DIR, "pomodoro-games.json")
            found = web_search.search_cached(query, cache_file, ttl=7 * 24 * 3600)
            text = " ".join(str(row.get("title", "")) + " " + str(row.get("snippet", ""))
                            for row in (found.get("results") or []))
            keywords = ("游戏", "网游", "手游", "单机", "Steam", "steam", "game", "Game", "电竞")
            hits = sum(1 for word in keywords if word in text)
            GAME_CACHE[name] = hits >= 2
        except Exception:
            GAME_CACHE[name] = True      # 查不到就先当游戏，宁可安静
        finally:
            try:
                self._ui(lambda: self._pomo_check_pending())
            except Exception:
                pass

    def _pomo_check_pending(self):
        if not self._pomo_pending_announce:
            return
        if self._pomo_game_running():
            self._pomo_game_check_schedule()
            return
        message, self._pomo_pending_announce = self._pomo_pending_announce, ""
        self._pomo_cancel_game_check()
        self._pomo_return_to_pet(message)

    def _pomo_game_check_schedule(self):
        self._pomo_cancel_game_check()
        if not self._pomo_pending_announce:
            return
        try:
            self._pomo_game_check_id = self.root.after(15000, self._pomo_game_check_tick)
        except Exception:
            self._pomo_game_check_id = None

    def _pomo_game_check_tick(self):
        self._pomo_game_check_id = None
        self._pomo_check_pending()

    def _pomo_cancel_game_check(self):
        if self._pomo_game_check_id is not None:
            try:
                self.root.after_cancel(self._pomo_game_check_id)
            except Exception:
                pass
            self._pomo_game_check_id = None
