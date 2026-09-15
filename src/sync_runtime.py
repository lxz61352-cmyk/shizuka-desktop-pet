"""Opt-in app integration. Configuration is separate from pet preferences."""
import json
from pathlib import Path
import threading
from sync_bridge import SyncBridge
from sync_transport import make_transport

_lock = threading.RLock()
_instances = {}


def stop_transports():
    """Stop non-daemon HTTP handlers before the desktop process exits."""
    with _lock:
        for bridge,transport in list(_instances.values()):
            transport.stop()
            if getattr(transport,"files",None):transport.files.queue.close()


def get_runtime(data_root, character="shizuka"):
    key = (str(Path(data_root).resolve()), character)
    with _lock:
        if key in _instances:
            return _instances[key]
        config_path = Path(data_root) / "sync-config.json"
        if not config_path.exists():
            return None
        config = json.loads(config_path.read_text("utf-8-sig"))
        if not config.get("enabled", False):
            return None
        # Restrict this pairing to its intended character, without sharing
        # future persona records accidentally through a different character channel.
        if config.get("character", "shizuka") != character:
            return None
        bridge = SyncBridge(data_root, character)
        try:
            transport = make_transport(bridge, config)
            from sync_files import attach_files
            attach_files(transport,data_root)
        except BaseException:
            bridge.close()
            raise
        _instances[key] = (bridge, transport)
        return bridge, transport
