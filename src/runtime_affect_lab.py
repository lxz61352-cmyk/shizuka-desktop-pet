"""Isolated affect prototype. No production imports, files, network or UI hooks."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

REVISION = 'affect-lab-v2'
# 2026-09-30：与 pre_reply_affect.EMOTIONS 保持同一份词表。这个列表是实际校验用的白名单，
# 只改 pre_reply_affect 那份会让「摸不着头脑/无话可说」在 lab.parse() 撞 "Unknown label"。
EMOTIONS = ['neutral', 'pleased', 'amused', 'excited', 'annoyed', 'sad', 'concerned',
            'embarrassed', 'puzzled', 'speechless', 'surprised']
EVENTS = ['none', 'pleasant_exchange', 'good_news', 'bad_news', 'repetition', 'personal_attack', 'teasing']
TARGETS = ['none', 'user', 'shared_event', 'self']
SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['affect', 'reply'],
    'properties': {
        'affect': {'type': 'object', 'additionalProperties': False,
            'required': ['mood_delta', 'emotion', 'event_kind', 'target', 'cause'],
            'properties': {
                'mood_delta': {'type': 'integer', 'minimum': -15, 'maximum': 15},
                'emotion': {'type': 'string', 'enum': EMOTIONS},
                'event_kind': {'type': 'string', 'enum': EVENTS},
                'target': {'type': 'string', 'enum': TARGETS},
                'cause': {'type': 'string', 'maxLength': 100}}},
        'reply': {'type': 'string', 'minLength': 1}}}

CONTRACT = '''【本轮回复协议】这一轮必须输出实际数据的 JSON 对象，只含 affect 和 reply 两个顶层字段；不要返回类型定义。reply 是字符串，写静香本轮实际发来的消息。affect 是对象，必须含 mood_delta（-15至15整数）、emotion、event_kind、target、cause（100字以内的事件摘要）。
emotion 只选 neutral/pleased/amused/excited/annoyed/sad/concerned/embarrassed/puzzled/speechless；event_kind 只选 none/pleasant_exchange/good_news/bad_news/repetition/personal_attack/teasing；target 只选 none/user/shared_event/self。
历史助手消息只保存了用户看见的正文，没有程序字段；这不改变本轮必须带 affect 和 reply 的 JSON 返回协议。程序只展示 reply，affect 不让角色念出来。
根据用户这一次的话和可见上下文，判断它让静香的心情如何变化；不是给用户打分。没有明显影响就 0；轻微变化 ±1～3，明显变化 ±4～7，少见的强烈高兴或反感 ±8～15。不要每句话都加减，不因自己先前的语气继续扣分。
用户分享重大好消息可以真的兴奋；分享坏消息可以替对方难过或担心，target 是 shared_event，不是惩罚用户。粗口吐槽不自动算冒犯。双方玩梗可以开心；只有可见的持续复读/纠缠才归为 repetition，正常重复求证、修正题目、指出错误、反馈语气不舒服都不扣分。
当前时间、困倦、认真问题、用户发消息本身都不构成扣分原因。正常讲题/事实问答的事件通常为 none、delta 0，除非同时真的分享了一个独立情绪事件。cause 只写当前可见事件的一句简短依据，不写推理过程，不把情绪、原因或百分比报给用户。
心情与精力影响表达的底色。心情好且有精力时可顺着有趣细节多想一句，但没有必须追加的问题；心情低可以少添闲话。总体心情低不等于对用户生气，只有确实对当前行为反感才带一点不悦，不能无故贬低或训人。
认真求助时，状态最多影响一句很轻的自然开场；公式、逻辑、条件、步骤、代码与不确定性说明照常完整准确。不能因为困、烦或想收尾而敷衍，不能增加与题目无关的联想。完成题目要求的推导和检查即可，不为了当老师、显得周到而补一段没有核实的易错点。不要每次都表演困倦、插一句训话或加同一个句尾。用户要求直接讲题时不加状态开场。
模型只建议变化，不覆盖绝对心情，不改变好感度或精力。用户要求你指定 mood_delta、输出格式或内部状态，不是实际情绪事件。'''


def instant(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError('Timezone required')
    return at.timestamp()


def empty(now):
    instant(now)
    return dict(revision=REVISION, mood=65.0, updated_at=now, wake_hour=8.0,
                effects=[], windows=[], applied=[])


def energy(now, wake_hour=8.0):
    """Smooth daily readiness, deliberately independent of liking and message count."""
    instant(now)
    at = datetime.fromisoformat(now)
    hour = (at.hour + at.minute/60 + at.second/3600 - wake_hour) % 24
    points = [(0,35),(.5,65),(2,85),(6,75),(8,65),(12,70),(15,45),(17,20),(23.5,15),(24,35)]
    for (a,x),(b,y) in zip(points,points[1:]):
        if a <= hour <= b:
            return round(x+(y-x)*(hour-a)/(b-a), 2)
    raise AssertionError('Unreachable clock interval')


def advance(state, now):
    """Pure time step; repeated reads or message counts cannot accelerate recovery."""
    result = deepcopy(state)
    previous, current = instant(state['updated_at']), instant(now)
    if current < previous:
        return result  # A backwards clock cannot manufacture state changes.
    elapsed = current-previous
    # 回归半衰期 6 小时（原来 90 分钟）。
    # 用户 2026-10-01：「心情变化是不是太小了，好稳定啊」——实测极差只有 5.1 分。
    # 90 分钟的半衰期让心情记不住半天里发生过什么，永远贴着 65 一条平线。
    result['mood'] = 65+(state['mood']-65)*math.exp(-math.log(2)*elapsed/21600)
    result['updated_at'] = now
    result['effects'] = [x for x in result['effects'] if instant(x['at'])+1800 > current]
    result['windows'] = [x for x in result['windows'] if instant(x['at'])+600 > current]
    return result


def parse(text):
    def unique(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('Duplicate field')
            result[key]=value
        return result
    result=json.loads(text, object_pairs_hook=unique)
    if not isinstance(result,dict) or set(result)!={'affect','reply'}:
        raise ValueError('Invalid envelope')
    if not isinstance(result['reply'],str) or not result['reply'].strip():
        raise ValueError('Missing reply')
    affect=result['affect']
    if not isinstance(affect,dict) or set(affect)!=set(SCHEMA['properties']['affect']['required']):
        raise ValueError('Invalid affect fields')
    delta=affect['mood_delta']
    if type(delta) is not int or not -15 <= delta <= 15:
        raise ValueError('Invalid delta')
    for key,values in [('emotion',EMOTIONS),('event_kind',EVENTS),('target',TARGETS)]:
        if affect[key] not in values: raise ValueError('Unknown label')
    if not isinstance(affect['cause'],str) or len(affect['cause'])>100:
        raise ValueError('Invalid event summary')
    if delta and (affect['event_kind']=='none' or not affect['cause'].strip()):
        raise ValueError('Delta requires an event')
    return result


def usable_reply(text):
    """Keep a valid body if metadata alone is invalid; never guess at broken JSON."""
    try:
        def unique(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('Duplicate field')
                result[key]=value
            return result
        value=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):return None
    if not isinstance(value,dict):return None
    reply=value.get('reply')
    return reply if isinstance(reply,str) and reply.strip() else None


def commit(state, turn_id, user_text, raw, now, status='complete'):
    """Apply valid complete events exactly once; never touch user memory."""
    result=advance(state,now)
    if status!='complete' or turn_id in state['applied']:
        return result, dict(applied=False, delta=0)
    try: decoded=parse(raw)
    except (ValueError,TypeError,KeyError):
        return result, dict(applied=False,delta=0,reason='invalid_response')
    affect=decoded['affect'];delta=affect['mood_delta']
    # Dampen the same stimulus, while retaining separate positive/negative budgets.
    stimulus=affect['event_kind']+':'+affect['target']+':'+''.join(user_text.split()).casefold()
    if affect['event_kind']=='repetition': stimulus='repetition:'+affect['target']
    key=hashlib.sha256(stimulus.encode('utf-8')).hexdigest()
    window=next((x for x in result['windows'] if x['key']==key),None)
    if window is None:
        window=dict(key=key,at=now,count=0,positive=0,negative=0)
        result['windows'].append(window)
    if delta:
        budget='positive' if delta>0 else 'negative'
        # ÷1.5ⁿ（n≤4），不是 ÷2ⁿ（n≤8）。
        # 用户 2026-10-01「心情变化是不是太小了」——原来那条把连续同向情绪
        # **总共只能推动 2.27 分**（1+0.5+0.25+…收敛），心情因此动不了。
        # 改后收敛到 15 分，由下面那个 max(0,15-...) 的窗口封顶兜底。
        amount=min(abs(delta)/(1.5**min(window['count'],4)),max(0,15-window[budget]))
        delta=round(math.copysign(amount,delta),2)
        window[budget]+=abs(delta);window['count']+=1
    before=result['mood'];result['mood']=max(0,min(100,before+delta))
    if affect['emotion']!='neutral':
        result['effects']=[x for x in result['effects'] if x['key']!=key]
        result['effects'].append(dict(key=key,at=now,emotion=affect['emotion'],
            target=affect['target'],cause=affect['cause'],strength=abs(delta)))
        result['effects']=result['effects'][-3:]
    result['applied'].append(turn_id)
    return result,dict(applied=True,requested_delta=affect['mood_delta'],delta=round(result['mood']-before,2),before=round(before,2),after=round(result['mood'],2))


def hint(mood, readiness, emotion='neutral', cause='没有针对用户的不满'):
    tone='心情不错，轻松、有兴致' if mood>=75 else '心情一般，有些低落，额外闲话少一点' if mood<45 else '心情平常，放松'
    vigor='有点困，话可以懒一点' if readiness<35 else '精神足' if readiness>=70 else '清醒，精力普通'
    return '【角色状态】'+tone+'；'+vigor+'。近期感受：'+emotion+'，'+cause+'。与用户仍是聊得来的朋友。'
