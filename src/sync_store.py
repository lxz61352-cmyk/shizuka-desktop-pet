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
COMPACT_AFTER_EVENTS = 5000   # 热表事件超过这个数就把它们压实进快照并移入归档冷表
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
        self._snapshot_cache = {}   # collection -> (快照正文, 解码结果)
        self.db = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(device TEXT, seq INTEGER, logical INTEGER,
                collection TEXT, record TEXT, body TEXT NOT NULL, PRIMARY KEY(device,seq));
            CREATE INDEX IF NOT EXISTS events_record ON events(collection,record);
            CREATE INDEX IF NOT EXISTS events_collection ON events(collection,logical);
            CREATE TABLE IF NOT EXISTS events_archive(device TEXT, seq INTEGER, logical INTEGER,
                collection TEXT, record TEXT, body TEXT NOT NULL, PRIMARY KEY(device,seq));
            CREATE TABLE IF NOT EXISTS snapshots(collection TEXT PRIMARY KEY, body TEXT NOT NULL);
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
        """热表事件：还没被压实进快照的那部分（本地读路径只用这个）。"""
        return [json.loads(row[0]) for row in
                self.db.execute("SELECT body FROM events ORDER BY logical,device,seq")]

    def _all_events(self):
        """完整历史（热表 + 归档冷表）：bundle()/conflicts() 用。

        压实只影响本地读的代价，对外仍然提供完整事件流——信封格式没变、对端不缺历史、
        冲突检测也不会因为压实而退化。
        """
        rows = self.db.execute("SELECT logical,device,seq,body FROM events").fetchall()
        rows += self.db.execute("SELECT logical,device,seq,body FROM events_archive").fetchall()
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
        return [json.loads(row[3]) for row in rows]

    def _snapshot(self, collection):
        """解码后的快照；按快照正文（stamp）缓存，避免每次读都重新 JSON 解析全部记录。

        调用方都在 self.lock / transaction 之内，且 _materialize 会逐条复制记录、
        不会改到这里缓存的对象，所以缓存可以安全复用。
        """
        row = self.db.execute("SELECT body FROM snapshots WHERE collection=?", (collection,)).fetchone()
        stamp = row[0] if row else None
        cached = self._snapshot_cache.get(collection)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        value = json.loads(stamp) if stamp else None
        self._snapshot_cache[collection] = (stamp, value)
        return value

    def _vector(self):
        vector = {}
        for table in ("events", "events_archive"):
            for device, seq in self.db.execute("SELECT device,MAX(seq) FROM %s GROUP BY device" % table):
                vector[device] = max(vector.get(device, 0), int(seq))
        # 压实过的 seq 记在 meta 里：即使将来把归档也清掉，新事件也不会复用旧序号。
        for device, seq in (self.meta("vector") or {}).items():
            vector[device] = max(vector.get(device, 0), int(seq))
        return vector

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
        # 归档表也要查：对端重发已经压实过的事件时，按 (device,seq) 判为重复而不是重复写入。
        for table in ("events", "events_archive"):
            old = self.db.execute(
                "SELECT body FROM %s WHERE device=? AND seq=?" % table, (e["device"], e["seq"])).fetchone()
            if old:
                if old[0] != body:
                    raise ValueError("Device journal collision; do not clone local sync databases")
                return False
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (e["device"], e["seq"], e["logical"], e["collection"], e["record"], body))
        return True

    def _materialize(self, collection, include_deleted=False):
        """= 快照（已压实的部分）+ 热表里基线之后的事件。"""
        snapshot = self._snapshot(collection)
        baseline = (snapshot or {}).get("baseline") or {}
        records = {row["id"]: dict(row) for row in (snapshot or {}).get("records", [])}
        for event in self._events():
            if event["collection"] != collection:
                continue
            if event["seq"] <= baseline.get(event["device"], 0):
                continue   # 已经包含在快照里，别再回放一遍
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
                    "events": [e for e in self._all_events() if e["collection"] in selected]}

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
            for e in self._all_events():
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

    # ---------------- 压实：本地读加速，历史不丢 ----------------
    def compact(self, force=False):
        """把当前状态写成快照，并把已包含在快照里的事件挪进归档冷表。

        这样 `rows()`/`commit_snapshot()` 只需要回放「快照 + 基线之后的热事件」，
        不用再逐条解析全部历史；而 `bundle()`/`conflicts()` 仍然读完整历史，
        所以对外行为不变（同步信封没变、对端不缺历史、冲突检测不退化）。

        三件不能省的事：
        - 快照记录**基线向量**（每设备最大 seq），回放时跳过基线内事件；
        - 快照保留**墓碑**（_deleted 记录），删除不会被旧事件复活；
        - `_insert` 同时检查归档表，(device,seq) 的幂等/冲突语义保持原样。
        """
        with self.transaction():
            hot = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if not force and hot == 0:
                return {"moved": 0, "events": 0}
            vector = self._vector()
            for collection in FIELDS:
                rows = self._materialize(collection, include_deleted=True)
                self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?)",
                                (collection, canonical({"baseline": dict(vector), "records": rows})))
            self.db.execute("INSERT OR IGNORE INTO events_archive SELECT * FROM events")
            self.db.execute("DELETE FROM events")
            self.set_meta("vector", vector)
            self.set_meta("compacted_at", time.time())
            return {"moved": int(hot), "events": len(vector)}

    def maybe_compact(self, threshold=COMPACT_AFTER_EVENTS):
        """热事件攒够阈值就压实一次；没到阈值返回 None。"""
        with self.lock:
            hot = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if hot < threshold:
            return None
        return self.compact()


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
