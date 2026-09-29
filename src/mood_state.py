"""隐性状态层：精力 / 清醒度 / 意愿 / 耐心等短期状态。

只影响表达倾向，不改变事实与功能：状态差不能拒绝功能请求、不能冷落或攻击用户、
不能声称身体疲劳或需要睡觉。数值不直接给模型，只给「偏低的精力」这类自然语言描述。
"""
import random
import re
import time
from collections import deque

WINDOW_SECONDS = 600          # 近期行为窗口（10 分钟）
INERTIA = 0.85                # 状态惯性：新值 = 旧值*0.85 + 目标*0.15
DRIFT_SIGMA = 0.015           # 每轮微小随机漂移
POSITIVE_RE = ('哈哈', '笑死', '好耶', '可爱', '谢谢', '不错', '厉害', '开心', '草', '好活')
CORRECTION_RE = ('不对', '不是这样', '重新', '再算', '再讲', '错了', '有问题', '为什么不是', '再来', '算了')
QUESTION_RE = ('？', '?', '吗', '呢', '怎么', '为什么', '如何', '是不是', '能不能')
DONE_RE = ('搞定', '弄好', '做完', '写完', '弄完', '完成', '交上', '过了')

# 安全边界：状态只影响表达，永远不能越过这些线。
MOOD_SAFETY_LIMITS = ('不辱骂、不贬低、不威胁用户，不制造关系压力，不说「都是因为你」，不故意冷落；'
                      '不因状态拒绝正常功能请求、不影响程序功能、不向用户报出状态数值。'
                      '可以表现出「有点困」「想收尾」「今天没什么精神」这类角色化倾向，'
                      '但不要把模拟状态说成真实生理事实：不声称自己存在人体意义上的疲劳、睡眠需求或身体不适。')

# 清醒度按时间平滑插值（0 点最低，上午到中午最高）
_ALERTNESS_POINTS = ((0, 0.18), (6, 0.32), (9, 0.72), (13, 0.78), (17, 0.66), (21, 0.42), (24, 0.20))


def _lerp(points, hour):
    for (h1, v1), (h2, v2) in zip(points, points[1:]):
        if h1 <= hour <= h2:
            ratio = (hour - h1) / max(1e-6, h2 - h1)
            return v1 + (v2 - v1) * ratio
    return points[-1][1]


def alertness_target(now=None):
    now = time.time() if now is None else now
    local = time.localtime(now)
    return _lerp(_ALERTNESS_POINTS, local.tm_hour + local.tm_min / 60)


def _clamp(value):
    return max(0.0, min(1.0, value))


def night_line_allowed(kind, text):
    """深夜催睡行只在她明确要收尾、或用户在问睡觉相关的事时允许注入。"""
    if kind == "goodbye":
        return True
    return bool(kind in ("question", "ask_help") and re.search(r"睡|困|熬夜", text or ""))


def _is_positive(text):
    return any(word in text for word in POSITIVE_RE)


def _is_correction(text):
    return any(word in text for word in CORRECTION_RE)


def _looks_like_question(text):
    return any(mark in text for mark in QUESTION_RE)


def _similar(a, b):
    """两段话的字符二元组重合度（0~1），用来识别用户反复问同一件事。"""
    if not a or not b:
        return 0.0
    sa = {a[i:i + 2] for i in range(len(a) - 1)}
    sb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


# ── 即时情绪反应：听到这一句话的第一反应（每轮临时，不落盘、不调模型）──
EMOTION_HINTS = {
    'amused': '有点好笑',
    'annoyed': '有点烦、有点无奈',
    'warm': '心里软了一下',
    'concerned': '有点在意、担心',
    'embarrassed': '有点不好意思',
    'curious': '有点好奇',
    'skeptical': '不太信',
    'proud': '有点得意、满意',
    'relieved': '松了口气，也替对方高兴',
    'impatient': '有点不耐烦',
    'touched': '被戳到了一下',
    'surprised': '有点意外',
    'awkward': '有点不知道该怎么接',
    'playful': '想逗一句',
    'tired': '提不起劲',
    'indifferent': '没什么感觉',
}

