"""One non-blocking typing lifecycle spanning queued work and every reply segment."""
import threading
import time


class TypingState:
    def __init__(self, client, peer, interval=5):
        self.client, self.peer, self.interval = client, peer, interval
        self.condition = threading.Condition()
        self.pending = {}
        self.closed = False
        self.thread = None
        self.dirty = False
        self.ticket = ''
        self.ticket_at = 0
        self.showing = False
        self.last = 0

    def begin(self, key, context):
        with self.condition:
            if self.closed:
                return
            self.pending[key] = context
            self.dirty = True
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='weixin-typing', daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def finish(self, *keys):
        with self.condition:
            for key in keys:
                self.pending.pop(key, None)
            self.dirty = True
            self.condition.notify_all()

    def refresh(self):
        # A delivered message can clear the client's indicator; renew between parts.
        with self.condition:
            self.dirty = True
            self.condition.notify_all()

    def clear(self, close=False):
        with self.condition:
            self.pending.clear()
            self.closed = self.closed or close
            self.dirty = True
            self.condition.notify_all()

    def _sync(self, context):
        try:
            if context:
                if not self.ticket or time.monotonic() - self.ticket_at > 600:
                    config = self.client.get_config(self.peer, context)
                    ticket = config.get('typing_ticket') if isinstance(config, dict) else None
                    if not isinstance(ticket, str) or not ticket:
                        return
                    self.ticket, self.ticket_at = ticket, time.monotonic()
                # Mark before I/O: an uncertain start must still be cancelled later.
                self.showing = True
                self.client.send_typing(self.peer, self.ticket, 1)
            elif self.showing and self.ticket:
                self.client.send_typing(self.peer, self.ticket, 2)
                self.showing = False
        except Exception:
            # Typing is advisory. It never blocks or cancels the actual reply.
            if context:
                self.ticket_at = 0

    def _run(self):
        while True:
            with self.condition:
                context = next(reversed(self.pending.values()), '')
                due = time.monotonic() - self.last >= self.interval
                if not self.dirty and not (context and due):
                    self.condition.wait(self.interval)
                    continue
                self.dirty = False
                closed = self.closed
            self._sync(context)
            self.last = time.monotonic()
            if closed:
                return
