"""共同经历存储（原型）：我们之间发生过什么。

只做保存/检索/关联/最近使用；不参与生成行为（Phase 3 由 Context Compiler 读取）。
写入门槛：只能显式 record()；相似条目更新（mention_count+1）而不是追加；
「一次发生 ≠ 共同历史」——是否值得记录由上游（记忆巡检/人工）判断。
"""
import json
import os
import time
import uuid

MAX_ENTRIES = 200
SIM_THRESHOLD = 0.55
MATCH_THRESHOLD = 0.30


def _tokens(text):
    import conversation_memory as cm
    return cm.tokens(text or "")


def _similarity(a, b):
    sa, sb = _tokens(a), _tokens(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


class SharedHistoryStore:
    """轻量共同经历库；落盘 data/shared_history.json。"""

    def __init__(self, data_dir):
        self._path = os.path.join(data_dir or "", "shared_history.json")
        self.entries = []
        self._load()

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.entries = [row for row in (data.get("entries") or []) if isinstance(row, dict)]
        except Exception:
            pass

    def save(self):
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "entries": self.entries}, handle,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            pass

    def record(self, summary, topics=None, people=None, emotion="", importance=0.5, now=None):
        """记录/更新一段共同经历；相似条目原地更新，返回条目 id。"""
        summary = (summary or "").strip()
        if not summary:
            return None
        now = time.time() if now is None else now
        for entry in self.entries:
            if _similarity(summary, entry.get("summary", "")) >= SIM_THRESHOLD:
                entry["mention_count"] = int(entry.get("mention_count") or 0) + 1
                entry["last_seen"] = now
                entry["importance"] = max(float(entry.get("importance") or 0.0), importance)
                if emotion:
                    entry["emotion"] = emotion
                for topic in (topics or []):
                    if topic and topic not in entry.setdefault("topics", []):
                        entry["topics"].append(topic)
                self.save()
                return entry["id"]
        entry = {"id": "sh_" + uuid.uuid4().hex[:10], "summary": summary,
                 "people": list(people or ["user", "shizuka"]), "topics": list(topics or []),
                 "emotion": emotion, "importance": float(importance),
                 "first_seen": now, "last_seen": now, "mention_count": 1}
        self.entries.append(entry)
        if len(self.entries) > MAX_ENTRIES:
            self.entries.sort(key=lambda row: (row.get("importance") or 0, row.get("last_seen") or 0))
            self.entries = self.entries[-MAX_ENTRIES:]
        self.save()
        return entry["id"]

    def touch(self, entry_id, now=None):
        for entry in self.entries:
            if entry.get("id") == entry_id:
                entry["mention_count"] = int(entry.get("mention_count") or 0) + 1
                entry["last_seen"] = time.time() if now is None else now
                self.save()
                return True
        return False

    def match(self, text, topic="", now=None):
        """当前话题是否触发一段共同经历；命中返回最相关条目，否则 None。"""
        text = text or ""
        if not text.strip():
            return None
        best, best_score = None, 0.0
        for entry in self.entries:
            blob = entry.get("summary", "")
            if topic and topic in (entry.get("topics") or []):
                blob += " " + topic
            score = _similarity(text, blob)
            if topic and topic in (entry.get("topics") or []):
                score += 0.2
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= MATCH_THRESHOLD:
            return best
        return None

    def recent(self, limit=5):
        return sorted(self.entries, key=lambda row: row.get("last_seen") or 0, reverse=True)[:limit]
