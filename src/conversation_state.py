"""当前这段对话的临时状态：聊到哪儿了、上一轮怎么接的。

分工：conversation_memory 管「用户以前是什么人」，本模块管「现在这段对话进行到哪儿了」。
不落盘、不进长期记忆，重启即重置；模型调用失败也不影响它。
"""
import random
import re
import time

from shizuka_turn_context import communication_limits, has_followup_request

QUESTION_END_RE = re.compile(
    r'[？?]\s*$|(?:吗|好不好|对不对|行不行|好吗|可以吗)\s*[。！!…~～]*\s*$')
USER_QUESTION_END_RE = re.compile(
    r'[？?]\s*$|(?:吗|呢|么|好不好|对不对|行不行|好吗|可以吗|是吧|对吧)\s*[。！!…~～]*\s*$')
QUESTION_MARK_RE = re.compile(r'[？?]')
QUESTION_WORD_RE = re.compile(
    r'为什么|怎么|如何|是不是|能不能|可不可以|要不要|有没有|什么时候|多少|等于几|几点|多久|哪种|哪一|'
    r'该不该|会不会|行不行|对不对|好不好')
GREETING_RE = re.compile(r'^\s*(?:你好|您好|嗨|哈喽|哈啰|hi|hello|早安|早上好|中午好|下午好|晚上好|早|在吗|在不在)[！!。.~～]*\s*$',
                         re.IGNORECASE)
# 主观征询（要不要/该不该/你觉得怎么样）：不按「功能题」处理，允许更多回应模式。
ADVICE_RE = re.compile(r'你觉得|你认为|怎么样|如何评价|好不好|该不该|要不要|还是|帮我选|给个建议')
ANSWER_HEAD_RE = re.compile(r'^(?:嗯|对|是的?|没有|没|还行|不错|好的?|行|可以|不知道|忘了|看了|吃过|睡了|确实|差不多|应该是)')
NEW_TOPIC_RE = re.compile(r'^(?:对了|话说|另外|说起来|还有|顺带)')
GOODBYE_RE = re.compile(
    r'晚安|我去睡|去睡了|睡觉去|我睡了|我去洗澡|洗澡去|我出门|出门了|先这样|拜拜|再见|回头聊|我下了|'
    r'去吃饭|吃饭去|我先走|先撤|溜了|去忙了|不聊了')
EMOTION_RE = re.compile(
    r'好累|太累|心累|难受|好烦|有点烦|很烦|太烦|心烦|烦躁|烦死|郁闷|难过|伤心|想哭|哭了|焦虑|压力|崩溃|委屈|emo|低落|'
    r'紧张|害怕|孤单|孤独|无聊|疼|好痛|困死|好困|丧|绝望|废物|没用|配不上|不想干|没力气|提不起劲|'
    r'开心|高兴|好爽|舒服|放松|欣慰|感动')
REQUEST_RE = re.compile(
    r'帮我|帮忙|麻烦|替我|给我|写一个|写个|查一下|查查|搜一下|找一下|看一下|读一下|翻译|总结|整理|'
    r'提醒我|记一下|打开|关闭|做个|列个')
SHARING_RE = re.compile(
    r'终于|写完|做完|搞定|弄完|完成|吃[了过]|看[了过]|玩[了过]|去[了过]|买[了过]|睡[了过]|'
    r'加班|摸鱼|上班|下班|我今天|我刚刚|我刚|我昨天|我最近')
# 冲着人来的态度（损人/夸人/撒娇式吐槽）：先当人际反应，不因为带「怎么」就当问题处理。
ATTITUDE_RE = re.compile(
    r'你好笨|真笨|太笨|这么笨|好笨|笨死|好蠢|闭嘴|烦人|讨厌你|'
    r'(?:你|静香)[^。！？!?]{0,6}(?:可爱|好懂|厉害|真好|温柔)|你怎么这么(?:懂|好)')

# ── 低信息连击：连着只喊人 / 只发语气词时，她不会一直配合 ──────────────
# 状态随连续次数升级（疑惑 → 不耐烦 → 警告），到执行级由程序直接给省略号；
# 用户说出实际内容（或隔了很久）立刻归零，不追罚。
EMPTY_RESET_SECONDS = 900
EMPTY_EXECUTE_STREAK = 5
EMPTY_CALL_RE = re.compile(
    r'^\s*(?:在吗|在么|在不在|在|111+|1+|喂+|嘿+|哈喽|哈啰|滴滴|戳(?:一下)?)'
    r'\s*[！!。.~～？?…]*\s*$')
EMPTY_FILLER_RE = re.compile(
    r'^\s*(?:嗯+|哦+|噢+|喔+|呃+|额+|啊+|哈+|呵+|嘿嘿|好吧|好|行|可以|那个|这个|'
    r'没啥|没什么|没事|算了|。。。+|……+|\.{2,}|[？?！!。…~]+)\s*$')
