"""真正的逐像素透明窗口（Windows 分层窗口）。

Tk 的 `-transparentcolor` 是色键：只有「全透明 / 全不透明」两档，
素材外圈那些半透明的柔光会被糊成一圈脏边。这里绕过 Tk，直接用
WS_EX_LAYERED + UpdateLayeredWindow 把 PIL 图贴成窗口表面，alpha 原样保留。

用法：窗口必须是 overrideredirect + 先 withdraw，贴完图再 deiconify。
"""
import ctypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def set_image(win, img):
    """把 PIL(RGBA) 图贴成窗口表面，返回是否成功。窗口尺寸会跟着图走。"""
    try:
        hwnd = win.winfo_id()
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not (ex & WS_EX_LAYERED):
            # 只在还没设过的时候设：对已经是分层窗口的再调一次 SetWindowLong，
            # 会把分层属性重置掉，表面可能要等下一次 UpdateLayeredWindow 才恢复。
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        w, h = img.size
        data = bytearray(img.convert("RGBA").tobytes())
        for i in range(0, len(data), 4):
            r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            data[i] = b * a // 255          # UpdateLayeredWindow 要预乘 BGRA
            data[i + 1] = g * a // 255
            data[i + 2] = r * a // 255
            data[i + 3] = a
        screen = user32.GetDC(0)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h          # 负数 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0      # BI_RGB
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hbmp:
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(0, screen)
            return False
        ctypes.memmove(bits, bytes(data), len(data))
        old = gdi32.SelectObject(mem, hbmp)
        size = _SIZE(w, h)
        src = _POINT(0, 0)
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(hwnd, screen, None, ctypes.byref(size), mem,
                                        ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, screen)
        return bool(ok)
    except Exception:
        return False
