"""Portable, offline-first field journal. No network, credentials, or GUI imports.

Events are immutable. Lamport order gives deterministic field resolution without
depending on wall clocks; causal contexts retain concurrent conflicts for review.
Deletions are independent tombstones, so stale offline edits cannot resurrect data.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

SCHEMA = 1
MAX_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 100000
FIELDS = {
    "memories": {"content", "pinned", "created", "last_used", "use_count"},
    "chats": {"role", "text", "kind", "created", "device", "turn_id"},
    "todos": {"text", "due", "on_boot", "done", "created"},
}
IDENTIFIER = re.compile(r"[a-zA-Z0-9_-]{1,96}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Snapshot(list):
    def __init__(self, rows=(), clock=None):
        super().__init__(rows)
        self.clock = dict(clock or {})


def stable_rows(collection, rows):
    """Give legacy rows deterministic IDs; repeated identical chats stay distinct."""
    if collection not in FIELDS or not isinstance(rows, list):
        raise ValueError("Invalid collection")
    result, seen, occurrences = [], set(), {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Invalid record")
        clean = {k: deepcopy(v) for k, v in row.items() if k in FIELDS[collection]}
        ident = row.get("id")
        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
            # Use original fields (no new timestamp) so copies migrate identically.
            fingerprint = hashlib.sha256(canonical(clean).encode()).hexdigest()[:32]
            index = occurrences.get(fingerprint, 0)
            occurrences[fingerprint] = index + 1
            ident = f"legacy_{fingerprint}_{index}"
        if ident in seen:
            raise ValueError("Duplicate record ID")
        seen.add(ident)
        if collection == "chats" and "created" not in clean:
            # Preserve old JSON order; tiny ordinal dates are labelled as legacy.
            clean["created"] = position
        validate_patch(collection, clean)
        result.append({"id": ident, **clean})
    return result


class SyncStore:
    def __init__(self, path, character="shizuka", device=None):
        if not IDENTIFIER.fullmatch(character):
            raise ValueError("Invalid character ID")
        self.path, self.character = Path(path), character
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(device TEXT, seq INTEGER, logical INTEGER,
                collection TEXT, record TEXT, body TEXT NOT NULL, PRIMARY KEY(device,seq));
            CREATE INDEX IF NOT EXISTS events_record ON events(collection,record);
        """)
        with self.transaction():
            existing = self.meta("character")
            if existing and existing != character:
                raise ValueError("Database belongs to a different character")
            self.set_meta("character", character)
            current = self.meta("device")
            if device and current and current != device:
                raise ValueError("Device identity already initialized")
            self.device = current or device or uuid.uuid4().hex
            if not IDENTIFIER.fullmatch(self.device):
                raise ValueError("Invalid device ID")
            self.set_meta("device", self.device)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, canonical(value)))

    def close(self):
        with self.lock:
            self.db.close()

    def _events(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM events ORDER BY logical,device,seq")]

    def _vector(self):
        return dict(self.db.execute("SELECT device,MAX(seq) FROM events GROUP BY device"))

    def _append(self, collection, record, patch, observed_clock=None):
        vector = self._vector()
        context = dict(vector if observed_clock is None else observed_clock)
        context[self.device] = vector.get(self.device, 0)
        seq = vector.get(self.device, 0) + 1
        logical = self.db.execute("SELECT COALESCE(MAX(logical),0)+1 FROM events").fetchone()[0]
        event = {"device": self.device, "seq": seq, "logical": logical, "context": context,
                 "collection": collection, "record": record, "patch": patch}
        self._insert(event)

    def _insert(self, e):
        body = canonical(e)
        old = self.db.execute("SELECT body FROM events WHERE device=? AND seq=?", (e["device"], e["seq"])).fetchone()
        if old:
            if old[0] != body:
                raise ValueError("Device journal collision; do not clone local sync databases")
            return False
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (e["device"], e["seq"], e["logical"], e["collection"], e["record"], body))
        return True

    def _materialize(self, collection, include_deleted=False):
        records = {}
        for event in self._events():
            if event["collection"] != collection:
                continue
            record = records.setdefault(event["record"], {"id": event["record"]})
            deleted = record.get("_deleted", False)
            record.update(event["patch"])
            record["_deleted"] = deleted or record.get("_deleted", False)
        return [dict(row) if include_deleted else {k: v for k, v in row.items() if not k.startswith("_")}
                for row in records.values() if include_deleted or not row.get("_deleted", False)]

    def rows(self, collection):
        if collection not in FIELDS:
            raise ValueError("Invalid collection")
        with self.lock:
            return Snapshot(self._materialize(collection), self._vector())

    def commit_snapshot(self, collection, desired, observed, delete_missing=True):
        """Write only the caller's edits, preserving updates received since its read.

        observed must be the caller's own last returned view, never the current
        remote view. Omitting an unseen remote record is not a deletion.
        """
        wanted = {r["id"]: r for r in stable_rows(collection, desired)}
        before = {r["id"]: r for r in stable_rows(collection, observed)}
        observed_clock = getattr(observed, "clock", None)
        with self.transaction():
            current = {r["id"]: r for r in self._materialize(collection, True)}
            for ident, row in wanted.items():
                if current.get(ident, {}).get("_deleted"):
                    continue  # Explicit restore uses a new ID; stale forms never resurrect.
                previous = before.get(ident, {})
                patch = {k: v for k, v in row.items() if k != "id" and (k not in previous or v != previous[k])}
                if ident not in current:
                    patch["_deleted"] = False
                if patch:
                    self._append(collection, ident, patch, observed_clock)
            if delete_missing:
                for ident in before.keys() - wanted.keys():
                    if not current.get(ident, {}).get("_deleted"):
                        self._append(collection, ident, {"_deleted": True}, observed_clock)
            return Snapshot(self._materialize(collection), self._vector())

    def bundle(self, collections=None):
        selected = set(collections or FIELDS)
        if not selected <= FIELDS.keys():
            raise ValueError("Invalid sync scope")
        with self.lock:
            return {"schema": SCHEMA, "character": self.character, "sender": self.device,
                    "events": [e for e in self._events() if e["collection"] in selected]}

    def import_bundle(self, bundle, collections=None):
        selected = set(collections or FIELDS)
        validate_bundle(bundle, self.character)
        if not selected <= FIELDS.keys():
            raise ValueError("Invalid sync scope")
        with self.transaction():
            count = 0
            for event in bundle["events"]:
                if event["collection"] in selected:
                    count += self._insert(event)
            return count

    def conflicts(self):
        """Report concurrent field edits; both values remain in the journal."""
        with self.lock:
            winners, conflicts = {}, []
            for e in self._events():
                for field, value in e["patch"].items():
                    key = (e["collection"], e["record"], field)
                    previous = winners.get(key)
                    if previous:
                        p, old = previous
                        concurrent = (e["context"].get(p["device"], 0) < p["seq"]
                                      and p["context"].get(e["device"], 0) < e["seq"])
                        if concurrent and value != old:
                            conflicts.append({"collection": key[0], "record": key[1], "field": field,
                                              "other": old, "selected": value,
                                              "devices": [p["device"], e["device"]]})
                    winners[key] = (e, value)
            return conflicts


