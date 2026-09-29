"""回应模式：这一轮她愿意怎么接（在策略之上的一层很弱的倾向）。

功能类请求（question / request）只用 engage / brief / expand 三种模式，
不参与 deflect / refuse / challenge，保证事实与功能照常处理。
"""
import random
import re

MODES = ('engage', 'brief', 'reaction', 'expand', 'self_expression', 'tease',
         'challenge', 'deflect', 'hesitate', 'refuse', 'ignore_detail')

BASE_WEIGHTS = {'engage': 30, 'brief': 18, 'reaction': 14, 'expand': 8, 'self_expression': 10,
                'tease': 5, 'challenge': 5, 'deflect': 5, 'hesitate': 4, 'refuse': 2,
                'ignore_detail': 6}

FUNCTIONAL_MODES = {'engage': 70, 'brief': 15, 'expand': 15}

# 这些模式已经主导了本轮，不再叠加策略指令，避免两套倾向互相打架。
SOFT_MODES = ('deflect', 'refuse', 'hesitate', 'ignore_detail')

# 只描述倾向，不下命令（不写「必须/不要」式的执行指令）。
INSTRUCTIONS = {
    'engage': '',
    'brief': '本轮倾向简短、随口，不必完整展开。',
    'reaction': '本轮倾向先给个自然反应，不急着给建议。',
    'expand': '本轮可以认真展开说清楚。',
    'self_expression': '本轮可以多说一点自己的看法或感受，不一定要围绕用户的需求。',
    'tease': '本轮可以轻轻调侃一句。',
    'challenge': '本轮可以反问，或先质疑一下前提。',
    'deflect': '本轮可以不正面回答，转开，或把决定交还给用户。',
    'hesitate': '本轮可以保留意见、表现出一点犹豫。',
    'refuse': '本轮可以保留意见、回避完整回答、把决定交还给用户，或直接说自己现在不想展开；除非有明确理由，不要生硬拒绝。',
    'ignore_detail': '用户说了好几件事时，本轮可以只接住其中一件（最要紧或最在意的那件）。',
}

CLOSING = ('用户的问题不必每次都被完整回答：可以只回应一个细节、只表达态度、给一个结论就停，或暂时不回答。'
           '事实和功能请求要如实处理；以上只是倾向，不是模板。')

# ── 回应完成度：这一轮说到什么程度就停 ──────────────────────────────
COMPLETIONS = ('minimal', 'partial', 'normal', 'complete')

COMPLETION_WEIGHTS = {
    'base': {'minimal': 18, 'partial': 22, 'normal': 45, 'complete': 15},
    'casual': {'minimal': 28, 'partial': 27, 'normal': 40, 'complete': 5},
    'task': {'minimal': 3, 'partial': 10, 'normal': 47, 'complete': 40},
    'help': {'minimal': 5, 'partial': 15, 'normal': 50, 'complete': 30},
}

COMPLETION_HINTS = {
    'minimal': '这一轮只说一句、只表个态就够，不补充方案、建议或追问。',
    'partial': '这一轮只接住其中一点，其余不必处理。',
    'normal': '',
    'complete': '',
}

COMPLETION_RULE = ('【本轮回应完成度】{word}\n'
                   '不要把每条消息都当成需要完成的任务：可以只回应一句、只表达态度、只接一个细节、'
                   '只回答一部分，或说完就停。用户没有明确要求解决时，不要自动追加建议、方案、提醒和追问'
                   '——没有下一步也是正常的结束。已经回应到情绪、问题、判断或一句自然的接话，就可以停，'
                   '不必为了显得有帮助再补充。')


