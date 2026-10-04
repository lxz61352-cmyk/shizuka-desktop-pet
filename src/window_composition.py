"""Per-window composition policy; never changes system animation preferences."""
import sys
import tkinter as tk


def restore_opaque(window):
    """End the opening fade's layered mode for an ordinary opaque dialog.

    Tk deliberately retains WS_EX_LAYERED after setting alpha back to 1.
    Keep real transparency and all layered child editors untouched.
    """
    if sys.platform!='win32' or not getattr(window,'_opaque_composition_requested',False):return False
    try:
        if float(window.attributes('-alpha'))!=1 or window.attributes('-transparentcolor'):return False
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('user32',use_last_error=True)
        api.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
        api.GetAncestor.restype=wintypes.HWND
        api.GetWindowLongW.argtypes=(wintypes.HWND,ctypes.c_int)
        api.GetWindowLongW.restype=ctypes.c_long
        api.SetWindowLongW.argtypes=(wintypes.HWND,ctypes.c_int,ctypes.c_long)
        api.SetWindowLongW.restype=ctypes.c_long
        hwnd=api.GetAncestor(window.winfo_id(),2)
        if not hwnd:return False
        style=api.GetWindowLongW(hwnd,-20)
        if style & 0x80000:
            ctypes.set_last_error(0)
            previous=api.SetWindowLongW(hwnd,-20,style & ~0x80000)
            if not previous and ctypes.get_last_error():return False
        window._opaque_composition_handle=hwnd
        return True
    except (OSError,AttributeError,ValueError,tk.TclError):return False


def disable_transitions(hwnd):
    """Keep DWM from animating snapshots while our client surface changes size.

    https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
    """
    if sys.platform!='win32':return False
    try:
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('dwmapi')
        api.DwmSetWindowAttribute.argtypes=(wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD)
        api.DwmSetWindowAttribute.restype=ctypes.c_long
        value=wintypes.BOOL(True)
        return api.DwmSetWindowAttribute(hwnd,3,ctypes.byref(value),ctypes.sizeof(value))==0
    except (OSError,AttributeError):return False
