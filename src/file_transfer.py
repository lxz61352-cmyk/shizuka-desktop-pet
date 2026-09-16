"""Durable, explicitly queued file delivery over the existing RustDesk tunnel.

The peer can read only queued snapshots, never arbitrary local paths. A received
file is acknowledged only after SHA256 verification and no-overwrite publication.
No received file is executed, extracted, or treated as an instruction.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import urllib.parse
import uuid
from loopback_session import LoopbackSession

ENDPOINT = "/v1/files"
PROTOCOL = "deskpet-rustdesk-files-v1"
CHUNK = 1024 * 1024
MAX_WIRE = CHUNK * 2
MAX_FILE = 16 * 1024 ** 3
IDENT = re.compile(r"[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


class FileAuthenticationError(ValueError):
    pass


class FileReplayError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON field")
        value[key] = item
    return value


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    if (not isinstance(name, str) or not name or len(name.encode("utf-8")) > 180
            or name in (".", "..") or name[-1] in " ."
            or any(ord(c) < 32 or c in '/\\:<>"|?*' for c in name)
            or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *("COM" + str(n) for n in range(1, 10)), *("LPT" + str(n) for n in range(1, 10))}):
        raise ValueError("Unsupported or unsafe file name")
    return name


def manifest(value):
    if not isinstance(value, dict) or set(value) != {"id", "name", "size", "sha256"}:
        raise ValueError("Invalid file manifest")
    if not isinstance(value["id"], str) or not IDENT.fullmatch(value["id"]):
        raise ValueError("Invalid transfer ID")
    if not isinstance(value["sha256"], str) or not HASH.fullmatch(value["sha256"]):
        raise ValueError("Invalid file digest")
    if type(value["size"]) is not int or not 0 <= value["size"] <= MAX_FILE:
        raise ValueError("File exceeds 16 GiB limit")
    safe_name(value["name"])
    return value


class FileQueue:
    def __init__(self, state_dir, receive_dir=None):
        self.root = Path(state_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "files.sqlite3", timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outgoing (
                id TEXT PRIMARY KEY, name TEXT, size INTEGER, sha256 TEXT,
                status TEXT NOT NULL, remote_path TEXT, created REAL, completed REAL);
            CREATE TABLE IF NOT EXISTS incoming (
                id TEXT PRIMARY KEY, name TEXT, size INTEGER, sha256 TEXT,
                offset INTEGER NOT NULL, path TEXT UNIQUE, status TEXT NOT NULL,
                created REAL, completed REAL);
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, expiry REAL);
        """)
        old = self.db.execute("SELECT value FROM settings WHERE key='receive_dir'").fetchone()
        if receive_dir is not None:
            target = Path(receive_dir).expanduser().resolve()
            target.mkdir(parents=True, exist_ok=True)
            if old and old[0] != str(target):
                raise ValueError("Receive folder is already configured; migrate deliberately")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES ('receive_dir', ?)", (str(target),))
            self.db.commit()
            self.receive_dir = target
        elif old:
            self.receive_dir = Path(old[0])
        else:
            raise ValueError("Initialize with an explicit receive folder first")
        for folder in ("outgoing", "incoming"):
            (self.root / folder).mkdir(exist_ok=True)

    def close(self):
        self.db.close()

    def _blob(self, direction, transfer_id):
        if not isinstance(transfer_id, str) or not IDENT.fullmatch(transfer_id):
            raise ValueError("Invalid transfer ID")
        path = self.root / direction / (transfer_id + ".part")
        if path.is_symlink() or path.resolve().parent != (self.root / direction).resolve():
            raise ValueError("Unexpected spool path")
        return path

    @staticmethod
    def _manifest(row):
        return {key: row[key] for key in ("id", "name", "size", "sha256")}

    def enqueue(self, source):
        source = Path(source).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError("Send a regular file; zip folders first")
        safe_name(source.name)
        if source.stat().st_size > MAX_FILE:
            raise ValueError("File exceeds 16 GiB limit")
        transfer_id = uuid.uuid4().hex
        snapshot = self._blob("outgoing", transfer_id)
        before = source.stat()
        try:
            with source.open("rb") as src, snapshot.open("xb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
                dst.flush()
                os.fsync(dst.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Source changed while creating snapshot; retry")
            item = manifest({"id": transfer_id, "name": source.name, "size": snapshot.stat().st_size,
                             "sha256": digest_file(snapshot)})
            with self.lock, self.db:
                self.db.execute("INSERT INTO outgoing VALUES (?,?,?,?, 'queued',NULL,?,NULL)",
                                (item["id"], item["name"], item["size"], item["sha256"], time.time()))
            return item
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise

    def list_outgoing(self):
        with self.lock:
            return [self._manifest(row) for row in self.db.execute(
                "SELECT * FROM outgoing WHERE status='queued' ORDER BY created LIMIT 32")]

    def read_chunk(self, transfer_id, offset):
        with self.lock:
            row = self.db.execute("SELECT * FROM outgoing WHERE id=?", (transfer_id,)).fetchone()
            if not row or row["status"] != "queued":
                raise ValueError("No queued file with this ID")
            if type(offset) is not int or not 0 <= offset <= row["size"]:
                raise ValueError("Invalid file offset")
            with self._blob("outgoing", transfer_id).open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read(CHUNK)
            return {"offset": offset, "data": base64.b64encode(chunk).decode("ascii"),
                    "chunk_sha256": hashlib.sha256(chunk).hexdigest()}

    def _progress(self, row):
        return {**self._manifest(row), "offset": row["offset"], "complete": row["status"] == "received",
                "path": row["path"] if row["status"] == "received" else None}

    def offer(self, item):
        item = manifest(item)
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM incoming WHERE id=?", (item["id"],)).fetchone()
            if row:
                if self._manifest(row) != item:
                    raise ValueError("Transfer ID reused with different contents")
                return self._progress(row)
            pending = self.db.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM incoming WHERE status!='received'").fetchone()
            if pending[0] >= 128 or pending[1] + item["size"] > 64 * 1024 ** 3:
                raise ValueError("Incoming queue quota exceeded")
            if shutil.disk_usage(self.root).free < item["size"] + 16 * 1024 ** 2:
                raise ValueError("Not enough spool disk space")
            if shutil.disk_usage(self.receive_dir).free < item["size"] + 16 * 1024 ** 2:
                raise ValueError("Not enough receive disk space")
            path = self.receive_dir / item["name"]
            n = 0
            while path.exists() or path.is_symlink() or self.db.execute("SELECT 1 FROM incoming WHERE path=?", (str(path),)).fetchone():
                n += 1
                base = Path(item["name"])
                path = self.receive_dir / (base.stem + " (rd-" + item["id"][:8] + "-" + str(n) + ")" + base.suffix)
            self.db.execute("INSERT INTO incoming VALUES (?,?,?,?,0,?,'receiving',?,NULL)",
                            (item["id"], item["name"], item["size"], item["sha256"], str(path), time.time()))
            row = self.db.execute("SELECT * FROM incoming WHERE id=?", (item["id"],)).fetchone()
            return self._progress(row)

    def write_chunk(self, transfer_id, chunk):
        if not isinstance(chunk, dict) or set(chunk) != {"offset", "data", "chunk_sha256"}:
            raise ValueError("Invalid chunk")
        data = base64.b64decode(chunk["data"], validate=True)
        if len(data) > CHUNK or hashlib.sha256(data).hexdigest() != chunk["chunk_sha256"]:
            raise ValueError("Invalid chunk checksum or size")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM incoming WHERE id=?", (transfer_id,)).fetchone()
            if not row:
                raise ValueError("Offer the manifest first")
            if row["status"] == "received":
                return self._progress(row)
            offset = chunk["offset"]
            if type(offset) is not int or offset != row["offset"] or offset + len(data) > row["size"]:
                raise ValueError("Chunk offset mismatch; query current progress")
            if not data and offset != row["size"]:
                raise ValueError("Empty non-final chunk")
            part = self._blob("incoming", transfer_id)
            with part.open("r+b" if part.exists() else "x+b") as stream:
                if stream.seek(0, os.SEEK_END) < offset:
                    raise ValueError("Partial file is shorter than persisted offset")
                stream.seek(offset)
                stream.truncate()
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.db.execute("UPDATE incoming SET offset=? WHERE id=?", (offset + len(data), transfer_id))
            if offset + len(data) == row["size"]:
                if digest_file(part) != row["sha256"]:
                    # Retain file for diagnosis, but restart from byte zero on retry.
                    self.db.execute("UPDATE incoming SET offset=0 WHERE id=?", (transfer_id,))
                    self.db.commit()
                    raise ValueError("Whole-file checksum mismatch")
                target = Path(row["path"])
                if target.parent.resolve() != self.receive_dir.resolve() or target.is_symlink():
                    raise ValueError("Receive destination changed")
                stage = self.receive_dir / (".rustdesk-" + transfer_id + ".tmp")
                if target.exists():
                    # Recovery after publication succeeded but the DB commit was interrupted.
                    if target.stat().st_size != row["size"] or digest_file(target) != row["sha256"]:
                        raise FileExistsError("Destination appeared; preserving existing file")
                else:
                    if stage.is_symlink():
                        raise ValueError("Unexpected publication staging link")
                    with part.open("rb") as src, stage.open("wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK)
                        dst.flush()
                        os.fsync(dst.fileno())
                    # Both paths are in the receive folder: link publishes atomically,
                    # refuses overwrites, and works even when spool is on another disk.
                    os.link(stage, target)
                stage.unlink(missing_ok=True)
                self.db.execute("UPDATE incoming SET status='received',completed=? WHERE id=?", (time.time(), transfer_id))
                self.db.commit()  # Durable receipt before deleting the resumable partial.
                part.unlink(missing_ok=True)
            row = self.db.execute("SELECT * FROM incoming WHERE id=?", (transfer_id,)).fetchone()
            return self._progress(row)

    def acknowledge(self, receipt):
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM outgoing WHERE id=?", (receipt.get("id"),)).fetchone()
            if (not row or not receipt.get("complete") or receipt.get("offset") != row["size"]
                    or self._manifest(row) != {key: receipt.get(key) for key in ("id", "name", "size", "sha256")}
                    or not isinstance(receipt.get("path"), str) or not receipt["path"]):
                raise ValueError("Receipt does not confirm the queued file")
            self.db.execute("UPDATE outgoing SET status='delivered',remote_path=?,completed=COALESCE(completed,?) WHERE id=?",
                            (receipt["path"], time.time(), row["id"]))
            self.db.commit()
            self._blob("outgoing", row["id"]).unlink(missing_ok=True)
            return {"acknowledged": row["id"]}

    def status(self, transfer_id=None):
        with self.lock:
            if transfer_id:
                outgoing_sql = "SELECT * FROM outgoing WHERE id=?"
                incoming_sql = "SELECT * FROM incoming WHERE id=?"
                params = (transfer_id,)
            else:
                outgoing_sql = "SELECT * FROM outgoing ORDER BY created DESC LIMIT 50"
                incoming_sql = "SELECT * FROM incoming ORDER BY created DESC LIMIT 50"
                params = ()
            return {"receive_dir": str(self.receive_dir),
                    "outgoing": [dict(row) for row in self.db.execute(outgoing_sql, params)],
                    "incoming": [dict(row) for row in self.db.execute(incoming_sql, params)]}


class FileTransfer:
    def __init__(self, queue, config, session=None):
        self.queue = queue
        self.channel = config["channel"]
        key = base64.b64decode(config["pairing_key"], validate=True)
        if len(key) != 32 or not IDENT.fullmatch(self.channel):
            raise ValueError("Invalid private file pairing")
        self.key = hmac.new(key, PROTOCOL.encode("ascii"), hashlib.sha256).digest()
        self.peer_url = config.get("peer_url") or ""
        self.address = urllib.parse.urlsplit(self.peer_url)
        if self.peer_url and (self.address.scheme != "http" or self.address.hostname != "127.0.0.1"
                or not self.address.port or self.address.username or self.address.password
                or self.address.path not in ("", "/") or self.address.query or self.address.fragment):
            raise ValueError("File peer must be a local RustDesk forward")
        self.timeout = config.get("timeout_seconds", 15)
        self.interval = config.get("poll_seconds", 10)
        self.owns_session = session is None
        self.session = session if session is not None else LoopbackSession(self.peer_url, self.timeout)
        if self.session.peer_url != self.peer_url.rstrip("/"):
            raise ValueError("Shared session has a different peer")
        self.stopping = threading.Event()
        self.worker = None
        self.tick_lock = threading.Lock()
        self.last_error = ""
        self.checked_at = None
        self.metadata_provider = None
        self.remote_metadata = {}

    def envelope(self, body, kind="request", reply_to=None):
        message = {"protocol": PROTOCOL, "channel": self.channel, "id": uuid.uuid4().hex,
                   "issued_at": int(time.time()), "kind": kind, "reply_to": reply_to, "body": body}
        message["mac"] = hmac.new(self.key, encode(message), hashlib.sha256).hexdigest()
        return message

    def unpack(self, raw, kind, reply_to=None):
        if len(raw) > MAX_WIRE:
            raise ValueError("File envelope too large")
        message = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        if not isinstance(message, dict) or set(message) != {"protocol", "channel", "id", "issued_at", "kind", "reply_to", "body", "mac"}:
            raise ValueError("Invalid file envelope")
        signature = message.pop("mac")
        if not isinstance(signature, str) or not hmac.compare_digest(signature, hmac.new(self.key, encode(message), hashlib.sha256).hexdigest()):
            raise FileAuthenticationError("File signature mismatch")
        if (message["protocol"] != PROTOCOL or message["channel"] != self.channel
                or message["kind"] != kind or message["reply_to"] != reply_to
                or type(message["issued_at"]) is not int or abs(time.time() - message["issued_at"]) > 300):
            raise FileAuthenticationError("Wrong pairing, response ID, or clock")
        if not isinstance(message["id"], str) or not IDENT.fullmatch(message["id"]) or not isinstance(message["body"], dict):
            raise ValueError("Invalid file request")
        return message

    def receive(self, raw):
        message = self.unpack(raw, "request")
        with self.queue.lock:
            with self.queue.db:
                self.queue.db.execute("DELETE FROM requests WHERE expiry<?", (time.time(),))
                if self.queue.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] > 10000:
                    raise ValueError("Request rate exceeded")
                try:
                    self.queue.db.execute("INSERT INTO requests VALUES (?,?)", (message["id"], message["issued_at"] + 301))
                except sqlite3.IntegrityError:
                    raise FileReplayError("Retry using a new request ID") from None
            request = message["body"]
            op = request.get("op")
            if op == "list":
                result = {"files": self.queue.list_outgoing()}
                if self.metadata_provider:result["sync_control"]=self.metadata_provider()
            elif op == "offer":
                result = self.queue.offer(request["file"])
            elif op == "chunk":
                result = self.queue.write_chunk(request["id"], request["chunk"])
            elif op == "read":
                result = self.queue.read_chunk(request["id"], request["offset"])
            elif op == "ack":
                result = self.queue.acknowledge(request["receipt"])
            else:
                raise ValueError("Unknown file operation")
            return encode(self.envelope(result, "response", message["id"]))

    def rpc(self, body):
        if not self.peer_url:
            raise ValueError("No outgoing tunnel configured")
        message = self.envelope(body)
        raw = encode(message)
        data = self.session.post(ENDPOINT, raw, MAX_WIRE)
        return self.unpack(data, "response", message["id"])["body"]

    @staticmethod
    def validate_progress(item, progress):
        if (not isinstance(progress, dict) or any(progress.get(k) != v for k, v in item.items())
                or type(progress.get("offset")) is not int or not 0 <= progress["offset"] <= item["size"]
                or type(progress.get("complete")) is not bool):
            raise ValueError("Peer progress does not match the queued file")
        return progress

    def tick(self):
        with self.tick_lock:
            try:
                for item in self.queue.list_outgoing():
                    progress = self.validate_progress(item, self.rpc({"op": "offer", "file": item}))
                    while not progress["complete"]:
                        if self.stopping.is_set():
                            return
                        chunk = self.queue.read_chunk(item["id"], progress["offset"])
                        newer = self.validate_progress(item, self.rpc({"op": "chunk", "id": item["id"], "chunk": chunk}))
                        if not newer["complete"] and newer["offset"] <= progress["offset"]:
                            raise ValueError("Peer made no file progress")
                        progress = newer
                    self.queue.acknowledge(progress)
                listing=self.rpc({"op": "list"})
                self.remote_metadata=listing.get("sync_control",{})
                if not isinstance(self.remote_metadata,dict):self.remote_metadata={}
                items = listing["files"]
                if not isinstance(items, list) or len(items) > 32:
                    raise ValueError("Invalid peer queue")
                for item in items:
                    progress = self.queue.offer(item)
                    while not progress["complete"]:
                        if self.stopping.is_set():
                            return
                        chunk = self.rpc({"op": "read", "id": item["id"], "offset": progress["offset"]})
                        progress = self.queue.write_chunk(item["id"], chunk)
                    ack = self.rpc({"op": "ack", "receipt": progress})
                    if ack.get("acknowledged") != item["id"]:
                        raise ValueError("Peer did not acknowledge the delivery receipt")
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)[:300]
            finally:
                self.checked_at = time.time()
                with self.queue.lock, self.queue.db:
                    self.queue.db.execute("INSERT OR REPLACE INTO settings VALUES ('transport_status',?)",
                                          (json.dumps({"checked_at": self.checked_at, "error": self.last_error,
                                                       "connection": self.session.status()}),))
        return {"error": self.last_error, "checked_at": self.checked_at}

    def start(self):
        if not self.peer_url or self.worker:
            return
        def loop():
            while not self.stopping.is_set():
                self.tick()
                self.stopping.wait(self.interval)
        self.worker = threading.Thread(target=loop, daemon=True, name="rustdesk-files")
        self.worker.start()

    def stop(self):
        self.stopping.set()
        if self.worker:
            self.worker.join(self.timeout + 5)
            if self.worker.is_alive():
                raise TimeoutError("File worker still finishing")
        if self.owns_session:
            self.session.close()