def validate_bundle(bundle, character):
    if not isinstance(bundle, dict) or set(bundle) != {"schema", "character", "sender", "events"}:
        raise ValueError("Invalid sync envelope")
    if type(bundle["schema"]) is not int or bundle["schema"] != SCHEMA or bundle["character"] != character:
        raise ValueError("Incompatible schema or character")
    if not isinstance(bundle["sender"], str) or not IDENTIFIER.fullmatch(bundle["sender"]):
        raise ValueError("Invalid sender")
    events = bundle["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS or len(canonical(bundle).encode()) > MAX_BYTES:
        raise ValueError("Sync payload too large")
    for e in events:
        if not isinstance(e, dict) or set(e) != {"device", "seq", "logical", "context", "collection", "record", "patch"}:
            raise ValueError("Invalid event")
        if any(not isinstance(e[k], str) or not IDENTIFIER.fullmatch(e[k]) for k in ("device", "record")):
            raise ValueError("Invalid journal identity")
        if any(type(e[k]) is not int or not 1 <= e[k] < 2**53 for k in ("seq", "logical")):
            raise ValueError("Invalid journal counter")
        context = e["context"]
        if not isinstance(context, dict) or len(context) > 128 or any(
            not isinstance(k, str) or not IDENTIFIER.fullmatch(k) or type(v) is not int or not 0 <= v < 2**53
            for k, v in context.items()):
            raise ValueError("Invalid causal context")
        collection, patch = e["collection"], e["patch"]
        validate_patch(collection, patch)


def validate_patch(collection, patch):
    if not isinstance(collection, str) or collection not in FIELDS or not isinstance(patch, dict) or not patch or not patch.keys() <= FIELDS[collection] | {"_deleted"}:
        raise ValueError("Unexpected sync fields")
    for key, value in patch.items():
        if key in {"_deleted", "pinned", "on_boot", "done"} and type(value) is not bool:
            raise ValueError("Invalid boolean")
        if key in {"content", "text", "role", "kind", "device", "turn_id"} and (not isinstance(value, str) or len(value) > 100000):
            raise ValueError("Invalid text")
        if key in {"created", "last_used", "due", "use_count"}:
            if key == "due" and value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15:
                raise ValueError("Invalid number")
