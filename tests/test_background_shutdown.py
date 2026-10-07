"""Shutdown and cancellation tests with real queues, no GUI/network/audio services."""
import ast
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from background_tasks import put_until_cancelled


def methods(*names,**extra):
    tree=ast.parse((ROOT/'src/pet.py').read_text('utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DeskPet')
    nodes=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
    scope=dict(queue=queue,time=time,os=os,_err_log=Mock(),_TTS_LOCK=threading.RLock(),**extra)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'pet workers','exec'),scope)
    return scope


class ShutdownTests(unittest.TestCase):
    def test_shutdown_rejects_new_ui_callbacks_and_stops_queued_callbacks(self):
        scope=methods('_ui','_poll_ui');called=[]
        app=SimpleNamespace(_ui_q=queue.Queue(),_quitting=True,root=SimpleNamespace(after=Mock()))
        app._poll_ui=scope['_poll_ui'].__get__(app)
        scope['_ui'](app,lambda:called.append('late'))
        self.assertTrue(app._ui_q.empty())
        app._ui_q.put(lambda:called.append('pending'))
        app._poll_ui()
        self.assertEqual(called,[])
        app.root.after.assert_not_called()

    def test_shutdown_from_a_callback_stops_the_remaining_batch(self):
        scope=methods('_poll_ui');called=[]
        app=SimpleNamespace(_ui_q=queue.Queue(),_quitting=False,root=SimpleNamespace(after=Mock()))
        app._poll_ui=scope['_poll_ui'].__get__(app)
        app._ui_q.put(lambda:setattr(app,'_quitting',True))
        app._ui_q.put(lambda:called.append('late'))
        app._poll_ui()
        self.assertEqual(called,[])
        app.root.after.assert_not_called()

    def test_cancellable_handoff_releases_a_blocked_producer(self):
        target=queue.Queue(maxsize=1);target.put('already queued')
        entered=threading.Event();cancel=threading.Event();result=[]
        def cancelled():entered.set();return cancel.is_set()
        thread=threading.Thread(target=lambda:result.append(put_until_cancelled(target,'old',cancelled)),daemon=True)
        thread.start();self.assertTrue(entered.wait(1));cancel.set();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(result,[False])
        self.assertEqual(target.get_nowait(),'already queued')

    def test_handoff_keeps_the_result_when_not_cancelled(self):
        target=queue.Queue(maxsize=1)
        self.assertTrue(put_until_cancelled(target,'current',lambda:False))
        self.assertEqual(target.get_nowait(),'current')

    def test_idle_speech_workers_exit_without_sentinel_messages(self):
        scope=methods('_tts_producer','_tts_loop')
        for name in ('_tts_producer','_tts_loop'):
            with self.subTest(worker=name):
                app=SimpleNamespace(_quitting=False,_tts_q=queue.Queue(),_synth_q=queue.Queue())
                thread=threading.Thread(target=scope[name],args=(app,),daemon=True)
                thread.start();app._quitting=True;thread.join(1)
                self.assertFalse(thread.is_alive())

    def test_synthesis_finishing_after_shutdown_does_not_publish_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            scope=methods('_tts_producer',DATA_DIR=folder)
            started=threading.Event();release=threading.Event()
            def synth(*args,**kwargs):
                started.set();release.wait(1);return True,'synthetic.wav',1
            app=SimpleNamespace(_quitting=False,_conv_id=1,_tts_q=queue.Queue(),_synth_q=queue.Queue(),
                                _voice_active=True,_tts_synth=synth)
            app._tts_q.put(('text','tts',1,0))
            thread=threading.Thread(target=scope['_tts_producer'],args=(app,),daemon=True)
            thread.start();self.assertTrue(started.wait(1));app._quitting=True;release.set();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertTrue(app._synth_q.empty())

    def test_shutdown_does_not_start_speech_workers(self):
        scope=methods('_tts_enqueue')
        app=SimpleNamespace(_quitting=True)
        scope['_tts_enqueue'](app,'late reply')
        self.assertFalse(hasattr(app,'_tts_q'))

    def test_stale_or_shutdown_model_job_stops_before_preparation(self):
        scope=methods('_ask_model')
        app=SimpleNamespace(_quitting=False,_conv_id=2,_should_sound=Mock())
        scope['_ask_model'](app,'obsolete',1)
        app._quitting=True
        scope['_ask_model'](app,'late',2)
        scope['_ask_model'](app,'unscoped',None)
        app._should_sound.assert_not_called()

    def test_stale_speech_does_not_wait_for_new_reply_typing(self):
        clock=SimpleNamespace(time=time.time,sleep=Mock(side_effect=AssertionError('should not wait')))
        scope=methods('_wait_voice_type_done');scope['time']=clock
        app=SimpleNamespace(_voice_type_cps=5,_voice_type_done=False,_conv_id=2)
        scope['_wait_voice_type_done'](app,10,1)
        clock.sleep.assert_not_called()

    def test_completed_reply_is_archived_but_cannot_mutate_a_new_turn(self):
        memory=SimpleNamespace(save=Mock())
        scope=methods('_post_memory',get_memory=lambda:memory)
        callbacks=[]
        app=SimpleNamespace(_conv_id=1,_quitting=False,_log_conversation=Mock(),_log_chat=Mock(),
                            _conv_state=SimpleNamespace(observe_reply=Mock()),
                            _mood=SimpleNamespace(observe_reply=Mock()),_ui=callbacks.append,
                            _refresh_memories=Mock(),_maybe_review_memory=Mock(),_shadow_tick=Mock())
        scope['_post_memory'](app,'user','completed',1)
        app._log_chat.assert_called_once_with('assistant','completed')
        self.assertEqual(len(callbacks),1)
        app._conv_id=2;callbacks[0]()
        app._conv_state.observe_reply.assert_not_called()
        app._mood.observe_reply.assert_not_called()
        app._refresh_memories.reset_mock();callbacks.clear()
        scope['_post_memory'](app,'user','older',1)
        app._refresh_memories.assert_not_called()
        self.assertEqual(callbacks,[])


if __name__=='__main__':unittest.main()