def completion_weights(mood, intent, strategy, mode):
    """由现有状态共同决定完成度权重；不额外调模型、不落盘。"""
    if intent in ('question', 'request'):
        weights = dict(COMPLETION_WEIGHTS['task'])
    elif intent == 'advice':
        weights = dict(COMPLETION_WEIGHTS['help'])
    else:
        weights = dict(COMPLETION_WEIGHTS['casual'])
    if strategy in ('reaction', 'humor', 'free'):
        weights['minimal'] += 12
        weights['partial'] += 8
    elif strategy == 'continuation':
        weights['partial'] += 10
        weights['normal'] += 5
    elif strategy == 'analysis':
        weights['normal'] += 8
        weights['complete'] += 10
    elif strategy == 'care':
        weights['normal'] += 6
        weights['partial'] += 4
    if mode == 'brief':
        weights['minimal'] += 20
    elif mode in ('reaction', 'self_expression', 'deflect', 'tease', 'hesitate'):
        weights['minimal'] += 10
        weights['partial'] += 8
    elif mode == 'ignore_detail':
        weights['partial'] += 16
    elif mode == 'challenge':
        weights['partial'] += 8
        weights['normal'] += 6
    elif mode == 'engage':
        weights['normal'] += 8
    elif mode == 'expand':
        weights['normal'] += 6
        weights['complete'] += 10
    if mood is not None:
        low = (max(0.0, 0.5 - mood.energy) + max(0.0, 0.55 - mood.willingness)
               + max(0.0, 0.5 - mood.patience))
        high = max(0.0, mood.energy - 0.7) + max(0.0, mood.willingness - 0.7)
        weights['minimal'] += 25 * low
        weights['partial'] += 18 * low
        weights['normal'] += 8 * high
        weights['complete'] += 6 * high
        if mood.alertness < 0.35:
            weights['minimal'] += 10
            weights['partial'] += 6
    return {name: max(0.0, value) for name, value in weights.items()}


def pick_completion(mood, intent, strategy, mode, rng=None):
    """带小扰动的加权选择；功能任务天然偏向 normal/complete。"""
    picker = rng or random
    weights = completion_weights(mood, intent, strategy, mode)
    jittered = {name: value * picker.uniform(0.9, 1.1) for name, value in weights.items()}
    total = sum(jittered.values())
    if total <= 0:
        return 'normal'
    point = picker.random() * total
    upto = 0.0
    for name, value in jittered.items():
        upto += value
        if point <= upto:
            return name
    return 'normal'


def completion_instruction(completion):
    hint = COMPLETION_HINTS.get(completion, '')
    text = COMPLETION_RULE.format(word=completion)
    if hint:
        text += '\n' + hint
    return text


# ── 第一冲动 / 回应范围 / 停止原因（2026-09-23 深夜：减法版核心）────────────
# 只判断「她第一时间想做什么」与「这轮要不要解决问题」，不再要求输出格式与完成度。
IMPULSES = ('laugh', 'tease', 'push_back', 'soften', 'acknowledge', 'deny',
            'deflect', 'ask', 'comfort', 'withdraw', 'agree', 'curious', 'surprised')

SCOPES = ('react_only', 'respond', 'help', 'full_task')

IMPULSE_TEXT = {
    'laugh': '笑一下',
    'tease': '逗他一句',
    'push_back': '顶回去',
    'soften': '软下来',
    'acknowledge': '应一声',
    'deny': '嘴硬一下',
    'deflect': '躲开这句',
    'ask': '问一句',
    'comfort': '靠近一点',
    'withdraw': '少说两句',
    'agree': '认了',
    'curious': '多知道一点',
    'surprised': '愣一下',
}

IMPULSE_CANDIDATES = {
    'concerned': ('soften', 'comfort'),
    'annoyed': ('push_back', 'deny'),
    'embarrassed': ('deflect', 'deny'),
    'amused': ('laugh', 'tease'),
    'skeptical': ('push_back', 'deny'),
    'surprised': ('surprised', 'ask'),
    'relieved': ('acknowledge', 'soften'),
    'touched': ('soften', 'withdraw'),
    'tired': ('withdraw', 'acknowledge'),
    'impatient': ('withdraw', 'push_back'),
    'indifferent': ('withdraw', 'acknowledge'),
}

# 即时情绪判不出来时，用话里的语气线索兜底，避免 50 轮里 39 轮都是「接住」。
IMPRESSION_CUES = (
    (re.compile(r'哈哈|笑死|逗你|开玩笑|乐死|好耶'), ('laugh', 'tease')),
    (re.compile(r'涩图|黄腔|搭讪|漂亮|美女|性感|亲一'), ('tease', 'deflect')),
    (re.compile(r'谢谢|感谢|听我说|陪我|跟我说这些'), ('soften', 'acknowledge')),
    (re.compile(r'算了|懒得|不闹了|不聊|别管|不说了'), ('withdraw', 'acknowledge')),
    (re.compile(r'真的假的|骗我|敷衍|糊弄|不信'), ('push_back', 'deny')),
    (re.compile(r'怎么办|咋办|为什么|为啥|怎么会'), ('curious', 'ask')),
)

