"""Authenticated journal exchange over the public Tailscale file CLI.

No listening port, SSH, PeerAPI, shell commands, or remote execution. Receiving
is a directory scan by default so an existing Taildrop receiver can own delivery.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from sync_bridge import atomic_json
from sync_store import canonical, validate_bundle, MAX_BYTES


def discover_tailscale(configured=None):
    candidates = [configured, shutil.which("tailscale"),
                  r"C:\Program Files\Tailscale\tailscale.exe",
                  "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                  "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise FileNotFoundError("未找到 Tailscale CLI，请在配置中填写 tailscale 路径")


def event_digest(bundle):
    return hashlib.sha256(canonical(sorted(bundle["events"], key=lambda e: (e["device"], e["seq"]))).encode()).hexdigest()


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Invalid sync configuration")
    if not re.fullmatch(r"[a-f0-9]{32}", config.get("channel", "")):
        raise ValueError("Invalid pairing channel")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", config.get("peer", "")):
        raise ValueError("Invalid Tailscale peer")
    try:
        key = base64.b64decode(config["pairing_key"], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid pairing key") from exc
    if len(key) != 32:
        raise ValueError("Invalid pairing key")
    if config.get("receive_mode", "scan") not in {"scan", "file_get"}:
        raise ValueError("Invalid receiving mode")
    return key


class TaildropSync:
    def __init__(self, bridge, config, runner=None):
        self.bridge, self.config = bridge, dict(config)
        self.key = validate_config(config)
        self.channel = config["channel"]
        self.prefix = "deskpet-" + self.channel + "-"
        self.inbox = Path(config.get("inbox") or Path.home() / "Downloads").expanduser().resolve()
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.state_path = bridge.sync_dir / ("taildrop-" + self.channel + ".json")
        self.state = json.loads(self.state_path.read_text("utf8")) if self.state_path.exists() else {}
        self.runner = runner or self._run
        self.lock = threading.RLock()
        self.tick_lock = threading.Lock()
        self.stopping = threading.Event()
        self.worker = None

    def _run(self, args):
        env = dict(os.environ)
        env.setdefault("TERM", "dumb")  # macOS app binary's documented CLI mode.
        return subprocess.run([discover_tailscale(self.config.get("tailscale")), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
            env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def _call(self, args):
        # Network delays must not prevent the local UI from showing/editing data.
        # tick_lock still serializes manual and automatic exchanges.
        self.lock.release()
        try:
            return self.runner(args)
        finally:
            self.lock.acquire()

    def packet(self, bundle):
        validate_bundle(bundle, self.bridge.character)
        unsigned = {"protocol": 1, "channel": self.channel, "packet": uuid.uuid4().hex, "body": bundle}
        return {**unsigned, "mac": hmac.new(self.key, canonical(unsigned).encode(), hashlib.sha256).hexdigest()}

    def unpack(self, raw):
        if len(raw) > MAX_BYTES + 4096:
            raise ValueError("Sync packet too large")
        packet = json.loads(raw)
        if not isinstance(packet, dict) or set(packet) != {"protocol", "channel", "packet", "body", "mac"}:
            raise ValueError("Invalid signed envelope")
        signature = packet.pop("mac")
        expected = hmac.new(self.key, canonical(packet).encode(), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise ValueError("同步包签名不匹配，文件已保留")
        if type(packet["protocol"]) is not int or packet["protocol"] != 1 or packet["channel"] != self.channel:
            raise ValueError("Unexpected pairing channel")
        if not isinstance(packet["packet"], str) or not re.fullmatch(r"[a-f0-9]{32}", packet["packet"]):
            raise ValueError("Invalid packet identity")
        validate_bundle(packet["body"], self.bridge.character)
        return packet

    def _receive(self):
        if self.config.get("receive_mode", "scan") == "file_get":
            # Explicit mode only. Normal Downloads remains the destination for
            # unrelated Taildrop files; never drain them into a hidden directory.
            result = self._call(["file", "get", "--conflict=rename", str(self.inbox)])
            if result.returncode:
                raise RuntimeError("Taildrop 接收失败：" + result.stderr[:500])
        added = 0
        for path in sorted(self.inbox.glob(self.prefix + "*.deskpet-sync.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
                fingerprint = [stat.st_size, stat.st_mtime_ns]
                if self.state.get("processed", {}).get(path.name) == fingerprint:
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 4097)
                packet = self.unpack(raw)
                body = packet["body"]
                if body["sender"] == self.bridge.store.device:
                    raise ValueError("收到自己的设备身份，请勿复制 .sync 数据库到另一台设备")
                imported, _ = self.bridge.exchange(body)
                added += imported
                self.state.update(remote_digest=event_digest(body), received_at=time.time(),
                                  peer_device=body["sender"], received_events=imported)
                # Leave received files in the user's chosen inbox. Only remember
                # successfully imported files; replay after a crash is harmless.
                self.state.setdefault("processed", {})[path.name] = fingerprint
            except (ValueError, OSError, TypeError, KeyError) as exc:
                self.state["receive_error"] = str(exc)[:600]
        return added

    def tick(self, force=False):
        with self.tick_lock, self.lock:
            try:
                self.state.pop("receive_error", None)
                added = self._receive()
                bundle = self.bridge.export()
                digest = event_digest(bundle)
                now = time.time()
                acknowledged = self.state.get("remote_digest") == digest
                should_send = force or self.state.get("sent_digest") != digest or (
                    not acknowledged and now - self.state.get("sent_at", 0) > 300)
                if should_send:
                    packet = self.packet(bundle)
                    outbox = self.bridge.sync_dir / "outbox"
                    outbox.mkdir(exist_ok=True)
                    path = outbox / (self.prefix + packet["packet"] + ".deskpet-sync.json")
                    atomic_json(path, packet)
                    try:
                        result = self._call(["file", "cp", str(path), self.config["peer"] + ":"])
                        if result.returncode:
                            raise RuntimeError("Taildrop 发送失败：" + result.stderr[:500])
                        self.state.update(sent_digest=digest, sent_at=now)
                    finally:
                        # Journal is the retry source, not an accumulating queue.
                        path.unlink(missing_ok=True)
                self.state.pop("error", None)
                self.state["added"] = added
            except Exception as exc:
                self.state["error"] = str(exc)[:600]
            self.state["checked_at"] = time.time()
            atomic_json(self.state_path, self.state)
            return self.status()

    def status(self):
        with self.lock:
            digest = event_digest(self.bridge.export())
            return {**{k: v for k, v in self.state.items() if k != "processed"}, "peer": self.config["peer"], "inbox": str(self.inbox),
                    "confirmed": self.state.get("remote_digest") == digest,
                    "pending": self.state.get("sent_digest") != digest}

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stopping.clear()
        def loop():
            while not self.stopping.is_set():
                self.tick()
                self.stopping.wait(10)
        self.worker = threading.Thread(target=loop, name="deskpet-taildrop", daemon=True)
        self.worker.start()

    def stop(self):
        self.stopping.set()