EMPTY_NOTES = {
    'call': {
        2: ('他又喊了一声，还是没说事。她有点不耐烦：让他有话直说。',
            '他第二遍还是只喊人不说事。她有点烦了：让他有话直说。'),
        3: ('他还在反复喊。她耐心快没了：直接问他到底要说什么。',
            '第三遍了。她不想再陪他绕：直接问他到底要说什么。'),
        4: ('她受够了：明确告诉他，再这样喊下去就不理他了。',
            '她不想再应了：跟他说清楚，再喊就不理他了。'),
    },
    'filler': {
        2: ('他还是只发这种没内容的短句。她可以只回一两个字，或者不接。',
            '又是这种没内容的短句。她不必每句都接，回一两个字就行。'),
        3: ('他一直这样没话找话。她可以明说：到底想说什么。',
            '他一直没话找话。她可以直接问他想说什么。'),
        4: ('她不想再陪着耗了：可以告诉他，再这样她就先不回了。',
            '她陪不动了：跟他说，再这样她就先不回了。'),
    },
}


def is_empty_contact(text):
    """低信息输入：只喊人不说话（call）或只有语气词（filler）；其余返回 ''。"""
    text = (text or '').strip()
    if not text:
        return ''
    if EMPTY_CALL_RE.match(text):
        return 'call'
    if EMPTY_FILLER_RE.match(text):
        return 'filler'
    return ''


def ends_with_question(text):
    """回复是否以提问收尾：只认问号和「吗/好不好」这类明确疑问收尾。

    「有我在呢。」这种带「呢」的陈述句不算，否则会误记成连续提问。
    """
    return bool(QUESTION_END_RE.search((text or '').strip()))


def looks_like_question(text):
    text = (text or '').strip()
    return bool(QUESTION_MARK_RE.search(text) or USER_QUESTION_END_RE.search(text) or QUESTION_WORD_RE.search(text))


def detect_intent(text):
    """规则判断用户这轮在做什么：question / emotion / request / sharing / greeting / goodbye / general。"""
    text = (text or '').strip()
    if not text:
        return 'general'
    if GREETING_RE.match(text):
        return 'greeting'
    if GOODBYE_RE.search(text):
        return 'goodbye'
    if communication_limits(text) and not has_followup_request(text):
        return 'sharing'
    if len(text) <= 30 and ATTITUDE_RE.search(text):
        return 'sharing'
    if looks_like_question(text):
        return 'advice' if ADVICE_RE.search(text) else 'question'
    if EMOTION_RE.search(text):
        return 'emotion'
    if REQUEST_RE.search(text):
        return 'request'
    if SHARING_RE.search(text):
        return 'sharing'
    return 'general'


