"""Bounded message delivery, optional continuation, and cancellable pacing."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import threading

REVISION = 'weixin-segments-v1'
BREAK = '[[WX_BREAK]]'
MORE = '[[WX_MORE]]'
END = '[[WX_END]]'
# 空行分条的门槛：这一段攒够这么多字才算一条独立消息。
#
# 调过两次：
#   · 无门槛（任何空行都拆）——拆成多条的比率从 14% 涨到 76%，用户反馈"每条都回两句以上"；
#   · 50 字——又太保守，「哦，是搬快递搬哭了。／几个啊，多到这种程度」这种
#     两段都不短（10 字 + 10 字）却被并成一个气泡，用户反馈"还是没分气泡"。
#
# 现在定 6：**两段都不止一两个字就拆**——这正是人发微信的习惯，
# 只有「嗯。」这种极短的开头才并进后一条。
SPLIT_MIN_CHARS = 6
INSTRUCTION = (
    '【微信分条发送】你可以像发微信一样分条，也可以只发一条。'
    '需要分开两个意思时，在两条之间单独写 [[WX_BREAK]]，最多用两次；直接空一行，程序同样会分开送达。'
    '一条写完就能先送达，不必先加“嗯、懂、收到”占位，也不必固定先回应再提问。'
    '分条只改变发送节奏，不增加本来没必要说的内容；用户告别或暂时离开，就回应告别，不借分条追加叮嘱或开新话题。'
    '讲题要完整，公式、代码块和一个推导步骤内部不分条。'
    '如果这次已说的内容之外还有具体想补的一点，可以在末尾写 [[WX_MORE]]，程序会再给你一次接着说的机会；'
    '已经说完或已经问了等用户回答的问题，就直接结束，不写它。只输出发给用户的正文和上述标记。'
)
CONTINUATION = (
    '【一次补充机会】上面的 assistant 正文已经逐条发给用户。'
    '如果确实还有与当前话题相关、尚未说过的内容，可以再补一条；没有就只输出 [[WX_END]]。'
    '不要重复、改写或解释刚才的回答，不要为了接话新增建议或臆测用户的经历、处境。'
    '用户的问题已经回答完整就可以停；可以问你确实想知道且尚不知道的事，但不要机械追问。'
    '保持用户原有的表达偏好与限制；这次最多一条，不能再申请补充，不输出思考过程。'
)


@dataclass(frozen=True)
class DeliveredReply:
    text: str
    status: str = 'complete'


def split_long(text, limit=1400):
    """Prefer paragraph/line boundaries; never drop the tail of a long explanation."""
    text = text.strip()
    offset = 0
    boundaries = []
    fenced = False
    for match in re.finditer(r'```|\n\n|\n|[。！？!?](?:[”」』])?', text):
        if match.group() == '```':
            fenced = not fenced
        elif not fenced:
            boundaries.append(match.end())
    while len(text) - offset > limit:
        # Prefer boundaries outside fenced code. A single oversized code block
        # still needs a transport split, but its text is preserved verbatim.
        candidates = [at for at in boundaries if offset + limit // 3 <= at <= offset + limit]
        at = candidates[-1] if candidates else offset + limit
        yield text[offset:at]
        offset = at
    if text[offset:]:
        yield text[offset:]


class ReplyProgress:
    """Callable status callback plus transport confirmed segmented delivery."""
    def __init__(self, status, send, cancel, stopped, checkpoint=None, delay=True):
        self.status, self.send = status, send
        self.cancel, self.stopped = cancel, stopped
        self.checkpoint = checkpoint or (lambda text: None)
        self.superseded = threading.Event()
        self.sent = []
        self.attempts = 0
        self.failed = False
        self.delay = delay
        self.on_complete = None

    def finish_delivery(self, success):
        callback, self.on_complete = self.on_complete, None
        if callback is not None:
            callback(bool(success) and not self.interrupted())

    def __call__(self, value):
        self.status(value)

    def interrupted(self):
        return self.cancel.is_set() or self.stopped.is_set() or self.superseded.is_set()

    def emit(self, text, on_sent):
        for piece in split_long(text):
            if self.sent and self.delay:
                # Brief, interruptible spacing; no artificial typo or long wait.
                seconds = min(1.2, .25 + len(piece) * .008)
                if self.superseded.wait(seconds) or self.interrupted():
                    return False
            if self.interrupted():
                return False
            index = self.attempts
            self.attempts += 1
            try:
                self.send(piece, index, self.interrupted)
            except InterruptedError:
                return False
            except Exception:
                self.failed = True
                raise
            self.sent.append(piece)
            on_sent(piece)
            self.checkpoint('\n\n'.join(self.sent))
        return True


def control_matches(text):
    """Code examples can mention the wire format without becoming commands."""
    spans = [(m.start(), m.end()) for m in re.finditer(r'```[\s\S]*?(?:```|$)|`[^`\n]*`', text)]
    return [m for m in re.finditer(r'\[\[WX_(?:BREAK|MORE|END)\]\]|\[\[WX_[A-Z_]*(?:\]\]?)?$', text)
            if not any(start <= m.start() < end for start, end in spans)]


def blank_breaks(text):
    """空行也是分条边界——但**要够长才算**。

    实测 167 条微信回复里没有一条写过 [[WX_BREAK]]——模型一直用空行分段，而分条器只认标记，
    于是"分条"在这条 profile 上从来没生效过，回复整段发出去。用户要求把空行也当分条。

    但**没有门槛的版本会拆过头**：实测拆成多条的比率从 14% 涨到 76%，
    一条十几字的回复也被拆成两三条送达，体感就成了"每条消息都回好几条"。
    所以空行只在"这一段已经攒够长"时才算边界（见 `_next_cut` 里的 SPLIT_MIN_CHARS）。

    代码块与行内代码里的空行不算；流式期间未闭合的围栏会一直匹配到缓冲区末尾，
    所以代码中途不会被切开。
    """
    spans = [(m.start(), m.end()) for m in re.finditer(r'```[\s\S]*?(?:```|$)|`[^`\n]*`', text)]
    return [m for m in re.finditer(r'\n[ \t]*\n[ \t]*', text)
            if not any(start <= m.start() < end for start, end in spans)]


def clean_control(text):
    for match in reversed(control_matches(text)):
        replacement = '\n\n' if match.group() == BREAK else ''
        text = text[:match.start()] + replacement + text[match.end():]
    return text.strip()


class SegmentBuffer:
    def __init__(self):
        self.pending = ''
        self.breaks = 0

    def _next_cut(self):
        """下一个分条位置，返回 (起点, 要吃掉的长度)；没有就返回 None。

        [[WX_BREAK]] 是模型明确要求分条，一律照办；空行要看已经攒了多少字——
        短回复不拆，免得一条十几字的话被拆成两三条送达。
        """
        cuts = []
        for match in control_matches(self.pending):
            if match.group() == BREAK:
                cuts.append((match.start(), match.end() - match.start()))
        blanks = blank_breaks(self.pending)
        if blanks and len(re.sub(r'\s', '', self.pending[:blanks[0].start()])) >= SPLIT_MIN_CHARS:
            match = blanks[0]
            cuts.append((match.start(), match.end() - match.start()))
        return min(cuts) if cuts else None

    def feed(self, delta):
        self.pending += delta
        ready = []
        while self.breaks < 2:
            cut = self._next_cut()
            if cut is None:
                break
            at, width = cut
            ready.append(self.pending[:at])
            self.pending = self.pending[at+width:]
            self.breaks += 1
        return ready

    def finish(self):
        value = self.pending
        self.pending = ''
        matches = control_matches(value.rstrip())
        more = bool(matches and matches[-1].group() == MORE and matches[-1].end() == len(value.rstrip()))
        return value, more


def repeated(text, previous):
    compact = lambda s: re.sub(r'[\W_]+', '', s)
    value = compact(text)
    return bool(value) and any(value in compact(old) or SequenceMatcher(None, value, compact(old)).ratio() >= .8 for old in previous)


def waiting_for_user(text):
    # Colloquial questions often have no question mark. This only suppresses an
    # optional extra generation; it never rewrites or removes the actual answer.
    return bool(re.search(r'[?？]|(?:^|[。\n！？!?，,])\s*(?:你)?(?:哪[家个里儿种部张位天]|什么|怎么|'
                          r'为啥|为什么|几[点个次]|多少|有没有|要不要|是不是)|'
                          r'[吗么呢][。！!…\s]*$|快说|告诉我|跟我说', text))


def user_ends_turn(messages):
    """Suppress only an optional second generation after a clear user sign-off.

    Never truncate the first answer. Questions and requests take precedence,
    even when the same message mentions leaving. Quoted/pasted sign-offs and
    long material messages are intentionally not classified by this small gate.
    """
    content=next((m.get('content') for m in reversed(messages) if m.get('role')=='user'),None)
    if not isinstance(content,str) or len(content)>160:
        return False
    if re.search(r'[?？“”「」"\']|(?:帮我|告诉我|解释|讲一下|继续|发我|算一下|为什么|怎么|多少|几点|能不能|可不可以)',content):
        return False
    clauses=[c.strip() for c in re.split(r'[。！!，,、\n]+',content) if c.strip()]
    if not clauses:
        return False
    ending=(r'(?:(?:先)?不聊(?:了|啦)?|(?:等会儿?|待会儿?|回头|晚点)(?:再)?(?:聊|说)|'
            r'(?:我)?(?:先)?去(?:吃饭|洗澡|睡觉|拿快递|上课|看(?:会儿?|一会儿?)?(?:书|小说))|'
            r'(?:我)?(?:先)?睡(?:了|啦)?|晚安|拜拜|再见)(?:了|啦|吧|啊|哦|哈|~|～|…)*')
    return bool(re.fullmatch(ending,clauses[-1]))


def generate(client, kwargs, progress, clean, on_sent, acquire=lambda: None, *, retry_empty=None):
    """At most two generations; only confirmed deliveries enter chat memory."""
    messages = [dict(m) for m in kwargs['messages']]
    messages[0] = dict(messages[0], content=messages[0]['content']+'\n\n'+INSTRUCTION)
    request = dict(kwargs, messages=messages, stream=True)
    buffer = SegmentBuffer()
    status = 'complete'
    more = False

    def emit(value):
        value = clean(clean_control(value)).strip()
        return not value or progress.emit(value, on_sent)

    try:
        if progress.interrupted():
            return DeliveredReply('', 'interrupted')
        acquire()
        with client.chat.completions.create(**request) as stream:
            for chunk in stream:
                if progress.interrupted():
                    return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
                for choice in chunk.choices or ():
                    for value in buffer.feed(choice.delta.content or ''):
                        if not emit(value):
                            return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
        tail, more = buffer.finish()
        if not emit(tail):
            return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
        # No extra turn after a question, empty output, or an already long answer.
        if (more and progress.sent and not user_ends_turn(messages) and len(progress.sent) < 4 and
                len(''.join(progress.sent)) < 900 and not waiting_for_user(progress.sent[-1]) and
                not progress.interrupted()):
            follow = messages + [{'role':'assistant', 'content':'\n\n'.join(progress.sent)},
                                 {'role':'system', 'content':CONTINUATION}]
            acquire()
            if not progress.interrupted():
                extra = []
                # Buffer this optional addition so duplicate/empty text stays invisible.
                follow_request = dict(request, messages=follow, max_tokens=1200)
                if request.get('_shizuka_profile'):
                    follow_request['_shizuka_profile'] = dict(request['_shizuka_profile'], max_value=1200)
                with client.chat.completions.create(**follow_request) as stream:
                    for chunk in stream:
                        if progress.interrupted():
                            return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
                        extra.extend(c.delta.content or '' for c in chunk.choices or ())
                raw = ''.join(extra)
                value = clean(clean_control(raw)).strip()
                ended = any(m.group() == END for m in control_matches(raw))
                if not ended and value and len(value) <= 500 and not repeated(value, progress.sent):
                    if not progress.emit(value, on_sent):
                        status = 'interrupted'
        if not progress.sent and not progress.interrupted() and retry_empty is not None:
            recovered = retry_empty(client, request)
            if recovered and not progress.interrupted():
                recovered_buffer = SegmentBuffer()
                for value in recovered_buffer.feed(recovered):
                    if not emit(value):
                        return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
                tail, _ = recovered_buffer.finish()
                if not emit(tail):
                    return DeliveredReply('\n\n'.join(progress.sent), 'interrupted')
        if not progress.sent and not progress.interrupted():
            emit('刚才没有收到完整回复，请再试一次。')
            status = 'empty'
    except Exception:
        # Do not resend a whole answer after partial delivery or a send timeout.
        status = 'delivery_failed' if progress.failed else 'generation_failed'
        if not progress.sent and not progress.failed and not progress.interrupted():
            try:
                emit('刚才没有收到完整回复，请再试一次。')
            except Exception:
                status = 'delivery_failed'
    return DeliveredReply('\n\n'.join(progress.sent), status)
