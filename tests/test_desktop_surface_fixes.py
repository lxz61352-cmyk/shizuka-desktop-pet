"""Real Tk layout, idle-vs-running dismissal, and voice cancellation regressions."""
import ast
import ctypes
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pomodoro import PomodoroMixin,PANEL_CLOCK
from todo_ui import TodoUIMixin
from art_table import ArtTable
from ui_theme import install,apply
import window_art


def pet_methods(*names):
    tree=ast.parse((ROOT/'src/pet.py').read_text('utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DeskPet')
    nodes=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
    scope=dict(tk=tk,time=time,queue=queue,DPI_SCALE=1,USAGE_AWAY_MIN=5,USAGE_AWAY_MAX_MIN=60,
               bind_wheel_scroll=lambda *a:None)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'pet methods','exec'),scope)
    return scope


class Harness(PomodoroMixin,TodoUIMixin):
    def __init__(self,root):
        self.root=root;self.pet=tk.Toplevel(root);self.pet.geometry('80x80+20+20')
        self._settings={};self._pomodoro_init();self._follow={};self.visible=True
        self.todos=[];self._todo_editor_win=None
    def _todo_init(self):pass
    def show_todo_quick(self):pass
    def _todo_options(self,item):return item.get('options',{})
    def _todo_state_label(self,item):return '已完成' if item.get('done') else '未安排时间'
    def _place_dialog(self,win,width,height):win.geometry(f'{width}x{height}+120+100')
    def _move_dialog(self,win,*args):win.lift()
    def _place_bubble(self,win):win.geometry('+200+220')
    def _start_follow(self,win):pass
    def _stop_follow(self,win):pass
    def _screen_bounds(self):return (0,0,1600,1000)
    def hide(self):self.visible=False
    def say(self,*args,**kwargs):pass
    def _save_settings(self):pass
    def _usage_today(self):return {'editor.exe':7200,'browser.exe':4200,'播放器.exe':400}
    def _app_display_name(self,name):return name
    def _fmt_dur(self,value):return f'{value//60} 分钟'


for name,func in pet_methods('show_usage','_close_usage_window','_build_usage_rows').items():
    if callable(func) and name in ('show_usage','_close_usage_window','_build_usage_rows'):setattr(Harness,name,func)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *e:self.errors.append(e)
        install(self.root);self.app=Harness(self.root)
    def pump(self,seconds=.3):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.root.update();time.sleep(.01)
    def tearDown(self):
        self.app._pomo_stop();self.root.destroy();self.assertEqual(self.errors,[])
    def test_todo_rows_details_selection_tabs_and_background(self):
        self.app.todos=[dict(id='1',text='带一把雨伞',created=0,done=False,due=None,options={'category':'生活','manual_note':'放在门口'}),
                        dict(id='2',text='整理实验记录',created=1,done=True,due=None,options={'category':'研究'})]
        self.app.show_todos();self.pump()
        win=self.app._todo_win;table=self.app._todo_trees['生活']
        self.assertIsInstance(table,ArtTable);self.assertEqual(table.get_children(),('1',))
        self.assertIsNotNone(table.art)
        self.assertEqual(table.art.tobytes(),win._art_backdrop.crop(table).tobytes())
        table.selection_set('1');self.pump()
        self.assertIn('放在门口',self.app._todo_details_box.get())
        self.app._todo_notebook.select(2);self.pump()
        self.assertTrue(self.app._todo_trees['已完成'].winfo_ismapped())
        win.geometry('680x500');self.pump()
        self.assertLessEqual(self.app._todo_details_box.winfo_rooty()+self.app._todo_details_box.winfo_height(),win.winfo_rooty()+win.winfo_height())
    def test_usage_rows_are_readable_and_resize_with_window(self):
        self.app.show_usage();self.pump();win=self.app._usage_win;canvas=self.app._usage_canvas
        embedded=[i for i in canvas.find_all() if canvas.type(i)=='window'][0]
        self.assertAlmostEqual(float(canvas.itemcget(embedded,'width')),canvas.winfo_width(),delta=2)
        inner=canvas.winfo_children()[0]
        labels=[w for row in inner.winfo_children() if isinstance(row,tk.Frame) for w in row.winfo_children() if isinstance(w,tk.Label)]
        self.assertTrue(all(w.winfo_width()>60 for w in labels))
        before=canvas.winfo_width();win.geometry('960x640');self.pump()
        self.assertGreater(canvas.winfo_width(),before)
        self.assertAlmostEqual(float(canvas.itemcget(embedded,'width')),canvas.winfo_width(),delta=2)
    def test_timer_text_fits_pixels_at_large_tk_scale(self):
        self.root.tk.call('tk','scaling',2.0)
        win=self.app._pomo_ensure_panel();self.pump()
        canvas=self.app._pomo_panel_canvas
        canvas.itemconfigure(self.app._pomo_panel_text,text='180:00')
        bbox=canvas.bbox(self.app._pomo_panel_text)
        self.assertLess(bbox[2]-bbox[0],PANEL_CLOCK*.72)
        self.assertLess(canvas._timer_font.cget('size'),0)
    def test_idle_dismisses_but_started_timer_stays_topmost_and_folds_pet(self):
        win=self.app._pomo_ensure_panel();self.pump()
        self.assertFalse(self.app._pomo_outside_press(win.winfo_rootx()+10,win.winfo_rooty()+10))
        self.assertTrue(self.app._pomo_outside_press(0,0));self.assertIsNone(self.app._pomo_panel)
        self.app._pomo_start();self.pump()
        self.assertEqual(self.app._pomo_phase,'focus');self.assertFalse(self.app.visible)
        self.assertFalse(self.app._pomo_outside_press(0,0))
        self.assertTrue(self.app._pomo_float.winfo_exists())
        self.assertTrue(self.app._pomo_float.attributes('-topmost'))
        floated=self.app._pomo_float;self.app.show_pomodoro()
        self.assertIs(self.app._pomo_float,floated)
        self.app._pomo_phase='break';rest=self.app._pomo_ensure_panel();self.app.show_pomodoro()
        self.assertIs(self.app._pomo_panel,rest);self.assertTrue(rest.winfo_exists())
    def test_background_cache_and_no_idle_repaint_loop(self):
        self.app.show_todos();self.pump(.6);art=self.app._todo_win._art_backdrop
        first=art.photo
        for _ in range(10):art.schedule()
        self.pump();self.assertIs(art.photo,first)
        card=art.card
        self.assertIs(window_art.background(card,600,400),window_art.background(card,600,400))
    def test_voice_window_withdraw_and_replacement_cancel_playback(self):
        follow=pet_methods('_start_follow')['_start_follow'];seen=[]
        app=self.app
        def stop(window):
            pending=app._follow.pop(id(window),None)
            if pending:window.after_cancel(pending)
        app._stop_follow=stop
        app._voice_type_cancel=lambda:seen.append('typing stopped')
        def cancel():app._voice_active=False;seen.append('voice stopped')
        app._cancel_reply=cancel
        for action in ('withdraw','destroy'):
            win=tk.Toplevel(self.root);self.pump(.05)
            app._reply_win=win;app._voice_win=win;app._voice_active=True
            follow(app,win);getattr(win,action)();self.pump(.05)
            self.assertFalse(app._voice_active);self.assertNotIn(id(win),app._follow)
        self.assertEqual(seen.count('voice stopped'),2)