EMOTION_RULE = ('【即时情绪反应】\n'
                '你不是没有个人反应的问答系统：先产生静香自己的第一反应，再决定说不说、说多少。'
                '不要把情绪名称说出来，也不要解释自己的心理——让语气、措辞、句长、是否接话、'
                '是否调侃自然带出来。不要每次都温柔、理性、耐心、正确；不要把关心自动变成建议清单。'
                '反应本身就可以是完整回应；已经表达了明显反应，就不要追加完整的帮助流程。')


def infer_emotion(text, mood=None, state=None):
    """规则给一个很弱的倾向；判不了返回 (None, 0.0)，交给主模型自己判断。"""
    text = (text or '').strip()
    if not text:
        return None, 0.0
    if re.search(r'(?:你|静香)[^。！？!?]{0,8}(?:可爱|好懂|厉害|真好|温柔|帅)|你怎么这么(?:懂|好)', text):
        return 'embarrassed', 0.6
    if re.search(r'(?:你|静香).{0,12}(?:根本|一点也)?不在乎(?:我|这件事|这个)?', text):
        return 'annoyed', 0.65
    if re.search(r'(?:不去|不想|放弃|不争取).{0,12}(?:难得|重要|机会)', text):
        return 'surprised', 0.65
    if re.search(r'敷衍|你是不是|真的假的|骗我|糊弄|又在骗', text):
        return 'skeptical', 0.6
    if re.search(r'你好笨|真笨|太笨|这么笨|好笨|笨死|好蠢|闭嘴|烦人|讨厌你', text):
        return 'annoyed', 0.6
    if re.search(r'废物|没用|不行|做不好|配不上|太菜|完蛋', text):
        return 'annoyed', 0.4
    if re.search(r'搞砸|删了|忘了|崩了|坏了|丢了|出错了', text):
        return 'surprised', 0.5
    if re.search(r'搞定了|弄好了|做完了|写完了|完成了|解决了|处理好了|终于.{0,8}(?:完|好|解决|处理)', text):
        return 'relieved', 0.65 if '终于' in text else 0.5
    if re.search(r'哈哈|笑死|好耶|逗你|开玩笑|可爱|不错嘛', text):
        return 'amused', 0.4
    if re.search(r'好累|累死|心累|难受|好烦|烦死|委屈|想哭|撑不住|状态不太好|状态很差', text):
        return 'concerned', 0.5
    if mood is not None and mood.energy < 0.3 and mood.alertness < 0.3:
        return 'tired', 0.4
    if mood is not None and getattr(mood, 'mood', 1.0) < 0.3 and len(text) <= 20:
        return 'indifferent', 0.4
    if state is not None and getattr(state, 'last_user_text', ''):
        if len(text) <= 40 and _similar(text, state.last_user_text) >= 0.6:
            return 'impatient', 0.5
    if state is not None and getattr(state, 'last_emotion', None) in (
            'annoyed', 'skeptical', 'touched', 'concerned') and len(text) <= 8:
        return state.last_emotion, 0.3
    return None, 0.0


def emotion_instruction(label=None, intensity=0.0):
    text = EMOTION_RULE
    if label and label in EMOTION_HINTS:
        level = '明显' if intensity >= 0.6 else '轻微'
        text += '\n本轮第一反应偏向：%s（%s）。先把这反应带进语气里，不必说出来。' % (EMOTION_HINTS[label], level)
        if intensity >= 0.6:
            text += '\n这次不要只给中性的确认句；让人能从措辞和语气直接听出这份反应，但不要夸张表演。'
        if label == 'relieved':
            text += '\n可以直接替对方高兴或松口气；不要改写成“你现在应该轻松了”这类替对方断定感受的话。'
    return text


