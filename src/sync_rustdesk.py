"""Exchange the existing SyncBridge journal through a RustDesk TCP tunnel.

The HTTP endpoint only binds loopback. RustDesk owns the cross-network tunnel;
this module neither launches RustDesk nor uses Tailscale or Downloads.
"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import select
import socket
import threading
import time
import urllib.parse
import uuid

from sync_bridge import atomic_json
from sync_store import canonical, validate_bundle, MAX_BYTES
from file_transfer import ENDPOINT as FILE_ENDPOINT, MAX_WIRE as FILE_MAX_WIRE, FileAuthenticationError, FileReplayError
from loopback_session import LoopbackSession

PROTOCOL = "deskpet-rustdesk-v1"
MAX_WIRE_BYTES = MAX_BYTES + 8192
ENDPOINT = "/v1/exchange"
IDENTITY = re.compile(r"[a-f0-9]{32}\Z")


class AuthenticationError(ValueError):
    pass


class ReplayError(ValueError):
    pass


def event_digest(bundle):
    events = sorted(bundle["events"], key=lambda event: (event["device"], event["seq"]))
    return hashlib.sha256(canonical(events).encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


class PersistentHTTPServer(ThreadingHTTPServer):
    """Track sockets so stopping the service does not wait for idle keep-alives."""
    def __init__(self, *args, **kwargs):
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.accepted_connections = 0
        super().__init__(*args, **kwargs)

    def get_request(self):
        client, address = super().get_request()
        with self.clients_lock:
            self.clients.add(client)
            self.accepted_connections += 1
        return client, address

    def close_request(self, request):
        with self.clients_lock:
            self.clients.discard(request)
        super().close_request(request)

    def server_close(self):
        with self.clients_lock:
            for client in list(self.clients):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


class RustDeskSync:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = dict(config)
        self.channel = config.get("channel", "")
        if not isinstance(self.channel, str) or not IDENTITY.fullmatch(self.channel):
            raise ValueError("Invalid pairing channel")
        try:
            self.key = base64.b64decode(config["pairing_key"], validate=True)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Invalid pairing key") from exc
        if len(self.key) != 32:
            raise ValueError("Pairing key must contain 32 random bytes")
        self.peer_url = config.get("peer_url") or ""
        if self.peer_url:
            address = urllib.parse.urlsplit(self.peer_url)
            if (address.scheme != "http" or address.hostname != "127.0.0.1"
                    or address.username or address.password or not address.port
                    or address.query or address.fragment or address.path not in ("", "/")):
                raise ValueError("peer_url must be http://127.0.0.1:<RustDesk-local-forward-port>")
            self.peer_url = self.peer_url.rstrip("/")
        self.timeout = config.get("timeout_seconds", 15)
        self.interval = config.get("poll_seconds", 10)
        self.memory_interval = config.get("memory_interval_seconds", 3*3600)
        if type(self.memory_interval) not in (int,float) or not math.isfinite(self.memory_interval) or not 60<=self.memory_interval<=604800:
            raise ValueError("Invalid memory sync interval")
        for number, maximum in ((self.timeout, 60), (self.interval, 300)):
            if type(number) not in (int, float) or not math.isfinite(number) or not 1 <= number <= maximum:
                raise ValueError("Invalid timeout or polling interval")
        self.listen_port = config.get("listen_port", 47631)
        if type(self.listen_port) is not int or not 0 <= self.listen_port <= 65535:
            raise ValueError("Invalid loopback listen port")
        self.state_path = bridge.sync_dir / ("rustdesk-" + self.channel + ".json")
        self.state = json.loads(self.state_path.read_text("utf-8")) if self.state_path.exists() else {}
        self.lock = threading.RLock()
        self.tick_lock = threading.Lock()
        self.receive_lock = threading.Lock()
        self.seen_requests = {}
        self.stopping = threading.Event()
        self.worker = None
        self.server = None
        self.server_thread = None
        self.files = None  # Optional explicit file queue; no changes to memory journals.
        # Loopback requests must never be forwarded through the system proxy.
        self.session = LoopbackSession(self.peer_url, self.timeout)

    def envelope(self, bundle, kind, reply_to=None):
        validate_bundle(bundle, self.bridge.character)
        message = {"protocol": PROTOCOL, "channel": self.channel, "id": uuid.uuid4().hex,
                   "kind": kind, "issued_at": int(time.time()), "reply_to": reply_to, "body": bundle}
        message["mac"] = hmac.new(self.key, canonical(message).encode("utf-8"), hashlib.sha256).hexdigest()
        return message

    def unpack(self, raw, kind, reply_to=None):
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError("Sync envelope too large")
        message = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        fields = {"protocol", "channel", "id", "kind", "issued_at", "reply_to", "body", "mac"}
        if not isinstance(message, dict) or set(message) != fields:
            raise ValueError("Invalid sync envelope")
        signature = message.pop("mac")
        expected = hmac.new(self.key, canonical(message).encode("utf-8"), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise AuthenticationError("Sync signature mismatch")
        if message["protocol"] != PROTOCOL or message["channel"] != self.channel:
            raise AuthenticationError("Unexpected protocol or pairing channel")
        if message["kind"] != kind or message["reply_to"] != reply_to:
            raise AuthenticationError("Response does not acknowledge this request")
        if not isinstance(message["id"], str) or not IDENTITY.fullmatch(message["id"]):
            raise ValueError("Invalid request identity")
        issued = message["issued_at"]
        if type(issued) is not int or abs(time.time() - issued) > 300:
            raise AuthenticationError("Expired message or device clocks differ by over five minutes")
        validate_bundle(message["body"], self.bridge.character)
        if message["body"]["sender"] == self.bridge.store.device:
            raise ValueError("Peer has this device identity; do not clone the journal database")
        return message

    def _save(self, **changes):
        with self.lock:
            self.state.update(changes)
            self.state["status_write_error"] = ""
            # This JSON is diagnostic metadata, not the authoritative journal.
            # Windows readers/AV may briefly deny replacing an open destination.
            for delay in (0, .025, .05, .1, .2, .4):
                if delay:
                    time.sleep(delay)
                try:
                    atomic_json(self.state_path, self.state)
                    return
                except PermissionError as exc:
                    failure = str(exc)[:300]
            self.state["status_write_error"] = failure
            # Keep exchanging the durable journal; retry status persistence next
            # round and expose this diagnostic failure through status/health.

    def receive(self, raw):
        message = self.unpack(raw, "request")
        with self.receive_lock:
            now = time.time()
            self.seen_requests = {key: expiry for key, expiry in self.seen_requests.items() if expiry >= now}
            if message["id"] in self.seen_requests:
                raise ReplayError("Request already handled; retry with a new request identity")
            if len(self.seen_requests) >= 4096:
                raise ValueError("Too many requests")
            self.seen_requests[message["id"]] = message["issued_at"] + 301
            # Only a successful durable import can produce a signed success reply.
            added, bundle = self.bridge.exchange(message["body"])
            self._save(received_at=now, received_events=added,
                       remote_digest=event_digest(message["body"]), peer_device=message["body"]["sender"],
                       replied_at=now, error="", receive_error="")
            self._save(sync_requested=None)
            return canonical(self.envelope(bundle, "response", message["id"])).encode("utf-8")

    def _post(self, raw):
        return self.session.post(ENDPOINT, raw, MAX_WIRE_BYTES)

    def tick(self, force=False):
        if not self.peer_url:
            return self.status()
        with self.tick_lock:
            if not force and not self.state.get("error") and time.time()-self.state.get("sent_at",0)<self.memory_interval:
                return self.status()
            try:
                added=0
                # The second signed exchange acknowledges the merged view on both
                # devices, without waiting another three hours for confirmation.
                for _ in range(2):
                    bundle = self.bridge.export()
                    message = self.envelope(bundle, "request")
                    raw = self._post(canonical(message).encode("utf-8"))
                    reply = self.unpack(raw, "response", message["id"])
                    count, _ = self.bridge.exchange(reply["body"])
                    added+=count
                now = time.time()
                self._save(sent_at=now, sent_digest=event_digest(bundle),
                           received_at=now, received_events=added, remote_digest=event_digest(reply["body"]),
                           peer_device=reply["body"]["sender"], error="", checked_at=now, added=added,
                           connection=self.session.status())
            except Exception as exc:
                # Durable local journal remains the retry source. No Downloads files.
                self._save(error=str(exc)[:500], checked_at=time.time(), connection=self.session.status())
            return self.status()

    def sync_control(self):
        with self.lock:return {"memory_request":self.state.get("sync_requested")}

    def request_sync(self):
        if self.peer_url:return self.tick(force=True)
        self._save(sync_requested=uuid.uuid4().hex)
        return self.status()

    def poll_once(self):
        # Files and the tiny signed request flag remain responsive independently
        # of the three-hour memory schedule. There is still only one worker.
        request=None
        if self.files and not self.stopping.is_set():
            self.files.tick()
            request=self.files.remote_metadata.get("memory_request")
        forced=isinstance(request,str) and bool(IDENTITY.fullmatch(request)) and request!=self.state.get("handled_memory_request")
        result=self.tick(force=forced)
        if forced and not result.get("error"):
            self._save(handled_memory_request=request)
        return result

    def status(self):
        digest = event_digest(self.bridge.export())
        with self.lock:
            return {**self.state, "transport": "rustdesk-tcp", "peer": self.config.get("peer", "peer"),
                    "connection": self.session.status(),
                    "peer_url": self.peer_url, "listen_port": self.server.server_port if self.server else None,
                    "memory_interval_seconds":self.memory_interval,
                    "next_memory_sync_at":self.state.get("sent_at",self.state.get("received_at",0))+self.memory_interval,
                    "confirmed": self.state.get("remote_digest") == digest,
                    "pending": self.state.get("remote_digest") != digest,
                    "recent_exchange": bool(self.state.get("received_at")) and
                    time.time() - self.state["received_at"] < self.memory_interval+60 and not self.state.get("error")}

    def start_server(self):
        if self.server:
            return self.server.server_port
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "DeskpetSync/1"
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(owner.timeout)

            def handle(self):
                # Separate the idle lifetime from the request-body timeout. Polling
                # readiness also lets Windows stop idle sessions promptly; socket
                # shutdown alone may not interrupt its timed socket read.
                self.close_connection = False
                idle_seconds = max(90, owner.memory_interval+60)
                deadline = time.monotonic() + idle_seconds
                while not self.close_connection and not owner.stopping.is_set():
                    try:
                        readable, _, _ = select.select([self.connection], [], [], .2)
                        if readable:
                            self.handle_one_request()
                            deadline = time.monotonic() + idle_seconds
                        elif time.monotonic() >= deadline:
                            break
                    except OSError:
                        break

            def log_message(self, *_args):
                pass  # Never log message bodies, keys, or personal memory contents.

            def send_json(self, code, body):
                raw = canonical(body).encode("utf-8") if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                if code != 200:
                    self.close_connection = True
                    self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self.send_json(200, {"service": "deskpet-sync", "protocol": PROTOCOL,
                                         "files": "deskpet-rustdesk-files-v1" if owner.files else None,
                                         "connection_policy": "shared-persistent", "version": "0.4.1",
                                         "memory_interval_seconds":owner.memory_interval,
                                         "worker_running": bool(owner.worker and owner.worker.is_alive()),
                                         "status_write_ok": not bool(owner.state.get("status_write_error")),
                                         "worker_error": bool(owner.state.get("worker_error")),
                                         "connection": owner.session.status()})
                else:
                    self.send_json(404, {"error": "not_found"})

            def do_POST(self):
                is_file = self.path == FILE_ENDPOINT and owner.files is not None
                if self.path != ENDPOINT and not is_file:
                    self.send_json(404, {"error": "not_found"})
                    return
                if self.headers.get("Origin") or not re.fullmatch(r"127\.0\.0\.1:\d{1,5}", self.headers.get("Host", "")):
                    self.send_json(403, {"error": "local_service_only"})
                    return
                sizes = self.headers.get_all("Content-Length", [])
                if len(sizes) != 1 or not sizes[0].isdigit() or self.headers.get("Transfer-Encoding"):
                    self.send_json(411, {"error": "content_length_required"})
                    return
                size = int(sizes[0])
                if size < 1 or size > (FILE_MAX_WIRE if is_file else MAX_WIRE_BYTES):
                    self.send_json(413, {"error": "message_size_limit"})
                    return
                if self.headers.get_content_type() != "application/json":
                    self.send_json(415, {"error": "json_required"})
                    return
                try:
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("Incomplete request")
                    response = owner.files.receive(raw) if is_file else owner.receive(raw)
                except (AuthenticationError, FileAuthenticationError):
                    self.send_json(401, {"error": "authentication_failed"})
                except (ReplayError, FileReplayError):
                    self.send_json(409, {"error": "duplicate_request"})
                except (ValueError, TypeError, KeyError, UnicodeError):
                    self.send_json(400, {"error": "invalid_message"})
                except Exception:
                    self.send_json(500, {"error": "exchange_failed"})
                else:
                    self.send_json(200, response)

        self.server = PersistentHTTPServer(("127.0.0.1", self.listen_port), Handler)
        # Let server_close wait for handlers before the caller closes SyncBridge.
        self.server.daemon_threads = False
        self.server_thread = threading.Thread(target=self.server.serve_forever,
                                               kwargs={"poll_interval": .1}, daemon=True, name="deskpet-rustdesk-api")
        self.server_thread.start()
        return self.server.server_port

    def start(self):
        self.start_server()
        if not self.peer_url or (self.worker and self.worker.is_alive()):
            return
        self.stopping.clear()

        def loop():
            while not self.stopping.is_set():
                try:
                    self.poll_once()
                    with self.lock:
                        self.state["worker_error"] = ""
                except Exception as exc:
                    # A diagnostics/disk failure must not silently kill the sole
                    # worker. Do not acknowledge failed operations or reset backoff.
                    with self.lock:
                        self.state["worker_error"] = str(exc)[:300]
                self.stopping.wait(self.interval)

        self.worker = threading.Thread(target=loop, daemon=True, name="deskpet-rustdesk-poll")
        self.worker.start()

    def stop(self):
        self.stopping.set()
        if self.files:
            self.files.stopping.set()
        if self.worker:
            self.worker.join(self.timeout + 25)
            if self.worker.is_alive():
                raise TimeoutError("Sync worker is still finishing; keep its bridge open")
        self.session.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(2)
            self.server = None