IMPRESSION_BY_INTENT = {
    'emotion': ('comfort', 'soften'),
    'sharing': ('curious', 'acknowledge'),
    'greeting': ('acknowledge', 'soften'),
    'advice': ('acknowledge', 'curious'),
}

TASK_VERBS = ('帮我', '帮我算', '帮我查', '帮我写', '帮我理', '帮我安排', '给我讲', '讲讲',
              '解释一下', '推导', '列出来', '整理成', '修改这个文件', '怎么解决', '怎么弄',
              '写一个', '写段', '写代码', '出几道', '详细讲讲', '展开说')

# 底线话题：拿心菜开黄腔/要涩图。这不是玩笑，她会直接翻脸。
BOUNDARY_RE = re.compile(r'(?:心菜|心菜酱)[^。！？!?]{0,8}(?:涩图|色图|黄图|裸|本子|同人|生成)|'
                         r'(?:涩图|色图|黄图|裸图|本子)[^。！？!?]{0,8}(?:心菜|心菜酱)')

BOUNDARY_NOTE = ('这句话踩到她的底线：直接、强硬地拒绝，可以带火气、可以不客气，'
                 '不要打圆场、不要顺着聊、不要给替代方案。')


def hits_boundary(text):
    return bool(BOUNDARY_RE.search(text or ''))


# 按角色设定（World Dai Star 静香：心菜是她的全部、对表演极认真）给话题态度。
KOKONA_RE = re.compile(r'心菜')
STAGE_RE = re.compile(r'表演|演技|舞台|角色|剧本|演员|公演|试镜|台词|剧团')


def topic_notes(text):
    text = text or ''
    notes = []
    if KOKONA_RE.search(text):
        notes.append('心菜是她世界里很重要的人：提起她时可以自然接话，'
                     '得意、吐槽、想念或护一句都可能，按当下语境和自己的心情来。')
    if STAGE_RE.search(text):
        notes.append('舞台和表演是她熟悉的领域：聊到时她会具体、认真；'
                     '其它话题照常，不必都绕回表演。')
    return notes


# 生活报备：吃饭/睡觉/出门/回来/上课/图书馆这类，只当"我告诉你一件事"，
# 不自动变成需要管理或照顾的对象。带问题、困难或明确求助时不走这条路。
LIFE_REPORT_RE = re.compile(
    r'我?(?:去|刚|已经|今天|现在|准备|打算)?(?:吃了|吃完|喝了|点了|加了|买了|打了|赢了|输了|送了|睡了|去睡|'
    r'出门|回来|回宿舍|回寝室|到家|上课|下课|去图书馆|图书馆|洗澡|躺下|休息|在路|到宿舍|到家了)|'
    r'晚安|我去睡|睡了|出门了|回来了|上课了|下课了|到家了|吃[了过]|玩[了过]')

LIFE_REPORT_EXCEPT_RE = re.compile(
    r'[？?]|吗|呢|怎么办|咋办|帮我|帮忙|你觉得|该不该|要不要|'
    r'学不进去|写不下去|卡住|不会|搞不定|来不及|赶不上|失败|被骂|挂了|难受|好烦|好累|撑不住')


def is_life_report(text):
    """纯生活报备（不夹问题/困难）→ 只当聊天回应。"""
    text = text or ''
    if LIFE_REPORT_EXCEPT_RE.search(text):
        return False
    return bool(LIFE_REPORT_RE.search(text))


def scope_for(intent, text=''):
    """这轮做到什么程度：react_only / respond / help / full_task。"""
    text = text or ''
    if hits_boundary(text):
        return 'react_only'
    if intent in ('question', 'request'):
        return 'full_task' if any(word in text for word in TASK_VERBS) else 'help'
    if intent == 'advice':
        return 'respond'
    if is_life_report(text):
        return 'react_only'
    if intent in ('emotion', 'sharing', 'greeting', 'goodbye'):
        return 'react_only'
    return 'respond'


def impulse_for(emotion_reaction, intent, scope, text='', rng=None):
    """第一冲动：一次只给一个；任务类默认接住。"""
    picker = rng or random
    if hits_boundary(text):
        return picker.choice(('push_back', 'deny'))
    if scope in ('help', 'full_task'):
        return 'acknowledge'
    if intent == 'goodbye':
        return 'acknowledge'
    candidates = IMPULSE_CANDIDATES.get(emotion_reaction or '')
    if not candidates:
        for pattern, cues in IMPRESSION_CUES:
            if pattern.search(text or ''):
                candidates = cues
                break
    if not candidates:
        candidates = IMPRESSION_BY_INTENT.get(intent, ('acknowledge', 'curious'))
    return picker.choice(candidates)


