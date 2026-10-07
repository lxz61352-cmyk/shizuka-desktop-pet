from pathlib import Path
from datetime import datetime
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from habit_reminders import HabitRemindersMixin, parse_times, due_slot
from proactive_controls import desktop_eligible, tomorrow
from experience_settings import load, save


def stamp(hour=10, minute=0, second=0):
    return datetime(2026,10,7,hour,minute,second).timestamp()


class HabitTests(unittest.TestCase):
    def test_times_normalize_and_reject_invalid(self):
        self.assertEqual(parse_times('16:00，9:00; 16:00\n14:30'),'09:00, 14:30, 16:00')
        for value in ('','24:00','10:60','下午三点','10:00, nope'):
            with self.assertRaises(ValueError):parse_times(value)

    def test_due_window_no_backlog_and_new_day(self):
        prefs={'water_enabled':True,'water_times':'10:00, 14:00'}
        self.assertIsNone(due_slot(prefs,{},stamp(9,59,59)))
        self.assertEqual(due_slot(prefs,{},stamp())[1],'2026-10-07 10:00')
        self.assertIsNone(due_slot(prefs,{},stamp(10,10)))
        self.assertIsNone(due_slot(prefs,{'2026-10-07 10:00':stamp()},stamp(10,1)))
        self.assertIsNotNone(due_slot(prefs,{'2026-10-06 10:00':stamp()-86400},stamp()))
        self.assertIsNone(due_slot(dict(prefs,water_enabled=False),{},stamp()))

    def test_scheduler_defers_then_delivers_and_deduplicates_after_reload(self):
        import pet
        with tempfile.TemporaryDirectory() as folder, patch.object(pet,'DATA_DIR',folder):
            app=HabitRemindersMixin()
            app._experience={'water_enabled':True,'water_times':'10:00'}
            app.visible=True;app._quiet_now=Mock(return_value=True)
            app._reminder_busy=Mock(return_value=False);app.say=Mock(return_value=True)
            app._record_notice=Mock();app.root=Mock()
            app._water_boot()
            self.assertFalse(app._water_tick(stamp()))
            app._quiet_now.return_value=False;app._reminder_busy.return_value=True
            self.assertFalse(app._water_tick(stamp()))
            app._reminder_busy.return_value=False
            self.assertTrue(app._water_tick(stamp(10,1)))
            self.assertEqual(app.say.call_args.kwargs['source'],'喝水提醒')
            self.assertEqual(app.say.call_args.kwargs['sound_callback'],app._play_water_sound)
            app._water_boot()
            self.assertFalse(app._water_tick(stamp(10,2)))
            self.assertEqual(app.say.call_count,1)
            self.assertIn('2026-10-07 10:00',json.loads((Path(folder)/'water-reminder-state.json').read_text('utf-8')))

    def test_folded_sound_switch_and_notification(self):
        import pet
        for sound in (True,False):
            with tempfile.TemporaryDirectory() as folder, patch.object(pet,'DATA_DIR',folder):
                app=HabitRemindersMixin();app.visible=False
                app._experience={'water_enabled':True,'water_times':'10:00'}
                app._quiet_now=Mock(return_value=False);app._reminder_busy=Mock(return_value=False)
                app._should_sound=Mock(return_value=sound);app._play_water_sound=Mock()
                app._record_notice=Mock();app.say=Mock()
                self.assertTrue(app._water_tick(stamp()))
                self.assertEqual(app._play_water_sound.call_count,int(sound))
                app.say.assert_not_called();app._record_notice.assert_called_once()

    def test_preferences_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            value=load(folder);self.assertFalse(value['water_enabled'])
            value.update(water_enabled=True,water_times='8:30, 16:00',desktop_start=1320,desktop_end=360)
            save(folder,value);restored=load(folder)
            self.assertEqual(restored['water_times'],'08:30, 16:00')
            self.assertTrue(restored['water_enabled'])

    def test_visible_reminder_uses_only_custom_sound_and_habit_log_kind(self):
        import pet
        app=pet.DeskPet.__new__(pet.DeskPet)
        app._voice_on=False;app._log_chat=Mock();app._should_sound=Mock(return_value=True)
        app._ui=lambda callback:callback()
        app._play_reply=Mock();app.play_sound=Mock();water_sound=Mock()
        self.assertTrue(app.say('喝点水吧。',is_reminder=True,source='喝水提醒',sound_callback=water_sound))
        water_sound.assert_called_once();app.play_sound.assert_not_called()
        self.assertEqual(app._log_chat.call_args.kwargs['kind'],'habit_reminder')
        app._should_sound.return_value=False
        app.say('喝点水吧。',is_reminder=True,source='喝水提醒',sound_callback=water_sound)
        self.assertEqual(water_sound.call_count,1)

    def test_bundled_notice14_routes_to_background_audio_player(self):
        import pet
        app=HabitRemindersMixin();app._play_sound_bg=Mock();app.play_sound=Mock()
        with patch('habit_reminders.threading.Thread') as worker:
            app._play_water_sound()
            self.assertEqual(Path(worker.call_args.kwargs['args'][0]),Path(pet.ASSETS_DIR)/'water-reminder.mp3')
            worker.return_value.start.assert_called_once()
            app.play_sound.assert_not_called()

    def test_corrupt_state_fails_closed(self):
        import pet
        with tempfile.TemporaryDirectory() as folder, patch.object(pet,'DATA_DIR',folder),patch.object(pet,'_err_log'):
            path=Path(folder)/'water-reminder-state.json';path.write_text('broken')
            app=HabitRemindersMixin();app.root=Mock();app._water_boot()
            self.assertFalse(app._water_tick(stamp()))
            self.assertEqual(path.read_text(),'broken')


