"""Prepare normal dialogs out of sight, then fade in their settled first frame."""
import time
import tkinter as tk

# This is a failure ceiling, not a delay. Large settings pages may need several
# geometry passes for image-backed controls before they can be exposed safely.
MAX_PREPARE_SECONDS = 8.0
FADE_SECONDS = .16
SETTLE_SECONDS = .25


def prepare(window):
    window = window.winfo_toplevel()
    if getattr(window,'_qt_model_only',False):return
    if (not isinstance(window, tk.Toplevel) or getattr(window, '_opening_started', False) or window.winfo_ismapped()
            or window.overrideredirect() or getattr(window, '_compact_surface', False)):
        return
    window._opening_started = True
    try:
        opacity = float(window.attributes('-alpha'))
        window.attributes('-alpha', 0.0)
    except tk.TclError:
        return
    window._opening_pending = True
    job = None
    started = time.monotonic()
    initialized = False
    fade_started = None
    stable_layout = None
    settle_deadline = None

    def finish(reason):
        nonlocal job
        if not window._opening_pending:return
        if job is not None:window.after_cancel(job); job = None
        window._opening_pending = False
        window._opening_result = reason
        window._opening_ms = round((time.monotonic()-started)*1000, 1)
        window.attributes('-alpha', opacity)
        if opacity==1.0:
            # Fade only while opening. Ordinary resized dialogs must not keep
            # the layered wrapper that Tk leaves behind at alpha=1.
            window._opaque_composition_requested=True
            from window_composition import restore_opaque
            if restore_opaque(window):
                from backdrop_frame import frame_update
                with frame_update(window):pass

    def fade():
        nonlocal job
        job = None
        if not window.winfo_exists():return
        if not window.winfo_ismapped() or window.state() == 'withdrawn':
            finish('hidden'); return
        progress = min(1.0, (time.monotonic()-fade_started)/FADE_SECONDS)
        window._opening_debug=dict(phase='fade',progress=progress)
        if progress >= 1.0:
            finish('ready'); return
        # Only compositor opacity changes. Do not resize, move or repaint widgets.
        window.attributes('-alpha', opacity*(1-(1-progress)**3))
        job = window.after(16, fade)

    def poll():
        nonlocal job, initialized, fade_started, stable_layout, settle_deadline
        job = None
        if not window.winfo_exists():return
        # after(0), unlike after_idle, is not run by constructors that call
        # update_idletasks to measure controls midway through building a page.
        if not initialized:
            initialized = True
            if window.state() == 'withdrawn':
                finish('withdrawn'); return
            from ui_theme import apply
            apply(window)
            job = window.after(1, poll)
            return
        if not window.winfo_ismapped():
            if window.state() == 'withdrawn':finish('hidden'); return
            if time.monotonic()-started >= MAX_PREPARE_SECONDS:finish('timeout'); return
            job = window.after(16, poll); return
        backdrop = getattr(window, '_art_backdrop', None)
        if backdrop is not None:
            ready = backdrop.ready()
        else:
            ready = min(window.winfo_width(), window.winfo_height()) > 1
        window._opening_debug=dict(phase='prepare',ready=ready,
            theme_pending=bool(getattr(window,'_theme_pending',False)),
            elapsed=round(time.monotonic()-started,2))
        if ready and not getattr(window, '_theme_pending', False):
            # A busy Tk event loop may deliver the first finished frame after
            # the preparation budget. Still allow one bounded settling period;
            # never expose that frame just because its construction was slow.
            if settle_deadline is None:
                settle_deadline = time.monotonic()+SETTLE_SECONDS
            layout = (window.winfo_geometry(), backdrop.signature if backdrop is not None else None)
            if stable_layout is not None and stable_layout!=layout:
                before={str(row[0]):row[1:] for row in stable_layout[1] or ()}
                changes=[dict(widget=str(row[0]),kind=row[0].winfo_class(),before=before.get(str(row[0])),after=row[1:])
                         for row in layout[1] or () if before.get(str(row[0]))!=row[1:]]
                trace=getattr(window,'_opening_diffs',[])
                trace.append(dict(geometry=layout[0],previous_geometry=stable_layout[0],changes=changes[:5]))
                window._opening_diffs=trace[-4:]
            # Image-backed ttk styles can queue another geometry pass. Let Tk
            # finish that pass before making any part of the window visible.
            if stable_layout == layout:
                fade_started = time.monotonic()
                window._opening_prepare_ms = round((fade_started-started)*1000, 1)
                fade(); return
            stable_layout = layout
        else:
            stable_layout = None
        # A slow/missing artwork must never leave an invisible, unusable dialog.
        if time.monotonic() >= max(started+MAX_PREPARE_SECONDS, settle_deadline or 0):
            finish('timeout'); return
        job = window.after(16, poll)

    def dispose(event):
        nonlocal job
        if event.widget is not window:return
        if job is not None:window.after_cancel(job); job = None
        window._opening_pending = False

    window.bind('<Destroy>', dispose, add='+')
    job = window.after(0, poll)


def dialog_window(parent):
    from qt_forms import create_dialog
    managed=create_dialog(parent)
    if managed is not None:return managed
    """Prepare immediately, before constructors can map an unfinished dialog."""
    window = tk.Toplevel(parent)
    prepare(window)
    return window
