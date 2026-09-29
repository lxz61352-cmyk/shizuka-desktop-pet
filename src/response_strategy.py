"""本轮该用哪种接法：规则判断意图 → 按对话状态加权挑策略 → 一小段提示词。

策略只描述「这一轮的倾向」，不是模板；具体说什么仍由角色卡和模型决定。
默认权重与主动发言的方向池（dialogue_style.PROACTIVE_DIRECTIONS）同一思路：可调、可测。
"""
import random
import re
from conversation_state import detect_intent

STRATEGIES = ('direct', 'reaction', 'continuation', 'analysis', 'care', 'humor', 'question', 'free')

# free = 不给具体套路，交给角色卡和状态自己决定；占比给得高，避免每轮都被指派任务。
BASE_WEIGHTS = {'direct': 25, 'reaction': 20, 'continuation': 12, 'analysis': 10,
                'care': 6, 'humor': 4, 'question': 3, 'free': 20}

INTENT_WEIGHTS = {
    'question': {'direct': 70, 'analysis': 20, 'question': 10},
    'emotion': {'care': 35, 'reaction': 30, 'continuation': 15, 'humor': 10, 'free': 10},
    'request': {'direct': 50, 'analysis': 40, 'reaction': 10},
    'sharing': {'reaction': 30, 'continuation': 20, 'care': 15, 'humor': 10, 'direct': 10, 'free': 15},
    'greeting': {'reaction': 40, 'direct': 20, 'continuation': 15, 'humor': 10, 'free': 15},
    'advice': {'reaction': 25, 'direct': 20, 'analysis': 20, 'continuation': 15, 'humor': 10, 'free': 10},
    'goodbye': {'reaction': 70, 'direct': 30},
}

# 只描述「倾向」，不下命令；具体说什么仍由角色卡、状态和模型决定。
INSTRUCTIONS = {
    'direct': '偏向直接回答用户问的事；答完就停，不用刻意延续。',
    'reaction': '偏向先对用户的话做个自然反应，不必急着分析。',
    'continuation': '可以顺着刚才的话题往下接一句，换个说法或角度。',
    'analysis': '如果决定认真回应，可以把关键原因说清楚。',
    'care': '可以回应用户当下的情绪，也可以给个具体做法。',
    'humor': '可以轻轻调侃一句，善意、不过火。',
    'question': '如果想问，就问一个和当前话题相关、好回答的问题。',
    'free': '',
}

# 规则 stance：只认三种明显情况，判不了就不注入（不额外调用模型）。
STANCE_SELF_DEPRECATION_RE = re.compile(r'废物|没用|不行|做不好|做不到|配不上|太菜|好菜|完蛋|果然不适合|就是笨')
STANCE_HELP_RE = re.compile(r'怎么办|帮我|帮忙|不会弄|不知道怎么做|教教我|救救|卡住了|搞不定')
STANCE_DONE_RE = re.compile(r'终于.{0,6}(?:做完|写完|弄完|搞定|完成|交了)|搞定了|弄好了|做完了|写完了|完成了')


def stance_note(text):
    """用户这轮明显在自我否定/求助/报完成时，给一句很弱的倾向；其余返回空串。"""
    text = (text or '').strip()
    if not text:
        return ''
    if STANCE_SELF_DEPRECATION_RE.search(text):
        return '可以对用户的自我否定持保留态度，直接表达不同看法。'
    if STANCE_HELP_RE.search(text):
        return '可以表达关切，并倾向给一个具体做法。'
    if STANCE_DONE_RE.search(text):
        return '可以自然表达认可。'
    return ''


def weights_for(state, intent):
    """策略权重 = 意图基准权重 − 连续提问惩罚 − 上一轮同策略降温。"""
    weights = dict(INTENT_WEIGHTS.get(intent) or BASE_WEIGHTS)
    weights.setdefault('question', 0)
    if state.consecutive_questions == 1:
        weights['question'] = weights.get('question', 0) * 0.3
    elif state.consecutive_questions >= 2:
        weights['question'] = 0
    if intent not in ('question', 'request') and state.last_strategy in weights:
        weights[state.last_strategy] = weights[state.last_strategy] * 0.4
    return weights


def pick(state, intent, rng=None):
    weights = weights_for(state, intent)
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total <= 0:
        return 'reaction'
    point = (rng or random).random() * total
    upto = 0.0
    for name, value in weights.items():
        upto += max(0.0, float(value))
        if point <= upto:
            return name
    return 'reaction'


def choose(state, user_text, rng=None, now=None):
    """更新状态并挑出本轮策略；返回值 (intent, strategy)。"""
    intent = detect_intent(user_text)
    state.intent = intent
    state.observe_user(user_text, now)
    state.abandon_note = state.resolve_pending(user_text)
    strategy = pick(state, intent, rng)
    state.last_strategy = strategy
    return intent, strategy


def state_notes(state):
    """连续提问提醒 / 上一轮问句没被接住：只留状态约束，不带策略。"""
    if state is None:
        return ''
    parts = []
    if getattr(state, 'consecutive_questions', 0) >= 1:
        parts.append('上一轮已经问过一次了，这一轮不要再用提问收尾。')
    if getattr(state, 'abandon_note', None):
        parts.append(state.abandon_note)
    return '\n'.join(parts)


def instruction(strategy, state=None):
    """策略块：free 不产生内容；状态提醒始终保留。"""
    text = INSTRUCTIONS.get(strategy, INSTRUCTIONS['reaction'])
    parts = []
    if text:
        parts.append('【本轮回复侧重】\n' + text)
    notes = state_notes(state)
    if notes:
        parts.append(notes)
    return '\n'.join(parts)
