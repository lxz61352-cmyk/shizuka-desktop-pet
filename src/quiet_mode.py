"""免打扰判定：前台是游戏或全屏程序时，静香先不说话。

判定失败一律当作「可以说话」——宁可多说一句，也不要因为探测不到就永远沉默。
"""
import ctypes
import os
from ctypes import wintypes

# 常见游戏进程名（小写）。名单只是提高命中率，真正可靠的信号是「前台窗口铺满整块屏幕」。
GAME_EXES = frozenset({
    "overwatch.exe", "cs2.exe", "csgo.exe", "valorant.exe", "valorant-win64-shipping.exe",
    "dota2.exe", "league of legends.exe", "leagueclient.exe", "riotclientservices.exe",
    "genshinimpact.exe", "yuanshen.exe", "starrail.exe", "zenlesszonezero.exe", "bh3.exe",
    "pubg.exe", "tslgame.exe", "apex_legends.exe", "r5apex.exe", "gta5.exe", "rdr2.exe",
    "eldenring.exe", "sekiro.exe", "witcher3.exe", "cyberpunk2077.exe", "hollow_knight.exe",
    "bf2042.exe", "bfv.exe", "modernwarfare.exe", "cod.exe", "rainbowsix.exe", "r6siege.exe",
    "naraka.exe", "wutheringwaves.exe", "deltaforceclient.exe", "destiny2.exe", "warframe.x64.exe",
    "ffxiv_dx11.exe", "wow.exe", "hearthstone.exe", "osu!.exe", "terraria.exe", "dst.exe",
    "stardew valley.exe", "hades.exe", "slaythespire.exe", "baldurs gate 3.exe", "bg3.exe",
})

# 桌面/任务栏这类「本来就占满屏幕」的窗口不算游戏
SHELL_EXES = frozenset({"explorer.exe", "progman.exe", "workerw.exe", "searchhost.exe", ""})

MONITOR_DEFAULTTONEAREST = 2
FULLSCREEN_TOLERANCE = 8      # 允许任务栏/边框的几像素误差


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


def foreground_is_fullscreen():
    """前台窗口是否铺满它所在的那块屏幕（全屏游戏、全屏视频都属于这种）。
    我们自己的窗口不算——桌宠偶尔会被拉到最大，那不该让静香闭嘴。"""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
        rect = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return False
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        screen = info.rcMonitor
        width = screen.right - screen.left
        height = screen.bottom - screen.top
        if width <= 0 or height <= 0:
            return False
        return (rect.right - rect.left >= width - FULLSCREEN_TOLERANCE
                and rect.bottom - rect.top >= height - FULLSCREEN_TOLERANCE
                and rect.left <= screen.left + 4 and rect.top <= screen.top + 4)
    except Exception:
        return False
    finally:
        pass


def quiet_reason(title, exe, fullscreen=False, quiet_apps=(), games=True, use_fullscreen=True):
    """该安静就返回理由（会显示在菜单里），否则返回 ''。"""
    name = (exe or "").strip().lower()
    label = (title or exe or "").strip()[:40]
    extra = {str(item).strip().lower() for item in (quiet_apps or []) if str(item).strip()}
    if name and name in extra:
        return label or exe
    if games and name and name in GAME_EXES:
        return label or exe
    if use_fullscreen and fullscreen and name not in SHELL_EXES:
        return label or exe or "全屏程序"
    return ""


def status_text(reason):
    return "正在免打扰：" + reason if reason else "没有在免打扰"
