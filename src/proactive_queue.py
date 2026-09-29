"""主动对话意图队列：说不出口就攒着，带 TTL 与优先级，过时作废。

和 LingChat 的「小本本」同一思路，但保持轻量：不落盘、不额外调模型。
类型优先级（高值先投）：reminder(4) > todo(2) > screen(1) > topic(0)
TTL：reminder 1800s / todo 600s / screen 120s / topic 900s（屏幕内容过时就别说了）
"""
import time

TTL = {'reminder': 1800, 'todo': 600, 'screen': 120, 'topic': 900}
PRIORITY = {'reminder': 4, 'todo': 2, 'screen': 1, 'topic': 0}

# 感知状态 → 兴趣修正（挂机更容易主动，工作/游戏更克制）
PERCEPTION_MODIFIER = {'挂机': 15, '浏览': 10, '轻度活动': 0, '工作': -10, '游戏/全屏': -15}


def classify_activity(idle_seconds, exe, quiet=False):
    """按空闲时长 + 前台程序粗分用户状态；纯函数，便于测试。"""
    exe = (exe or '').lower()
    if quiet:
        return '游戏/全屏'
    if idle_seconds is None:
        idle_seconds = 0
    if idle_seconds >= 900:
        return '挂机'
    work_apps = ('code.exe', 'pycharm64.exe', 'devenv.exe', 'winword.exe', 'excel.exe',
                 'wps.exe', 'powerpnt.exe', 'notepad.exe', 'sublime_text.exe')
    browse_apps = ('chrome.exe', 'msedge.exe', 'firefox.exe', 'iexplore.exe')
    if exe in work_apps:
        return '工作'
    if exe in browse_apps:
        return '浏览'
    return '轻度活动'


class ProactiveIntent:
    __slots__ = ('kind', 'text', 'created', 'ttl', 'priority', 'todo_id', 'due', 'snapshot', 'source')

    def __init__(self, kind, text, todo_id=None, due=None, snapshot=None, source=None,
                 ttl=None, created=None):
        self.kind = kind
        self.text = text
        self.todo_id = todo_id
        self.due = due
        self.snapshot = snapshot
        self.source = source or kind
        self.created = time.time() if created is None else created
        self.ttl = TTL.get(kind, 600) if ttl is None else ttl
        self.priority = PRIORITY.get(kind, 0)

    @property
    def expired(self):
        return time.time() - self.created > self.ttl

    def as_dict(self):
        return {'text': self.text, 'todo_id': self.todo_id, 'due': self.due}


class ProactiveQueue:
    def __init__(self, clock=None):
        self._items = []
        self._clock = clock or time.time

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def push(self, intent):
        self._items.append(intent)
        self.prune()

    def prune(self):
        now = self._clock()
        self._items = [item for item in self._items if now - item.created <= item.ttl]

    def by_kind(self, kind):
        self.prune()
        return [item for item in self._items if item.kind == kind]

    def remove(self, intent):
        try:
            self._items.remove(intent)
        except ValueError:
            pass

    def clear_kind(self, kind):
        self._items = [item for item in self._items if item.kind != kind]

    def replace_kind(self, kind, intents):
        self.clear_kind(kind)
        for intent in intents:
            self._items.append(intent)
        self.prune()

    def pop_ready(self, kinds=None):
        """按优先级取一条（不删除）；调用方投放成功后自行 remove。"""
        self.prune()
        candidates = [item for item in self._items if kinds is None or item.kind in kinds]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item.priority, item.created))
        return candidates[0]
