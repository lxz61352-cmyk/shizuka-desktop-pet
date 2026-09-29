"""Isolated public preferences and Windows credential storage for the test app."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path

from chat_test_core import DEFAULT_CONFIG, validate_config


def data_directory():
    override = os.environ.get('SHIZUKA_CHAT_TEST_DATA_DIR')
    return Path(override) if override else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ShizukaChatTest'


def load_config(directory):
    try:
        return validate_config(json.loads((Path(directory) / 'connection.json').read_text('utf-8')))
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(DEFAULT_CONFIG)


def save_config(directory, config):
    public = validate_config(config)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'connection.json'
    temp = directory / 'connection.json.tmp'
    temp.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def load_natural_chat(directory, default=False):
    try:
        value = json.loads((Path(directory) / 'dialogue-mode.json').read_text('utf-8')).get('natural_chat')
        return value if type(value) is bool else default
    except (OSError, ValueError, TypeError, AttributeError):
        return default


def save_natural_chat(directory, enabled):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'dialogue-mode.json'
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps({'natural_chat': enabled is True}), encoding='utf-8')
    temp.replace(path)


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class KeyStore:
    """No fallback to the desktop pet's credentials, and no plaintext key files."""
    def target(self, base):
        return 'ShizukaChatTest/' + hashlib.sha256(base.encode('utf-8')).hexdigest()[:20]

    def _api(self):
        if os.name != 'nt':
            raise OSError('此平台不支持 Windows 凭据管理器。')
        api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def read(self, base):
        api = self._api()
        pointer = ctypes.POINTER(Credential)()
        if not api.CredReadW(self.target(base), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return ''
            raise OSError('无法读取本机测试凭据。')
        try:
            cred = pointer.contents
            return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode('utf-8')
        finally:
            api.CredFree(pointer)

    def write(self, base, key):
        blob = key.encode('utf-8')
        if not blob or len(blob) > 2500:
            raise ValueError('测试 key 长度无效。')
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = Credential(Type=1, TargetName=self.target(base), CredentialBlobSize=len(blob),
                          CredentialBlob=buffer, Persist=2, UserName='ShizukaChatTest')
        if not self._api().CredWriteW(ctypes.byref(cred), 0):
            raise OSError('无法保存测试凭据；可以取消记住 key，仅本次使用。')

    def delete(self, base):
        if not self._api().CredDeleteW(self.target(base), 1, 0) and ctypes.get_last_error() != 1168:
            raise OSError('无法删除已存测试凭据。')
