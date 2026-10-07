"""Local daily water reminders; bounded lateness and durable deduplication."""
from datetime import datetime
from pathlib import Path
import json
import re
import threading
import time

GRACE_SECONDS = 600


def parse_times(text):
    parts = re.split(r'[，,；;\s]+', str(text).strip())
    if not parts or any(not re.fullmatch(r'(?:[01]?\d|2[0-3]):[0-5]\d', p) for p in parts):
        raise ValueError('请输入有效时间，例如 10:00, 14:00, 16:00。')
    values = sorted({int(p.split(':')[0])*60 + int(p.split(':')[1]) for p in parts})
    if len(values) > 24:
        raise ValueError('每天最多设置 24 个提醒时间。')
    return ', '.join('%02d:%02d' % divmod(v, 60) for v in values)


def due_slot(prefs, sent, now):
    if not prefs.get('water_enabled', False):return None
    current = datetime.fromtimestamp(now)
    slots = []
    for value in parse_times(prefs.get('water_times', '10:00, 14:00, 16:00')).split(', '):
        hour, minute = map(int, value.split(':'))
        due = current.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
        key = current.strftime('%Y-%m-%d') + ' ' + value
        if 0 <= now-due < GRACE_SECONDS and key not in sent:slots.append((due, key))
    return max(slots) if slots else None


class HabitRemindersMixin:
    def _water_boot(self):
        import pet
        path = Path(pet.DATA_DIR)/'water-reminder-state.json'
        self._water_sent = {}
        try:
            if path.exists():self._water_sent = json.loads(path.read_text('utf-8-sig'))
            if not isinstance(self._water_sent, dict):raise ValueError('invalid water state')
        except (ValueError, OSError):
            # Do not overwrite an unreadable deduplication file.
            self._water_state_error = True
            pet._err_log('water_reminder_state')
        self.root.after(1000, self._water_loop)

    def _water_loop(self):
        import pet
        try:self._water_tick()
        except Exception:pet._err_log('water_reminder')
        finally:
            if not getattr(self, '_quitting', False):self.root.after(15000, self._water_loop)

    def _play_water_sound(self):
        import pet
        path = getattr(self, '_experience', {}).get('water_sound', '')
        if not path:path = str(Path(pet.ASSETS_DIR)/'water-reminder.mp3')
        if path and Path(path).is_file():
            threading.Thread(target=self._play_sound_bg, args=(path,), daemon=True).start()
        else:self.play_sound()

    def _water_tick(self, now=None):
        import pet
        from sync_bridge import atomic_json
        now = time.time() if now is None else now
        if getattr(self, '_quitting', False) or getattr(self, '_water_state_error', False):return False
        prefs = getattr(self, '_experience', {})
        sent = getattr(self, '_water_sent', {})
        slot = due_slot(prefs, sent, now)
        if not slot or self._quiet_now() or self._reminder_busy():return False
        due, key = slot
        # Reserve on disk before producing sound or a bubble; restart cannot repeat it.
        recent = {k:v for k,v in sent.items() if isinstance(v, (int,float)) and now-v < 7*86400}
        recent[key] = now
        atomic_json(str(Path(pet.DATA_DIR)/'water-reminder-state.json'), recent)
        self._water_sent = recent
        text = '到喝水提醒的时间了，喝点水吧。'
        self._record_notice(text, '喝水提醒', key='water:'+key)
        if self.visible:
            self.say(text, is_reminder=True, source='喝水提醒', sound_callback=self._play_water_sound)
        elif self._should_sound(True):self._play_water_sound()
        return True