class MoodState:
    """进程内的短期状态；不落盘，重启回到按时间推算的基线。"""

    def __init__(self, now=None):
        now = time.time() if now is None else now
        self.energy = 0.65
        self.alertness = alertness_target(now)
        self.willingness = 0.75
        self.patience = 0.72
        self.engagement = 0.6
        self.cheerfulness = 0.6
        self.warmth = 0.7
        self.tension = 0.15
        # 总体心情：随互动缓慢积累（好互动 +，纠正/重复/纠缠 −），惯性跟其他状态一致。
        # 只以自然语言进入提示词，不给模型看数值。
        self.mood = 0.62
        self._events = deque(maxlen=32)
        self.recent_events = deque(maxlen=3)
        self._last_interaction = now
        self._last_day = time.localtime(now).tm_yday
        self.load = 0.0

    # ---------- 输入 ----------
    def observe_user(self, text, now=None):
        now = time.time() if now is None else now
        idle = now - self._last_interaction
        self._recover(now)
        day = time.localtime(now).tm_yday
        if day != self._last_day:            # 跨天：临时状态基本重置
            self.__init__(now)
            return
        self._last_interaction = now
        text = (text or '').strip()
        kind = 'msg'
        if _looks_like_question(text):
            kind = 'question'
        if _is_correction(text):
            kind = 'correction'
        if _is_positive(text):
            kind = 'positive'
        if any(word in text for word in DONE_RE) and len(text) <= 30:
            kind = 'done'
        self._events.append((now, kind, len(text), text))
        self._note_events(now, idle)

    def _note_events(self, now, idle):
        """只留最近 1~3 件小事，作为状态背景（不是系统诊断）。"""
        window = self._window(now)
        if idle >= 900:
            self._push_event('刚刚有一段时间没收到消息')
        if sum(1 for row in window if row[1] == 'positive') >= 2:
            self._push_event('刚才用户心情不错')
        if sum(1 for row in window if row[1] == 'correction') >= 3:
            self._push_event('刚才用户反复修改要求')
        if sum(1 for row in window if row[1] == 'question') >= 5:
            self._push_event('刚才连续处理了很多问题')
        if any(row[1] == 'done' for row in window[-3:]):
            self._push_event('刚才完成了一件事')

    def _push_event(self, text):
        if text in self.recent_events:
            return
        self.recent_events.append(text)

    def observe_reply(self, reply):
        """回复长度反过来影响精力/意愿：连续长篇之后更容易累。"""
        size = len((reply or '').strip())
        if size > 400:
            self.energy = _clamp(self.energy - 0.02)
        elif size and size < 30:
            self.patience = _clamp(self.patience + 0.01)

    # ---------- 内部 ----------
    def _window(self, now, seconds=WINDOW_SECONDS):
        return [row for row in self._events if now - row[0] <= seconds]

    def _recover(self, now):
        idle = now - self._last_interaction
        if idle >= 300:
            minutes = min(idle / 60.0, 180.0)
            self.patience = _clamp(self.patience + 0.02 * minutes / 5)
        if idle >= 900:
            self.willingness = _clamp(self.willingness + 0.15)
            self.tension = _clamp(self.tension - 0.1)
        if idle >= 3600:
            self.energy = _clamp(self.energy + 0.2)

    def _targets(self, now):
        window = self._window(now)
        total = len(window)
        minutes = max(1.0, min(60.0, (now - self._events[0][0]) / 60.0)) if window else 10.0
        rate = total / minutes                                  # 条/分钟
        avg_len = sum(row[2] for row in window) / total if total else 20
        question_ratio = sum(1 for row in window if row[1] == 'question') / total if total else 0
        corrections = sum(1 for row in window if row[1] == 'correction')
        positives = sum(1 for row in window if row[1] == 'positive')
        correction_ratio = corrections / total if total else 0
        positive_ratio = positives / total if total else 0
        dones = sum(1 for row in window if row[1] == 'done')
        done_ratio = dones / total if total else 0
        texts = [row[3] for row in window if row[3]]
        repeated = sum(1 for index in range(1, len(texts)) if _similar(texts[index], texts[index - 1]) >= 0.6)
        repeat_ratio = repeated / len(texts) if texts else 0

        load = (min(1.0, rate / 4) * 0.35 + min(1.0, avg_len / 120) * 0.15
                + question_ratio * 0.25 + min(1.0, correction_ratio * 3) * 0.15
                + min(1.0, repeat_ratio * 2) * 0.1)
        self.load = _clamp(load)

        late = 1.0 if time.localtime(now).tm_hour >= 23 or time.localtime(now).tm_hour < 6 else 0.0
        mood = (0.62 + 0.18 * positive_ratio + 0.10 * min(1.0, done_ratio * 2)
                - 0.28 * correction_ratio - 0.22 * repeat_ratio - 0.10 * load - 0.08 * late)
        energy = 0.75 - 0.4 * load - 0.12 * late
        willingness = 0.82 - 0.5 * load + 0.06 * positive_ratio
        patience = 0.78 - 0.55 * load + 0.05 * positive_ratio
        engagement = 0.45 + 0.35 * question_ratio + 0.2 * min(1.0, rate / 3)
        cheerfulness = 0.6 + 0.25 * positive_ratio - 0.12 * correction_ratio
        warmth = 0.72 - 0.2 * load + 0.08 * positive_ratio
        tension = 0.12 + 0.45 * correction_ratio
        return {'energy': energy, 'willingness': willingness, 'patience': patience,
                'engagement': engagement, 'cheerfulness': cheerfulness, 'warmth': warmth,
                'tension': tension, 'mood': mood}

    def update(self, now=None):
        now = time.time() if now is None else now
        targets = self._targets(now)
        targets['alertness'] = alertness_target(now)
        for name, target in targets.items():
            old = getattr(self, name)
            value = old * INERTIA + target * (1 - INERTIA) + random.gauss(0, DRIFT_SIGMA)
            setattr(self, name, _clamp(value))

    # ---------- 输出 ----------
    @staticmethod
    def _level(value):
        if value < 0.2:
            return '很低'
        if value < 0.4:
            return '偏低'
        if value < 0.6:
            return '正常'
        if value < 0.8:
            return '较高'
        return '很高'

    def summary(self, now=None, night_line=True):
        """给模型的状态倾向：只列明显偏离的项，不含数字；无事可报时返回空串。

        night_line=False 时跳过深夜催睡行（P2c：深夜不再无条件催睡，
        只有用户确实在收尾/说困时才提醒）。
        """
        now = time.time() if now is None else now
        self.update(now)
        hour = time.localtime(now).tm_hour
        night = hour >= 23 or hour < 6    # 夜里她反而更清醒：夜间不再报「清醒度低」，避免和角色卡冲突
        lines = []
        if self.mood >= 0.74:
            lines.append('今天心情不错，语气可以松一点')
        elif self.mood < 0.32:
            lines.append('今天提不起劲，不太想说话')
        elif self.mood < 0.48:
            lines.append('今天兴致一般，话不多')
        # 心情已经很低时不再逐项叠加精力/意愿/耐心，避免同一件事说四遍
        low_mood = self.mood < 0.32
        if self.alertness < 0.4 and not night:
            lines.append('清醒度' + self._level(self.alertness))
        if self.energy < 0.42 and not low_mood:
            lines.append('精力' + self._level(self.energy))
        if self.willingness < 0.4 and not low_mood:
            lines.append('连续聊天的意愿' + self._level(self.willingness) + '，可以更简短')
        if self.patience < 0.45 and not low_mood:
            lines.append('耐心' + self._level(self.patience))
        if self.tension > 0.45:
            lines.append('有点紧绷')
        if self.warmth > 0.82:
            lines.append('比平时更温和')
        if night_line and (self.alertness < 0.5 or self.energy < 0.5):
            if night:
                lines.append('已经很晚：她夜里反而更清醒，但觉得用户该睡了，可以直接催、嫌他磨蹭，不必继续认真回应')
            elif 22 <= hour < 23:
                lines.append('夜深了：她开始不太想接话，可以更明显一点地表达该收尾了')
            elif 20 <= hour < 22 and (self.energy < 0.5 or self.willingness < 0.5):
                lines.append('时间不早：可以自然提一句差不多该收尾了')
        if self.recent_events:
            lines.append('最近：' + '；'.join(self.recent_events) + '（只当背景，不要复述成系统说明）')
        if not lines:
            return ''
        return '当前状态倾向：' + '；'.join(lines) + '。' + MOOD_SAFETY_LIMITS
