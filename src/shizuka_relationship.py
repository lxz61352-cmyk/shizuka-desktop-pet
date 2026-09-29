"""慢状态：与用户的关系（说话距离）。

familiarity 每轮有内容的互动就渐近上移（渐近式，永不封顶突跳）；
trust / playfulness / respect / comfort 由事件设置目标，实际值按惯性缓慢逼近。
持久化到 data/relationship_state.json。数值永不注入模型（Phase 2b 才转自然语言）。
"""
import json
import os
import time

INERTIA = 0.90
SAVE_INTERVAL = 60.0
SHARED_HISTORY_PER_ENTRY = 0.15
FAMILIARITY_GAIN = 0.03

TRACKED = ("trust", "playfulness", "respect", "comfort")
BASELINE = {"familiarity": 0.35, "trust": 0.40, "playfulness": 0.35,
            "respect": 0.55, "comfort": 0.50}
LONG_USER_BOOST = {"familiarity": 0.60, "comfort": 0.58, "trust": 0.45}


def _clamp(value):
    return max(0.0, min(1.0, value))


class RelationshipState:
    """慢状态。familiarity 渐近式直涨；其余四维目标只随事件移动。"""

    def __init__(self, data_dir):
        self._path = os.path.join(data_dir or "", "relationship_state.json")
        self.values = dict(BASELINE)
        self.targets = {dim: BASELINE[dim] for dim in TRACKED}
        self.entries = []
        self._quiet_turns = 0
        self._last_save = 0.0
        self._load()

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
            for dim in list(BASELINE):
                self.values[dim] = _clamp(float(data.get(dim, self.values[dim])))
            for dim in TRACKED:
                self.targets[dim] = self.values[dim]
            self.entries = data.get("shared_entries") or []
            self._quiet_turns = int(data.get("quiet_turns") or 0)
        except Exception:
            pass

    def boost_for_memories(self, count):
        """长期用户起点：记忆库已有一定存量时，关系不再是全新起步。"""
        if count < 10:
            return
        for dim, value in LONG_USER_BOOST.items():
            if self.values[dim] < value:
                self.values[dim] = value
            if dim in self.targets and self.targets[dim] < value:
                self.targets[dim] = value

    def observe(self, situation, state=None):
        kind = situation.get("kind") or ""
        if kind in ("empty_call", "empty_filler"):
            if getattr(state, "empty_streak", 0) >= 3:
                self.targets["comfort"] = _clamp(self.targets["comfort"] - 0.03)
        elif kind in ("task", "ask_help", "question"):
            # 近似：用户求助即 +信任（规格里「确实帮上」的验证留到 Phase 4）
            self.targets["trust"] = _clamp(self.targets["trust"] + 0.04)
            self._gain_familiarity()
        elif kind == "praise":
            self.targets["comfort"] = _clamp(self.targets["comfort"] + 0.03)
            self._gain_familiarity()
        elif kind == "tease":
            self.targets["playfulness"] = _clamp(self.targets["playfulness"] + 0.04)
            self._gain_familiarity()
        elif kind == "challenge":
            self.targets["respect"] = _clamp(self.targets["respect"] - 0.05)
        elif kind in ("greeting", "goodbye", "boundary"):
            pass
        else:
            self._gain_familiarity()
            self._quiet_turns += 1
            if self._quiet_turns % 10 == 0:
                self.targets["comfort"] = _clamp(self.targets["comfort"] + 0.02)
        for dim in TRACKED:
            self.values[dim] = _clamp(self.values[dim] * INERTIA + self.targets[dim] * (1 - INERTIA))
        self._save_if_due()

    def _gain_familiarity(self):
        value = self.values["familiarity"]
        self.values["familiarity"] = _clamp(value + (1 - value) * FAMILIARITY_GAIN)

    def shared_history(self):
        return _clamp(SHARED_HISTORY_PER_ENTRY * len(self.entries))

    def snapshot(self):
        data = dict(self.values)
        data["shared_history"] = self.shared_history()
        return data

    def _save_if_due(self):
        now = time.time()
        if now - self._last_save < SAVE_INTERVAL:
            return
        self._last_save = now
        self.save()

    def save(self):
        try:
            data = dict(self.values)
            data["shared_entries"] = self.entries
            data["quiet_turns"] = self._quiet_turns
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            pass
