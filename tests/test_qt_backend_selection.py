import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import qt_window_bridge


class BackendSelectionTests(unittest.TestCase):
    def test_packaged_custom_data_keeps_shared_windows(self):
        with patch.dict(os.environ, {'SHIZUKA_DATA_DIR': 'fixture-data', 'SHIZUKA_WINDOW_BACKEND': ''}), patch.object(sys, 'frozen', True, create=True), patch.dict(sys.modules, {'pet': SimpleNamespace(ROOT_DIR='fixture-root')}), patch.object(Path, 'is_file', return_value=True):
            self.assertTrue(qt_window_bridge.enabled())

    def test_source_fixture_retains_legacy_windows(self):
        with patch.dict(os.environ, {'SHIZUKA_DATA_DIR': 'fixture-data', 'SHIZUKA_WINDOW_BACKEND': ''}), patch.object(sys, 'frozen', False, create=True):
            self.assertFalse(qt_window_bridge.enabled())

    def test_explicit_backend_preference_wins(self):
        for value, expected in [('qt', True), ('tk', False)]:
            with self.subTest(value=value), patch.dict(os.environ, {'SHIZUKA_DATA_DIR': 'fixture-data', 'SHIZUKA_WINDOW_BACKEND': value}):
                self.assertEqual(qt_window_bridge.enabled(), expected)
