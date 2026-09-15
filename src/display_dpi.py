"""Render at native Windows pixels while retaining the previous physical size."""
import sys


def configure_display_dpi():
    if sys.platform != 'win32':
        return 96
    try:
        import ctypes
        user32=ctypes.windll.user32
        try:
            # System-aware coordinates also match the existing window-surface code.
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
        except AttributeError:
            user32.SetProcessDPIAware()
        return max(96,int(user32.GetDpiForSystem()))
    except (AttributeError,OSError,ValueError):
        return 96


def restore_position(position,saved_dpi,current_dpi):
    """Old settings were virtualized at 96 DPI; new settings record their DPI."""
    try:
        ratio=current_dpi/float(saved_dpi or 96)
        return [round(float(position[0])*ratio),round(float(position[1])*ratio)]
    except (TypeError,ValueError,ZeroDivisionError,IndexError):
        return position


DISPLAY_DPI=configure_display_dpi()
DPI_SCALE=DISPLAY_DPI/96