class ConversationState:
    """一次会话内的临时状态。字段都是可选的，用不上时保持 None。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.topic = None
        self.intent = None
        self.mood = None
        self.last_strategy = None
        self.turn = 0
        self.question_count = 0
        self.consecutive_questions = 0
        self.reply_length = 'medium'
        self.last_user_text = ''
        self.pending_question = None
        self.abandon_note = None
        self.last_mode = None
        self.last_completion = None
        self.last_emotion = None
        self.last_impulse = None
        self.last_scope = None
        self.last_stop_reason = None
        self.last_line_emotions = []
        self.last_topic = None
        self.active_topic = None
        self.previous_topic = None
        self.dormant_topics = []
        self.topic_changed_at = 0
        self.empty_streak = 0
        self.empty_kind = ''
        self._last_empty_at = None
        self.current_interaction = None
        self.last_limit_turn = None
        self.last_correction_turn = None
        self.last_playful_meta_turn = None
        self.unresolved_prior_reference_turn = None

    def observe_user(self, text, now=None):
        self.turn += 1
        if re.search(r'(?:上次|之前).{0,18}(?:其实|只是|并不是|不是真的)', text or ''):
            self.last_correction_turn = self.turn
        if re.search(r'暧昧|开玩笑|别突然上课', text or ''):
            self.last_playful_meta_turn = self.turn
        self.last_user_text = (text or '')[:200]
        if communication_limits(text) and not has_followup_request(text):
            self.last_limit_turn = self.turn
        now = time.time() if now is None else now
        if self._last_empty_at and now - self._last_empty_at > EMPTY_RESET_SECONDS:
            self.empty_streak = 0
            self.empty_kind = ''
        if (self.current_interaction
                and self.current_interaction.get('current_text') == text
                and is_empty_contact(text)):
            self.empty_streak = 0
            self.empty_kind = ''
            self._last_empty_at = None
            return
        kind = is_empty_contact(text)
        if not kind or self._answers_pending(text):
            self.empty_streak = 0
            self.empty_kind = ''
            return
        self.empty_streak += 1
        self.empty_kind = kind
        self._last_empty_at = now

    def begin_turn(self, text, now=None):
        """Commit user-turn state once, before the unified planner runs."""
        self.intent = detect_intent(text)
        self.observe_user(text, now=now)
        self.abandon_note = self.resolve_pending(text)
        return self.intent

    def continuity_note(self):
        """Render only conversation continuity already owned by this state."""
        parts = []
        if self.consecutive_questions >= 1:
            parts.append('上一轮已经问过一次了，这一轮不要再用提问收尾。')
        if self.abandon_note:
            parts.append(self.abandon_note)
        return '\n'.join(parts)

    def note_topic(self, topic, shift=False):
        """话题所有权：明确切换时旧话题休眠；当前话题成为 active。"""
        if shift:
            if self.active_topic:
                self.previous_topic = self.active_topic
                self.dormant_topics.append(self.active_topic)
                self.dormant_topics = self.dormant_topics[-5:]
            self.topic_changed_at = self.turn
        if topic and topic != "无":
            self.active_topic = topic

    def _answers_pending(self, text):
        """她刚问过一句时，短回答（嗯/好/编号）算接住了，不算低信息连击。"""
        if not self.pending_question:
            return False
        text = (text or '').strip()
        if not text or len(text) > 12:
            return False
        if re.fullmatch(r'[0-9０-９]+', text):
            return True
        return bool(ANSWER_HEAD_RE.match(text))

    def empty_contact_note(self):
        """连着低信息输入时给她一句状态说明；第 1 次和执行级不注入。

        每个阶段有两套措辞随机选，避免「重复次数 → 固定台词」的脚本感。
        """
        if self.empty_streak < 2 or self.empty_streak >= EMPTY_EXECUTE_STREAK:
            return ''
        texts = EMPTY_NOTES.get(self.empty_kind, {}).get(self.empty_streak)
        if not texts:
            return ''
        return '【她这会儿】\n' + random.choice(texts)

    def empty_executes(self):
        """警告过之后还在喊：这一轮直接不接（省略号），不再调模型。"""
        return self.empty_streak >= EMPTY_EXECUTE_STREAK and bool(self.empty_kind)

    def observe_reply(self, reply):
        """回复生成后记账：她这轮是不是又问了一句、回复多长、留下了什么待接的问题。"""
        text = (reply or '').strip()
        if ends_with_question(text):
            self.question_count += 1
            self.consecutive_questions += 1
            self.pending_question = text[-80:]
        else:
            self.consecutive_questions = 0
            self.pending_question = None
        size = len(text)
        self.reply_length = 'short' if size <= 40 else 'medium' if size <= 160 else 'long'

    def limit_followup_note(self, text):
        """上一轮说过「不用建议/分析」后，用户又明确求助：只答现在的，不翻旧账。"""
        if communication_limits(text) or not self.last_limit_turn:
            return ''
        if self.turn - self.last_limit_turn > 3:
            return ''
        signals = getattr(self, "last_signals", None) or {}
        if not (signals.get("explicit_help") or signals.get("speech_type") == "question"):
            return ''
        return ('用户上一轮说过不想被分析或给建议，那是上一轮的限定；'
                '他现在明确在问，正常回答，不要提他之前的限定，也不要翻旧账。')

    def correction_followup_note(self):
        """Keep a just-given correction authoritative for its immediate follow-up."""
        if not self.last_correction_turn or self.turn - self.last_correction_turn > 2:
            return ''
        return ('【刚刚发生的事实更正】以用户的新说明为准。不要批评他“改口”“绕一圈”或话不可靠，'
                '不要从更正动作推断他的偏好、动机或性格。当前只知道旧的“讨厌甜食”已撤回；'
                '具体喜欢什么仍未知，就直接说不知道。')

    def playful_followup_note(self):
        """Keep a declared joke playful through its immediate resolution."""
        if not self.last_playful_meta_turn or self.turn - self.last_playful_meta_turn > 2:
            return ''
        return ('【刚刚是轻玩笑】把它当熟人间的逗趣接住，可以嘴硬或反逗，但不要把责任推回用户，'
                '不要说他“自己往那边想”“怪不到我”“到底想不想聊”，也不要逼他解释玩笑。')

    def unresolved_prior_reference_note(self):
        if not self.unresolved_prior_reference_turn or self.turn - self.unresolved_prior_reference_turn > 2:
            return ''
        return ('【原始前文仍不可见】后续只能解释当前可见回复；不得补写最初那句的内容，'
                '也不得声称“我说的是／我说你……”来替缺失前文定稿。')

    def resolve_pending(self, text):
        """上一轮的问句有没有被接住；没接住就返回一句提醒（避免重复追问）。

        判定从宽：短回复、以「嗯/对/还行…」开头的都算接住了；明确换话题或长内容才算没接。
        """
        question = self.pending_question
        self.pending_question = None
        if not question:
            return None
        text = (text or '').strip()
        if not text:
            return None
        if NEW_TOPIC_RE.match(text) or (len(text) > 12 and not ANSWER_HEAD_RE.match(text)):
            return '上一轮的问题用户没有接，不要重复追问，接住用户现在说的事。'
        return None
