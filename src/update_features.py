"""检查更新：菜单入口、更新确认、下载进度与重启后的更新公告。"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from app_identity import APP_VERSION
from updater import (check_latest_release, download_package, launch_swap, read_announcement,
                     read_pending_update, write_pending_update)


class UpdateFeaturesMixin:
    def _center_on_pet(self, win):
        """把窗口居中到桌宠所在的显示器（不是主屏），双屏分辨率不同时别跑到另一块屏上。"""
        self._place_dialog(win)

    def _update_init(self):
        if hasattr(self, "_update_info"):
            return
        self._update_info = None                    # (has_update, version, url, notes)
        self._update_mark = None
        self._update_disabled = bool(self._settings.get("update_disabled", False))
        self._update_downloading = False
        self._update_notified = False
        self._update_prog_win = None
        self._update_prog_bar = None
        self._update_prog_lbl = None
        self._update_prog_note = None

    # ---------- 检查 ----------
    def _check_update_async(self):
        self._update_init()
        if self._update_disabled:
            return
        def work():
            info = check_latest_release()
            self._ui(lambda: self._apply_update_info(info))
        threading.Thread(target=work, daemon=True).start()

    def _apply_update_info(self, info):
        self._update_init()
        self._update_info = info
        self._refresh_update_mark()
        # 检测到更新：让静香主动说一句（每个会话只说一次）
        try:
            if info and info[0] and not self._update_notified:
                self._update_notified = True
                self.say("检测到新版本 v%s，去右键菜单里更新一下吧～" % info[1])
        except Exception:
            pass

    def _refresh_update_mark(self):
        m = getattr(self, "_update_mark", None)
        if m is None:
            return
        info = getattr(self, "_update_info", None)
        try:
            if getattr(self, "_update_downloading", False):
                m.config(text="下载中…", fg="#4a6fa5")
            elif getattr(self, "_update_disabled", False):
                m.config(text="已禁用更新", fg="#8a8a8a")
            elif info and info[0]:
                m.config(text="·有更新·", fg="#c0392b")
            elif info and info[1]:
                m.config(text="已是最新版本咯~", fg="#7a7a7a")
            elif info is None:
                m.config(text="检查更新", fg="#7a7a7a")
            else:
                m.config(text="检查更新失败，可重试", fg="#c0392b")
        except Exception:
            pass

    def _add_menu_update(self, win):
        """检查更新：左键检查/更新；右键可停止或重新接收更新。"""
        row, lbl, mark = self._menu_row(win, "检查更新（v%s）" % APP_VERSION)
        try:
            mark.config(width=0)   # 「已是最新版本咯~」比固定宽度长，别被截断
        except Exception:
            pass
        self._update_mark = mark
        self._refresh_update_mark()
        for w in (row, lbl, mark):
            w.bind("<Button-1>", lambda e, ww=win: self.select_item(ww, self._on_update_click))
            w.bind("<Button-3>", lambda e, ww=win: self.select_item(ww, self._confirm_toggle_update))

    # ---------- 用户操作 ----------
    def _on_update_click(self):
        self._update_init()
        if self._update_downloading:
            self.say("正在下载更新呢，稍等一下～")
            return
        if self._update_disabled:
            self.say("更新检查已经关掉啦，想重新打开的话在「检查更新」上右键。")
            return
        info = self._update_info
        if info and info[0] and info[2]:
            self._confirm_update(info)
        else:
            self._update_info = None
            m = getattr(self, "_update_mark", None)
            if m is not None:
                try:
                    m.config(text="检查中…", fg="#7a7a7a")
                except Exception:
                    pass
            self._check_update_async()

    def _confirm_toggle_update(self):
        """右键「检查更新」：停止 / 重新接收更新的确认窗口。"""
        self._update_init()
        disable = not self._update_disabled
        try:
            win = tk.Toplevel(self.root)
            win.title("停止接收更新" if disable else "重新接收更新")
            win.attributes("-topmost", True)
            win.configure(bg="#2b2b3a")
            tk.Label(win, text=("确定要停止接收更新吗？" if disable else "要开启更新吗？"),
                     bg="#2b2b3a", fg="#e8e8f0",
                     font=("Microsoft YaHei", 12, "bold")).pack(padx=22, pady=(16, 8))
            body = ("停止接收更新后，您仍可以在更新按钮的位置上再次右键开始更新。"
                    "此设置适合有使用经验，想要自己修改程序的用户，"
                    "但更改程序后再进行更新会覆盖掉更改的内容，请谨慎选择。") if disable else \
                   ("开启更新后，程序发现新版本会自动下载并覆盖安装；"
                    "如果您自己修改过程序内容，更新会覆盖掉您的修改，请确认后再开启。")
            tk.Label(win, text=body, bg="#2b2b3a", fg="#9a9ab0", wraplength=360,
                     justify="left", anchor="w").pack(padx=22, pady=(0, 12))
            bar = tk.Frame(win, bg="#2b2b3a")
            bar.pack(pady=(0, 16))

            def do_it():
                self._update_disabled = disable
                self._settings["update_disabled"] = disable
                self._save_settings()
                if not disable:
                    self._check_update_async()
                self._refresh_update_mark()
                win.destroy()
                self.say("好，以后就不自动检查更新了。" if disable else "好，更新检查重新开起来了。")

            tk.Button(bar, text=("确定停止" if disable else "确定开启"), width=10,
                      command=do_it).pack(side="left", padx=6)
            tk.Button(bar, text="取消", width=10, command=win.destroy).pack(side="left", padx=6)
            self._center_on_pet(win)
        except Exception:
            pass

    def _confirm_update(self, info):
        has, ver, url, notes = info
        try:
            win = tk.Toplevel(self.root)
            win.title("发现新版本")
            win.attributes("-topmost", True)
            win.configure(bg="#2b2b3a")
            tk.Label(win, text="发现新版本 %s" % ver, bg="#2b2b3a", fg="#e8e8f0",
                     font=("Microsoft YaHei", 12, "bold")).pack(padx=20, pady=(14, 6))
            txt = tk.Text(win, width=54, height=12, bg="#3a3a4e", fg="#e8e8f0",
                          relief="flat", wrap="word")
            txt.insert("1.0", notes or "（这个版本没有写更新说明）")
            txt.config(state="disabled")
            txt.pack(padx=20, pady=6)
            bar = tk.Frame(win, bg="#2b2b3a")
            bar.pack(pady=(0, 14))
            tk.Button(bar, text="立即更新", width=10,
                      command=lambda: (win.destroy(), self._apply_update(info))).pack(side="left", padx=6)
            tk.Button(bar, text="取消", width=10, command=win.destroy).pack(side="left", padx=6)
            self._center_on_pet(win)
        except Exception:
            self._apply_update(info)

    def _apply_update(self, info):
        has, ver, url, notes = info
        if not url:
            self.say("这个版本没有可下载的压缩包，去仓库手动下载一下吧。")
            return
        self._update_downloading = True
        self._refresh_update_mark()
        self.say("好，我这就去下载新版本，下载好会自动重启～")
        threading.Thread(target=self._download_and_update, args=(url, ver, notes), daemon=True).start()

    # ---------- 下载 / 安装 ----------
    def _show_update_progress(self, ver):
        """下载进度窗口（无按钮，下载中不允许再点更新）。"""
        try:
            if self._update_prog_win is not None:
                return
            win = tk.Toplevel(self.root)
            win.title("正在下载更新")
            win.attributes("-topmost", True)
            win.configure(bg="#2b2b3a")
            win.resizable(False, False)
            tk.Label(win, text=("正在下载 v%s …" % ver) if ver else "正在下载更新…",
                     bg="#2b2b3a", fg="#e8e8f0",
                     font=("Microsoft YaHei", 11, "bold")).pack(padx=24, pady=(18, 8))
            bar = ttk.Progressbar(win, orient="horizontal", length=320,
                                  mode="determinate", maximum=100)
            bar.pack(padx=24, pady=6)
            lbl = tk.Label(win, text="0%", bg="#2b2b3a", fg="#9a9ab0")
            lbl.pack(pady=(0, 4))
            note = tk.Label(win, text="", bg="#2b2b3a", fg="#7f9ac0",
                            font=("Microsoft YaHei", 8))
            note.pack(pady=(0, 12))
            self._update_prog_win = win
            self._update_prog_bar = bar
            self._update_prog_lbl = lbl
            self._update_prog_note = note
            self._center_on_pet(win)
        except Exception:
            pass

    def _update_progress(self, done, total, extracting=False):
        try:
            if self._update_prog_bar is None:
                return
            if extracting:
                self._update_prog_bar["value"] = 100
                self._update_prog_lbl.config(text="正在安装…")
                return
            if total > 0:
                pct = min(100, int(done * 100 / total))
                self._update_prog_bar["value"] = pct
                self._update_prog_lbl.config(text="%d%%  （%.1f / %.1f MB）" % (pct, done / 1e6, total / 1e6))
            else:
                self._update_prog_lbl.config(text="%.1f MB" % (done / 1e6))
        except Exception:
            pass

    def _update_note(self, text):
        try:
            if self._update_prog_note is not None:
                self._update_prog_note.config(text=text)
        except Exception:
            pass

    def _close_update_progress(self):
        w = getattr(self, "_update_prog_win", None)
        self._update_prog_win = None
        self._update_prog_bar = None
        self._update_prog_lbl = None
        self._update_prog_note = None
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass

    def _download_and_update(self, url, ver="", notes=""):
        import pet as engine
        try:
            self._ui(lambda: self._show_update_progress(ver))
            tmp, src = download_package(
                url,
                on_progress=lambda d, t, ex=False: self._ui(
                    lambda: self._update_progress(d, t, ex)),
                on_note=lambda text: self._ui(lambda: self._update_note(text)))
            if getattr(sys, "frozen", False):
                restart = '"%s"' % os.path.join(engine.ROOT_DIR, "Shizuka.exe")
            else:
                restart = '"%s" "%s"' % (engine._find_pythonw(),
                                         os.path.join(engine.APP_DIR, "run_pet.py"))
            launch_swap(src, tmp, restart)
            write_pending_update(ver, notes)
            time.sleep(0.5)
            self._ui(self.quit)
        except Exception:
            self._update_downloading = False
            self._ui(self._close_update_progress)
            self._ui(self._refresh_update_mark)
            self._ui(lambda: self.say("更新失败了呢……可以到仓库手动下载新版本。"))

    def _show_update_done(self):
        """更新重启后：弹一次更新公告，然后删掉标记文件。"""
        d = read_pending_update()
        if not d:
            return
        ver = (d.get("version") or "").strip()
        notes = (d.get("notes") or "").strip()
        try:
            # 优先用随包的「更新公告.md」里该版本那一节，其次用 Release 说明
            body_text = (read_announcement(ver) or read_announcement(APP_VERSION)
                         or notes or "（这个版本没有写更新公告）")
            win = tk.Toplevel(self.root)
            win.title("更新公告")
            win.attributes("-topmost", True)
            win.configure(bg="#2b2b3a")
            tk.Label(win, text="更新公告", bg="#2b2b3a", fg="#e8e8f0",
                     font=("Microsoft YaHei", 13, "bold")).pack(padx=22, pady=(16, 2))
            tk.Label(win, text=("已更新到 v%s" % ver) if ver else "更新完成",
                     bg="#2b2b3a", fg="#9a9ab0",
                     font=("Microsoft YaHei", 9)).pack(padx=22, pady=(0, 8))
            txt = tk.Text(win, width=54, height=12, bg="#3a3a4e", fg="#e8e8f0",
                          relief="flat", wrap="word")
            txt.insert("1.0", body_text)
            txt.config(state="disabled")
            txt.pack(padx=22, pady=6)
            tk.Button(win, text="知道啦", width=10, command=win.destroy).pack(pady=(0, 16))
            self._center_on_pet(win)
        except Exception:
            pass
