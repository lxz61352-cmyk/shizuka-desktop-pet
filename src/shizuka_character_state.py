"""快状态：当前这一会儿的静香。

十个维度随对话快速变化：每轮先向基线回落（惯性 0.80），再按事件叠加。
进程内、不落盘；数字只活在程序里（Phase 2b 才转成自然语言注入）。
"""
import time

DIMENSIONS = ("playfulness", "confidence", "competitiveness", "protectiveness", "curiosity",
              "self_expression", "social_openness", "embarrassment", "seriousness", "attachment")
BASELINE = {"playfulness": 0.40, "confidence": 0.55, "competitiveness": 0.35, "protectiveness": 0.15,
            "curiosity": 0.45, "self_expression": 0.50, "social_openness": 0.60,
            "embarrassment": 0.10, "seriousness": 0.35, "attachment": 0.50}
INERTIA = 0.80
IDLE_EXTRA_STEP = 900.0

BUMP = {
    "praise": {"embarrassment": 0.25, "confidence": 0.05},
    "tease": {"playfulness": 0.10},
    "challenge": {"competitiveness": 0.20, "confidence": 0.10, "social_openness": -0.10},
    "share_negative": {"seriousness": 0.05, "playfulness": -0.05},
    "task": {"seriousness": 0.15},
    "ask_help": {"seriousness": 0.15},
    "share_casual": {"curiosity": 0.10},
    "share_achievement": {"curiosity": 0.10},
    "question": {"curiosity": 0.05},
    "心菜": {"attachment": 0.10},
    "表演": {"seriousness": 0.10, "self_expression": 0.10, "competitiveness": 0.05},
    "boundary": {"protectiveness": 0.25},
}


def _clamp(value):
    return max(0.0, min(1.0, value))


class CharacterState:
    """当前状态：每轮回落基线 + 事件顶升；隔 15 分钟以上再收到消息时多回落半档。"""

    def __init__(self):
        self.values = dict(BASELINE)
        self._last_step = None

    def step(self, situation, state=None, now=None):
        now = time.time() if now is None else now
        idle_boost = self._last_step is not None and now - self._last_step > IDLE_EXTRA_STEP
        self._decay(extra=idle_boost)
        self._last_step = now

        kind = situation.get("kind") or ""
        topic = situation.get("topic") or ""
        bumps = dict(BUMP.get(kind) or {})
        for dim, delta in (BUMP.get(topic) or {}).items():
            bumps[dim] = bumps.get(dim, 0.0) + delta
        if kind in ("empty_call", "empty_filler") and getattr(state, "empty_streak", 0) >= 2:
            bumps["social_openness"] = bumps.get("social_openness", 0.0) - 0.08
            bumps["playfulness"] = bumps.get("playfulness", 0.0) - 0.05
        for dim, delta in bumps.items():
            if dim in self.values:
                self.values[dim] = _clamp(self.values[dim] + delta)

    def _decay(self, extra=False):
        factor = 1 - INERTIA
        if extra:
            factor = min(1.0, factor * 2)
        for dim in DIMENSIONS:
            self.values[dim] += (BASELINE[dim] - self.values[dim]) * factor

    def snapshot(self):
        return dict(self.values)