class ProactiveControlsTests(unittest.TestCase):
    def test_weixin_guard_rechecks_quiet_and_executing_tasks(self):
        from weixin_ui import WeixinMixin
        import time
        app=WeixinMixin();app._quiet_now=Mock(return_value=False)
        app._last_user_dialogue_at=time.monotonic()-7200
        app._computer_state={'executing':True}
        self.assertFalse(app._weixin_proactive_allowed())
        app._computer_state={}
        self.assertTrue(app._weixin_proactive_allowed())
        app._quiet_now.return_value=True
        self.assertFalse(app._weixin_proactive_allowed())

    def test_allowed_hours_and_cross_midnight(self):
        prefs={'desktop_start':1320,'desktop_end':360}
        self.assertFalse(desktop_eligible(prefs,[],stamp())[0])
        self.assertTrue(desktop_eligible(prefs,[],stamp(23))[0])
        self.assertTrue(desktop_eligible(prefs,[],stamp(5))[0])
        self.assertFalse(desktop_eligible(prefs,[],stamp(6))[0])

    def test_pause_expires_at_next_local_day(self):
        until=tomorrow(stamp())
        self.assertEqual(datetime.fromtimestamp(until),datetime(2026,10,8))
        prefs={'desktop_paused_until':until}
        self.assertFalse(desktop_eligible(prefs,[],stamp())[0])
        self.assertTrue(desktop_eligible(prefs,[],until)[0])

    def test_recent_chat_and_unanswered_message_gate(self):
        rows=[{'role':'assistant','kind':'proactive','created':stamp()-4*3600}]
        self.assertFalse(desktop_eligible({},rows,stamp())[0])
        rows.append({'role':'user','kind':'weixin','created':stamp()-29*60})
        self.assertFalse(desktop_eligible({},rows,stamp())[0])
        self.assertTrue(desktop_eligible({'desktop_after_chat':10},rows,stamp())[0])

    def test_water_does_not_count_as_unanswered_casual_chat(self):
        self.assertTrue(desktop_eligible({},[{'role':'assistant','kind':'habit_reminder','created':stamp()}],stamp())[0])


if __name__=='__main__':unittest.main()
