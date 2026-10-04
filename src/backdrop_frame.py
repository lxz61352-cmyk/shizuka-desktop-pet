"""One proportional fit and one synchronous repaint for artwork dialogs."""
from contextlib import contextmanager
import sys
import tkinter as tk
from PIL import ImageOps


def fit_image(image, size):
    return image if image.size == size else ImageOps.fit(image, size, centering=(.5, .5))


@contextmanager
def frame_update(window):
    """Commit queued client paints without hiding or erasing the surface.

    Tk queues these image/control changes until its idle display handlers run.
    A native WM_PAINT alone only queues Tk exposes; drain Tk's display work
    before asking Windows to repaint. Never run the full/reentrant event loop.
    WM_SETREDRAW can remove WS_VISIBLE, and RDW_ERASE/RDW_FRAME can expose an
    empty client during a DWM maximize transition. Neither is needed here.
    """
    handle=None
    api=None
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            api=ctypes.WinDLL('user32', use_last_error=True)
            api.IsWindowVisible.argtypes=(wintypes.HWND,)
            api.IsWindowVisible.restype=wintypes.BOOL
            api.IsWindow.argtypes=(wintypes.HWND,)
            api.IsWindow.restype=wintypes.BOOL
            api.RedrawWindow.argtypes=(wintypes.HWND,ctypes.c_void_p,wintypes.HRGN,wintypes.UINT)
            api.RedrawWindow.restype=wintypes.BOOL
            candidate=window.winfo_id()
            if api.IsWindowVisible(candidate):handle=candidate
        except (AttributeError,OSError,tk.TclError):
            handle=None
    try:
        yield
    finally:
        if window.winfo_exists() and window.winfo_ismapped():
            window.update_idletasks()
        if handle and api.IsWindow(handle) and api.IsWindowVisible(handle):
            # INVALIDATE | NOERASE | ALLCHILDREN | UPDATENOW; client only.
            api.RedrawWindow(handle,None,None,0x1A1)
