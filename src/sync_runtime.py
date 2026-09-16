"""Opt-in app integration. Configuration is separate from pet preferences."""
import json
from pathlib import Path
import threading
from sync_bridge import SyncBridge
from sync_transport import make_transport

# 双端共享/同步记忆还没做好，先整体关掉（和研究进展一样）：菜单只显示「开发中」，
# 后台不启动传输、不排期检查，待办/记忆/聊天记录一律退回本地 JSON 存储。
# 配对配置、journal、传输层代码都还在，改 True 即可恢复。
SYNC_ENABLED = False

_lock = threading.RLock()
_instances = {}


def stop_transports():
    """Stop non-daemon HTTP handlers before the desktop process exits."""
    with _lock:
        for bridge,transport in list(_instances.values()):
            transport.stop()
            if getattr(transport,"files",None):transport.files.queue.close()


def get_runtime(data_root, character="shizuka"):
    if not SYNC_ENABLED:
        return None
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