class VoiceTests(unittest.TestCase):
    def test_stop_drains_queues_stops_only_voice_and_invalidates_pending_ui(self):
        scope=pet_methods('_stop_voice_playback','_voice_ui');commands=[]
        scope['_mci_send']=commands.append
        calls=[];obj=SimpleNamespace(_conv_id=4,_voice_active=True,_tts_q=queue.Queue(),_synth_q=queue.Queue(),_ui=calls.append)
        obj._tts_q.put(('old',));obj._synth_q.put(('old',))
        scope['_voice_ui'](obj,4,lambda:commands.append('late bubble'))
        obj._conv_id=5;scope['_stop_voice_playback'](obj);calls[0]()
        self.assertEqual(commands,['stop deskpet_voice','close deskpet_voice'])
        self.assertTrue(obj._tts_q.empty() and obj._synth_q.empty());self.assertFalse(obj._voice_active)
    def test_stale_end_marker_cannot_close_current_voice(self):
        scope=pet_methods('_tts_loop');scope['_err_log']=lambda *a:None
        class Items:
            def __init__(self):self.items=iter([('end',3),('end',4)])
            def get(self):return next(self.items)
        seen=[];obj=SimpleNamespace(_conv_id=4,_synth_q=Items(),_voice_active=True,_voice_bubble_finish=lambda:None,
                                  _voice_ui=lambda conv,callback:seen.append(conv))
        scope['_tts_loop'](obj);self.assertEqual(seen,[4])
    def test_mci_playback_is_interruptible_without_wait_lock_deadlock(self):
        tree=ast.parse((ROOT/'src/pet.py').read_text('utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_mci_play')
        scope=dict(_mci_lock=lambda alias:threading.Lock(),_sound_log=lambda *a:None,time=time)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'mci','exec'),scope)
        stop=threading.Event();started=threading.Event();commands=[]
        def send(command,buf,*args):
            commands.append(command)
            if command.startswith('status'):buf.value='playing';started.set()
            return 0
        winmm=SimpleNamespace(mciSendStringW=send)
        with patch.object(ctypes,'windll',SimpleNamespace(winmm=winmm),create=True):
            thread=threading.Thread(target=lambda:scope['_mci_play']('fixture.wav','deskpet_voice',wait=True,cancel=stop.is_set))
            thread.start();self.assertTrue(started.wait(1));begin=time.monotonic();stop.set();thread.join(.3)
            self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-begin,.3)
        self.assertIn('stop deskpet_voice',commands);self.assertNotIn('play deskpet_voice wait',commands)


if __name__=='__main__':unittest.main()
