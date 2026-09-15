"""Keep legacy JSON views compatible with the authoritative portable journal."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from sync_store import SyncStore, Snapshot, FIELDS, IDENTIFIER, canonical, stable_rows


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".sync-write-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class SyncBridge:
    def __init__(self, data_root, character="shizuka", device=None):
        if not IDENTIFIER.fullmatch(character):
            raise ValueError("Invalid character ID")
        self.root = Path(data_root).resolve()
        self.directory = self.root / "characters" / character
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sync_dir = self.directory / ".sync"
        self.sync_dir.mkdir(exist_ok=True)
        self.thread_lock = threading.RLock()
        self.paths = {"memories": self.directory / "memory.json", "todos": self.directory / "todos.json",
                      "chats": self.directory / "对话记录" / "对话记录.json"}
        self.store = SyncStore(self.sync_dir / "journal.sqlite3", character, device)
        self.character = character
        try:
            with self.exclusive():
                self._bootstrap()
        except BaseException:
            self.store.close()
            raise

    @contextmanager
    def exclusive(self):
        """Serialize JSON projections across app and local helper processes."""
        with self.thread_lock:
            with open(self.sync_dir / "projection.lock", "a+b") as lockfile:
                lockfile.seek(0, os.SEEK_END)
                if lockfile.tell() == 0:
                    lockfile.write(b"0")
                    lockfile.flush()
                lockfile.seek(0)
                if os.name == "nt":
                    import msvcrt
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise TimeoutError("Sync data is busy")
                            time.sleep(.05)
                else:
                    import fcntl
                    fcntl.flock(lockfile, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lockfile.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lockfile, fcntl.LOCK_UN)

    def _bootstrap(self):
        # Validate all source files first. A malformed legacy file must not become
        # an empty initialized collection or an inferred deletion.
        imports = {}
        for collection, path in self.paths.items():
            if self.store.meta("initialized:" + collection):
                continue
            raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else ([] if collection == "chats" else {"items": []})
            if collection != "chats":
                if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
                    raise ValueError("Invalid legacy " + collection + " file; original retained")
                raw = raw["items"]
            imports[collection] = stable_rows(collection, raw)
        for collection, rows in imports.items():
            path = self.paths[collection]
            if path.exists():
                backup = self.sync_dir / "before-sync" / path.name
                backup.parent.mkdir(exist_ok=True)
                if not backup.exists():
                    shutil.copy2(path, backup)
            self.store.commit_snapshot(collection, rows, Snapshot(), delete_missing=False)
            with self.store.transaction():
                self.store.set_meta("initialized:" + collection, True)
        self._project()

    def _sorted(self, collection, rows):
        if collection == "memories":
            rows.sort(key=lambda r: (not r.get("pinned", False), -(r.get("last_used") or 0), r["id"]))
        else:
            rows.sort(key=lambda r: (r.get("created") or 0, r["id"]))
        return rows

    def _project(self):
        for collection, path in self.paths.items():
            rows = self._sorted(collection, self.store.rows(collection))
            view = list(rows) if collection == "chats" else {"items": list(rows)}
            atomic_json(path, view)

    def read(self, collection):
        with self.exclusive():
            rows = self._sorted(collection, self.store.rows(collection))
            return Snapshot(rows if collection == "chats" else rows, rows.clock)

    def commit(self, collection, desired, observed):
        with self.exclusive():
            rows = self.store.commit_snapshot(collection, desired, observed, delete_missing=collection != "chats")
            rows = self._sorted(collection, rows)
            atomic_json(self.paths[collection], list(rows) if collection == "chats" else {"items": list(rows)})
            return Snapshot(rows if collection == "chats" else rows, rows.clock)

    def exchange(self, bundle, collections=None):
        with self.exclusive():
            added = self.store.import_bundle(bundle, collections)
            self._project()
            return added, self.store.bundle(collections)

    def export(self, collections=None):
        with self.exclusive():
            return self.store.bundle(collections)

    def status(self):
        with self.exclusive():
            return {"character": self.character, "device": self.store.device,
                    "counts": {k: len(self.store.rows(k)) for k in FIELDS},
                    "events": len(self.store.bundle()["events"]),
                    "conflicts": len(self.store.conflicts())}

    def close(self):
        self.store.close()
