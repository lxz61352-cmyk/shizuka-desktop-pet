"""Capture both actual channel request paths without a network or real messages."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tools')]
import desktop_dialogue_profile as profile


class DesktopProfileTests(unittest.TestCase):
    def test_explicit_release_selection_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SHIZUKA_DIALOGUE_PROFILE', None)
            self.assertEqual(profile.load(folder), '')
            path = Path(folder)/profile.FILE_NAME
            path.write_text(json.dumps({'profile':profile.PROFILE}), encoding='utf-8')
            self.assertEqual(profile.load(folder), profile.PROFILE)
            os.environ['SHIZUKA_DIALOGUE_PROFILE'] = 'legacy'
            self.assertEqual(profile.load(folder), '')
            os.environ['SHIZUKA_DIALOGUE_PROFILE'] = 'unknown'
            with self.assertRaises(ValueError): profile.load(folder)

    def test_both_channels_use_trial_card_without_coarse_frame(self):
        import pet
        import run_shizuka_phase_s0 as s0
        import run_shizuka_phase_s1 as s1
        from chat_test_core import compile_persona
        from enhanced_dialogue import output_blocks
        text = '吃个饭而已，别老拿复习的事情套我了。'
        recorder = []
        Capture = s0._build_capture_class(pet)
        with tempfile.TemporaryDirectory() as folder, patch.multiple(
                pet, DESKTOP_DIALOGUE_PROFILE=profile.PROFILE, ENHANCED_MODE=True,
                DIALOGUE_V2=False, TONE_MODE=0, DATA_DIR=folder,
                get_client=lambda:s0._Client(recorder), api_model=lambda:'fake',
                has_api_key=lambda:True), patch('socket.socket.connect', side_effect=AssertionError('offline')):
            capture = Capture(recorder, history=[], time_block='', memory_block='')
            capture._ask_model(text)
            wx = s1._run_weixin(text, False)
        card = compile_persona('s31-r')[0]
        block = output_blocks(text, [], natural_chat=True, outer_variant='no_frame')[0]
        for request in (recorder[-1], wx):
            system = request['messages'][0]['content']
            self.assertTrue(system.startswith(card+'\n\n'))
            self.assertIn(block, system)
            self.assertNotIn('【本轮交互事实】', system)
            self.assertNotIn('【本轮行动约束】', system)
            self.assertNotIn('一两句说清', system)
            self.assertEqual(request['messages'][-1], {'role':'user','content':text})
        from enhanced_dialogue import compose_messages
        self.assertEqual(wx['messages'],compose_messages(card,text,[],
            capabilities='当前通过微信文字交流。文件操作需使用 /电脑 指令；没有执行回执不声称已完成。'))

    def test_timeline_preserves_times_and_feedback_without_current_duplicate(self):
        import pet
        from memory_maintenance import MemoryFeaturesMixin
        from datetime import datetime
        rows = [dict(id=1, role='user', text='别老拿复习的事情套我了', kind='weixin', created=1000000001),
                dict(id=2, role='assistant', text='好啦。', kind='weixin', created=1000000031),
                dict(id=3, role='user', text='这锅土豆还挺好吃的', kind='weixin', created=1000000901)]
        obj = SimpleNamespace(_chat_log=rows, _chat_lock=threading.RLock(), _settings={})
        with patch.object(pet, 'DESKTOP_DIALOGUE_PROFILE', profile.PROFILE):
            history, block = MemoryFeaturesMixin._recent_messages(obj, rows[-1]['text'], 'weixin')
        self.assertEqual(len(history), 2)
        from chat_timeline import CONTRACT
        data = json.loads(block[len(CONTRACT)+1:])
        self.assertEqual(data['messages'][1]['gap_seconds'], 30)
        self.assertEqual(datetime.fromisoformat(data['messages'][0]['at']).timestamp(), 1000000001)
        self.assertIn(0, data['feedback_user_indices'])
        self.assertNotIn(rows[-1]['text'], str(history))


if __name__ == '__main__': unittest.main()
