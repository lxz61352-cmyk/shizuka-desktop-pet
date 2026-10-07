"""Product branding must not break HTTP headers, local auth or old preferences."""
import ast
import ctypes
import http.client
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import updater
import chat_test_settings as settings

class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()

def check_headers(req):
    connection = http.client.HTTPConnection('example.invalid')
    connection.putrequest('GET', '/', skip_host=True, skip_accept_encoding=True)
    for name, value in req.header_items(): connection.putheader(name, value)
    return req.get_header('User-agent')

def extracted(path, names, scope):
    tree = ast.parse((ROOT / path).read_text('utf-8-sig'))
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), path, 'exec'), scope)
    return scope

class BrandContractTests(unittest.TestCase):
    def test_ui_name_is_english_while_role_identity_remains_chinese(self):
        import pet
        self.assertEqual(pet.DISPLAY_CHARACTER_NAME, 'Shizuka')
        self.assertIn('静香', pet.CHARACTER_NAME)
        from desktop_dialogue_profile import persona_core, LATEST_PROFILE
        self.assertIn('静香', persona_core(LATEST_PROFILE, pet.ACTIVE_PACK))

    def test_github_headers_reach_version_comparison(self):
        def open_request(req, **kw):
            self.assertEqual(check_headers(req), 'ShizukaDeskPet')
            return Response({'tag_name': 'v' + updater.APP_VERSION, 'assets': []})
        with patch.object(updater.urllib.request, 'urlopen', side_effect=open_request):
            result = updater.check_latest_release()
        self.assertFalse(result[0])
        self.assertEqual(result[1], updater.APP_VERSION)

    def test_mirror_headers_are_encodable_after_main_source_failure(self):
        seen = []
        def open_request(req, **kw):
            seen.append(check_headers(req))
            if len(seen) == 1: raise OSError('main source offline')
            return Response({'version': updater.APP_VERSION, 'asset': 'Shizuka-update.zip'})
        with patch.object(updater.urllib.request, 'urlopen', side_effect=open_request):
            self.assertEqual(updater.check_latest_release()[1], updater.APP_VERSION)
        self.assertEqual(seen, ['ShizukaDeskPet', 'ShizukaDeskPet'])

    def test_sync_page_token_is_accepted_and_invalid_token_rejected(self):
        scope = extracted('src/sync_client.py', {'valid'}, {'secrets': secrets, 'token': 'test-session'})
        results = []
        request = NS(server=NS(server_port=1234), headers={'Host': '127.0.0.1:1234', 'X-Shizuka-Token': 'test-session'},
                     respond=lambda status, body: results.append(status))
        self.assertTrue(scope['valid'](request))
        request.headers['X-Shizuka-Token'] = 'wrong'
        self.assertFalse(scope['valid'](request))
        self.assertEqual(results, [403])
        self.assertIn("'X-Shizuka-Token':token", (ROOT / 'src/sync_client.py').read_text('utf-8'))

    def test_old_autostart_entry_is_detected_and_replaced_without_duplicates(self):
        values = {'静香DeskPet': 'old command'}
        class Key:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        def query(key, name):
            if name not in values: raise FileNotFoundError(name)
            return values[name], 1
        def delete(key, name):
            if name not in values: raise FileNotFoundError(name)
            del values[name]
        registry = NS(HKEY_CURRENT_USER=1, REG_SZ=1, OpenKey=lambda *a: Key(), CreateKey=lambda *a: Key(),
            QueryValueEx=query, DeleteValue=delete, SetValueEx=lambda k,n,r,t,v: values.__setitem__(n,v))
        scope = extracted('src/pet.py', {'is_autostart_on', 'set_autostart'},
            {'AUTOSTART_REG': 'Run', 'AUTOSTART_NAME': 'ShizukaDeskPet', '_AUTOSTART_NAMES': ('ShizukaDeskPet','静香DeskPet'),
             'autostart_command': lambda: 'new command'})
        with patch.dict(sys.modules, winreg=registry):
            self.assertTrue(scope['is_autostart_on']())
            self.assertTrue(scope['set_autostart'](True))
            self.assertEqual(values, {'ShizukaDeskPet': 'new command'})
            self.assertTrue(scope['set_autostart'](False))
            self.assertEqual(values, {})

    def test_existing_test_app_data_directory_is_not_abandoned(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, LOCALAPPDATA=directory):
            with patch.dict(os.environ):
                os.environ.pop('SHIZUKA_CHAT_TEST_DATA_DIR', None)
                legacy = Path(directory) / '静香ChatTest'; legacy.mkdir()
                self.assertEqual(settings.data_directory(), legacy)
                current = Path(directory) / 'ShizukaChatTest'; current.mkdir()
                self.assertEqual(settings.data_directory(), current)

    def test_test_app_legacy_credential_is_read_and_both_names_are_deleted(self):
        store = settings.KeyStore(); base = 'https://example.invalid'
        current, legacy = store.targets(base)
        self.assertTrue(current.startswith('ShizukaChatTest/'))
        self.assertTrue(legacy.startswith('静香ChatTest/'))
        blob = (ctypes.c_ubyte * 8).from_buffer_copy(b'test-key')
        credential = settings.Credential(CredentialBlob=blob, CredentialBlobSize=8)
        seen, deleted = [], []
        def read(target, kind, flags, output):
            seen.append(target)
            if target == current: return False
            ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(settings.Credential)))[0] = ctypes.pointer(credential)
            return True
        api = NS(CredReadW=read, CredFree=lambda *a: None,
                 CredDeleteW=lambda target, *a: deleted.append(target) or True)
        with patch.object(store, '_api', return_value=api), patch.object(ctypes, 'get_last_error', return_value=1168):
            self.assertEqual(store.read(base), 'test-key')
            store.delete(base)
        self.assertEqual(seen, [current, legacy])
        self.assertEqual(deleted, [current, legacy])

if __name__ == '__main__': unittest.main()
