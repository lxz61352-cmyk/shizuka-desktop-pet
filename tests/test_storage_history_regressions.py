"""Storage failure and history projection regressions without Tk or model calls."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from qt_window_bridge import Bridge


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(id=str(i), role='user', text=str(i), kind='chat') for i in range(3)]
        self.notices = []
        self.bridge = Bridge.__new__(Bridge)
        self.bridge.app = SimpleNamespace(
            _chat_lock=threading.RLock(), _chat_log=self.rows,
            _workflow=lambda: SimpleNamespace(notices=lambda: deepcopy(self.notices)))
        self.bridge.last_history = None
        self.bridge.history_ids = []
        self.received = []
        self.packets = []
        def send(packet):
            self.packets.append(deepcopy(packet))
            self.received = self.received[:packet['offset']] + deepcopy(packet['rows'])
        self.bridge.send = send
        self.bridge.publish_history()

    def test_older_edit_and_append_reach_receiver(self):
        self.rows[0]['text'] = 'corrected'
        self.rows.append(dict(id='3', role='assistant', text='next', kind='chat'))
        self.bridge.publish_history()
        self.assertEqual(self.received, self.rows)
        self.assertEqual(self.packets[-1]['offset'], 0)

    def test_metadata_edit_reaches_receiver(self):
        self.rows[1]['created'] = 123
        self.bridge.publish_history()
        self.assertEqual(self.received, self.rows)
        self.assertEqual(self.packets[-1]['offset'], 1)

    def test_append_delete_reorder_and_clear(self):
        self.rows.append(dict(id='3', role='assistant', text='next', kind='chat'))
        self.bridge.publish_history()
        self.assertEqual(self.packets[-1]['offset'], 3)
        self.assertEqual(self.received, self.rows)
        self.rows.pop()
        self.bridge.publish_history()
        self.assertEqual(self.received, self.rows)
        self.rows.reverse()
        self.bridge.publish_history()
        self.assertEqual(self.received, self.rows)
        self.rows.clear()
        self.bridge.publish_history()
        self.assertEqual(self.received, [])

    def test_unchanged_notices_and_force(self):
        self.bridge.publish_history()
        self.assertEqual(len(self.packets), 1)
        self.notices.append(dict(id='n1', text='notice', source='todo', read=False))
        self.bridge.publish_history()
        self.notices[0]['source'] = 'updated'
        self.bridge.publish_history()
        self.assertEqual(self.packets[-1]['notices'][0]['source'], 'updated')
        self.assertEqual(self.received, self.rows)
        self.bridge.publish_history(force=True)
        self.assertEqual(self.packets[-1]['offset'], 0)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        # Execute the real method without importing pet's optional GUI dependencies.
        tree = ast.parse((ROOT / 'src/pet.py').read_text('utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeskPet')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_save_settings')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings.json'
        self.log = Mock()
        scope = dict(SETTINGS_FILE=str(self.path), _FILE_LOCK=threading.RLock(),
                     _err_log=self.log, DISPLAY_DPI=96, USAGE_AWAY_MIN=5,
                     DEFAULT_API_BASE='unused', DEFAULT_API_MODEL='unused', MUSIC_VOLUME=50,
                     gsv_dir=lambda: '', api_mode=lambda: 'chat')
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'pet settings', 'exec'), scope)
        self.save = scope['_save_settings']
        self.app = SimpleNamespace(
            pet=SimpleNamespace(winfo_x=lambda: 12, winfo_y=lambda: 34),
            _settings=dict(api_mode='responses', api_base='https://example.invalid', api_model='fixture'),
            _character_pack=None, _animation_on=True, _ambient_actions_on=True,
            _land_on_windows=False, _sound_mode='todo', _clip_on=True, _translate_on=True,
            _greeting_on=True, _summary_on=True, _speed='medium', _idle_minutes=5, _scale=1.0)

    def test_save_preserves_selected_mode_and_position(self):
        self.save(self.app)
        stored = json.loads(self.path.read_text('utf-8'))
        self.assertEqual(stored['api_mode'], 'responses')
        self.assertEqual(stored['pos'], [12, 34])
        self.log.assert_not_called()

    def test_replace_failure_preserves_original_and_logs(self):
        original = b'{"api_mode":"chat"}'
        self.path.write_bytes(original)
        with patch('sync_bridge.os.replace', side_effect=OSError('simulated failure')):
            self.save(self.app)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('.sync-write-*.tmp')), [])
        self.log.assert_called_once_with('save_settings')


if __name__ == '__main__':
    unittest.main()
