"""Read-only window geometry and pure selection of exposed horizontal supports."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class WindowSurface:
    handle: int
    bounds: tuple
    pid: int = 0


def exposed_support(surfaces,handle,x,margin=6):
    for index,surface in enumerate(surfaces):
        if surface.handle!=handle:
            continue
        left,top,right,bottom=surface.bounds
        if not left+margin<=x<=right-margin:
            return None
        if any(l<=x<r and t<=top+2<b for l,t,r,b in (s.bounds for s in surfaces[:index])):
            return None
        return surface
    return None


def choose_support(surfaces,x,sole_y,taskbar_y):
    choices=[s for s in surfaces if sole_y-2<=s.bounds[1]<taskbar_y
             and exposed_support(surfaces,s.handle,x) is not None]
    return min(choices,key=lambda s:s.bounds[1],default=None)


def window_surfaces():
    """Front-to-back visible app frames; no titles, contents or screenshots are read."""
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL("user32",use_last_error=True)
        dwm=ctypes.WinDLL("dwmapi",use_last_error=True)
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
        user.EnumWindows.restype=wintypes.BOOL
        for name in ("IsWindowVisible","IsIconic"):
            getattr(user,name).argtypes=[wintypes.HWND]
            getattr(user,name).restype=wintypes.BOOL
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        style_fn=user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p)==8 else user.GetWindowLongW
        style_fn.argtypes=[wintypes.HWND,ctypes.c_int]
        style_fn.restype=ctypes.c_ssize_t
        dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        dwm.DwmGetWindowAttribute.restype=ctypes.c_long
        surfaces=[]
        @callback_type
        def visit(hwnd,_):
            if not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):return True
            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==os.getpid() or style_fn(hwnd,-20)&0x80:return True
            name=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,name,len(name))
            if name.value in {"Progman","WorkerW","Shell_TrayWnd","Shell_SecondaryTrayWnd"}:return True
            cloaked=wintypes.DWORD()
            if dwm.DwmGetWindowAttribute(hwnd,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value:return True
            rect=wintypes.RECT()
            # GetWindowRect uses this process's DPI coordinate space, like Tk.
            # DWM extended frame bounds are physical pixels and cannot be mixed in.
            if not user.GetWindowRect(hwnd,ctypes.byref(rect)):return True
            bounds=(rect.left,rect.top,rect.right,rect.bottom)
            if rect.right-rect.left>=120 and rect.bottom-rect.top>=100:
                surfaces.append(WindowSurface(int(hwnd),bounds,pid.value))
            return True
        user.EnumWindows(visit,0)
        return surfaces
    except (ImportError,AttributeError,OSError):
        return []