def stop_reason_for(scope, impulse, intent):
    if intent == 'goodbye':
        return 'user_closed'
    if scope != 'react_only':
        return ''
    if impulse in ('soften', 'comfort'):
        return 'emotion_expressed'
    if impulse in ('laugh', 'tease'):
        return 'teasing_landed'
    if impulse in ('acknowledge', 'withdraw'):
        return 'nothing_to_add'
    return 'reaction_done'


STOP_TEXT = {
    'reaction_done': '反应给到就够了。',
    'emotion_expressed': '情绪接住就够了。',
    'teasing_landed': '玩笑落地就够了。',
    'nothing_to_add': '最想说的已经说了，可以就停在这里。',
    'user_closed': '用户已经结束话题，应一声就好。',
}

SCOPE_TEXT = {
    'react_only': '这只是他说的一件事，不是交给她的任务：想接就接；不想接，应一声也行。',
    'respond': '这轮没有必须完成的事。想说什么说什么，说完就停。',
    'help': '这轮确实要帮她做点事：认真给做法，别只回一句。',
    'full_task': '这是明确的任务：认真完成，该展开就展开。',
}


def impulse_prompt(impulse, scope, stop_reason, reaction_text=''):
    lines = []
    if reaction_text:
        lines.append('静香刚听到这句话，第一反应是%s。' % reaction_text)
    lines.append('她这会儿想%s。' % IMPULSE_TEXT.get(impulse, '应一声'))
    lines.append(SCOPE_TEXT.get(scope, SCOPE_TEXT['respond']))
    text = STOP_TEXT.get(stop_reason)
    if text:
        lines.append(text)
    lines.append('用静香自己的自然说话方式回答；不必凑长度，也不必把话接完整。')
    return '【她这会儿】\n' + '\n'.join(lines)


def weights_for(mood, intent):
    """按状态微调权重；功能类意图走固定池。"""
    if intent in ('question', 'request'):
        return dict(FUNCTIONAL_MODES)
    weights = dict(BASE_WEIGHTS)
    if mood is None:
        return weights
    low_willingness = max(0.0, 0.55 - mood.willingness)
    low_energy = max(0.0, 0.5 - mood.energy)
    low_patience = max(0.0, 0.5 - mood.patience)
    high_energy = max(0.0, mood.energy - 0.7)
    high_cheer = max(0.0, mood.cheerfulness - 0.7)
    high_tension = max(0.0, mood.tension - 0.35)
    high_engagement = max(0.0, mood.engagement - 0.7)
    weights['brief'] += 40 * low_willingness + 30 * low_energy
    weights['reaction'] += 20 * low_energy
    weights['deflect'] += 25 * low_willingness + 20 * low_patience
    weights['refuse'] += 15 * low_willingness + 15 * low_patience
    weights['ignore_detail'] += 20 * low_willingness + 15 * high_tension + 15 * low_patience
    weights['hesitate'] += 20 * high_tension
    weights['challenge'] += 15 * low_patience
    weights['tease'] += 25 * high_cheer
    weights['self_expression'] += 20 * high_cheer + 25 * high_engagement + 15 * (1 - low_willingness)
    weights['expand'] += 25 * high_energy + 20 * high_engagement
    weights['engage'] += 20 * high_engagement
    if intent == 'goodbye':
        weights = {'brief': 60, 'reaction': 30, 'engage': 10}
    return {name: max(0.0, value) for name, value in weights.items()}


def pick(state, mood, intent, rng=None):
    """挑本轮回应模式；连续两轮同模式时给它降温（brief/engage 豁免）。"""
    weights = weights_for(mood, intent)
    last = getattr(state, 'last_mode', None)
    if last in weights and last not in ('brief', 'engage'):
        weights[last] *= 0.4
    total = sum(weights.values())
    if total <= 0:
        mode = 'engage'
    else:
        point = (rng or random).random() * total
        upto = 0.0
        mode = 'engage'
        for name, value in weights.items():
            upto += value
            if point <= upto:
                mode = name
                break
    state.last_mode = mode
    return mode


def instruction(mode):
    text = INSTRUCTIONS.get(mode, '')
    if not text:
        return ''
    return '【本轮回应方式】\n' + text + '\n' + CLOSING
