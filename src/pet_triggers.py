"""Local interaction policy. No timers, GUI, network or character artwork."""
import math


class ActionTriggers:
    COOLDOWNS = {"pat": 8.0, "sleep": 300.0, "happy": 60.0}
    GESTURE_COOLDOWNS = {"pat": 8.0, "happy": 5.0}
    IDLE_SECONDS = 60.0
    RETURN_SECONDS = 30.0

    def __init__(self, now):
        self.last_interaction = now
        self.last_started = {}
        self.last_any = -math.inf
        self.source = None
        self.hidden_at = None
        self.return_at = None
        self.clear_stroke()

    def clear_stroke(self):
        self.stroke_start = self.stroke_last = None
        self.stroke_x = None
        self.direction = 0
        self.reversals = 0
        self.distance = 0.0

    def interact(self, now):
        self.last_interaction = now
        self.clear_stroke()

    def stroke(self, x, now, inside, pressed=False):
        """Held strokes are deliberate: a short sweep is enough; hover needs reversals."""
        self.last_interaction = now
        if not inside:
            self.clear_stroke()
            return False
        if (self.stroke_start is None or now-self.stroke_start > 1.6
                or now-self.stroke_last > .5):
            self.clear_stroke()
            self.stroke_start = now
            self.stroke_x = x
        self.stroke_last = now
        delta = x-self.stroke_x
        if abs(delta) < .018:
            return False
        direction = 1 if delta > 0 else -1
        if self.direction and direction != self.direction:
            self.reversals += 1
        self.direction = direction
        self.distance += abs(delta)
        self.stroke_x = x
        if (pressed and self.distance >= .06 or self.reversals >= 2 and self.distance >= .16):
            self.clear_stroke()
            return True
        return False

    def allow(self, action, now, *, manual=False, gesture=False, blocked=False, active=False):
        if action not in self.COOLDOWNS:
            raise ValueError(f"Unknown action: {action}")
        cooldown = self.GESTURE_COOLDOWNS.get(action,2.0) if gesture else 2.0 if manual else self.COOLDOWNS[action]
        if (blocked or active or now-self.last_any < (2.0 if manual else 3.0)
                or now-self.last_started.get(action, -math.inf) < cooldown):
            return False
        self.last_started[action] = self.last_any = now
        self.source = "gesture" if gesture else "manual" if manual else "automatic"
        return True

    def hide(self, now):
        if self.hidden_at is None:
            self.hidden_at = now
        self.return_at = None
        self.interact(now)

    def restore(self, now):
        if self.hidden_at is None:
            return
        duration = now-self.hidden_at
        self.hidden_at = None
        self.interact(now)
        self.return_at = now+.4 if duration >= self.RETURN_SECONDS else None

    def candidate(self, now, system_idle, *, enabled=True, blocked=False):
        if not enabled or blocked:
            self.last_interaction = now
            self.clear_stroke()
            if not enabled:
                self.return_at = None
            elif self.return_at is not None and now-self.return_at > 10:
                self.return_at = None
            return None
        if self.return_at is not None and now >= self.return_at:
            age = now-self.return_at
            self.return_at = None
            if age <= 10:
                return "happy"
        # A missing OS idle reading must never make an active user 'idle'.
        if (system_idle is not None and system_idle >= self.IDLE_SECONDS
                and now-self.last_interaction >= self.IDLE_SECONDS):
            return "sleep"
        return None
