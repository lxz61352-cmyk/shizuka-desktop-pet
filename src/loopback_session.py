"""One persistent HTTP connection shared by memory and files over RustDesk.

Never reconnect within a request. Failed connections back off, and three
consecutive failures suspend reconnection until the helper is explicitly restarted.
"""
import http.client
import math
import threading
import time
import urllib.parse


class LoopbackSession:
    def __init__(self, peer_url, timeout=15):
        self.peer_url = (peer_url or "").rstrip("/")
        self.address = urllib.parse.urlsplit(peer_url or "")
        if peer_url and (self.address.scheme != "http" or self.address.hostname != "127.0.0.1"
                or not self.address.port or self.address.username or self.address.password
                or self.address.path not in ("", "/") or self.address.query or self.address.fragment):
            raise ValueError("Peer must be http://127.0.0.1:<RustDesk-local-forward-port>")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise ValueError("Invalid HTTP timeout")
        self.timeout = timeout
        self.lock = threading.RLock()
        self.connection = None
        self.connect_attempts = 0
        self.requests = 0
        self.failures = 0
        self.retry_at = 0
        self.circuit_open = False
        self.stopped = False

    def _close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def status(self):
        with self.lock:
            return {"policy": "shared-persistent", "connect_attempts": self.connect_attempts,
                    "requests": self.requests, "consecutive_failures": self.failures,
                    "retry_after_seconds": max(0, round(self.retry_at - time.monotonic(), 1)),
                    "reconnection_paused": self.circuit_open, "stopped": self.stopped,
                    "connected": bool(self.connection and self.connection.sock)}

    def post(self, path, raw, maximum):
        if path not in ("/v1/exchange", "/v1/files"):
            raise ValueError("Unsupported local API endpoint")
        with self.lock:
            if self.stopped:
                raise ConnectionError("Transport is stopped")
            if not self.peer_url:
                raise ValueError("No outgoing tunnel configured")
            if self.circuit_open:
                raise ConnectionError("Reconnection paused after three failures; inspect peer and explicitly restart helper")
            if time.monotonic() < self.retry_at:
                raise ConnectionError("Reconnection cooling down; queue retained")
            try:
                if self.connection is None:
                    self.connect_attempts += 1
                    self.connection = http.client.HTTPConnection("127.0.0.1", self.address.port, timeout=self.timeout)
                self.connection.request("POST", path, raw, {"Content-Type": "application/json"})
                self.requests += 1
                response = self.connection.getresponse()
                data = response.read(maximum + 1)
                if response.status != 200:
                    # http.client does not follow redirects or apply system proxies.
                    raise ConnectionError("API returned HTTP " + str(response.status))
                if response.headers.get_content_type() != "application/json" or len(data) > maximum:
                    raise ValueError("Unexpected or oversized API response")
                if response.will_close:
                    raise ConnectionError("Peer closed keep-alive; upgrade both helpers before resuming")
                self.failures = 0
                self.retry_at = 0
                return data
            except Exception:
                self._close()
                self.failures += 1
                self.retry_at = time.monotonic() + min(120, 15 * 2 ** min(self.failures - 1, 3))
                self.circuit_open = self.failures >= 3
                raise

    def close(self):
        with self.lock:
            self.stopped = True
            self._close()
