"""Persistent, opt-in conversation opportunities; silence is never a mood penalty."""
import hashlib
import re
import time

DEFAULTS = dict(enabled=False, start=600, end=1320, daily_limit=2, gap_minutes=180,
                awaiting=False, last_sent=0, last_user=0, paused_until=0, history=[], attempts=[])
HELP = ('/主动 开启 · /主动 关闭 · /主动 状态\n'
        '/主动 暂停：今天暂停\n/主动 时间 10:00-22:00\n'
        '/主动 频率 少 / 偶尔 / 多（每天最多 1 / 2 / 3 次）\n'
        '发出后未回应就暂停后续闲聊；待办提醒不受影响。电脑和桌宠需要保持运行。')


def state(data):
    from copy import deepcopy
    result=deepcopy(DEFAULTS)
    result.update(data.get('proactive_chat') or {})
    result['enabled']=result['enabled'] is True
    return result


def clock_text(minutes):
    return '%02d:%02d' % divmod(minutes,60)


def command(text, data, now=None):
    """Exact slash commands only; quoted/narrated requests never toggle settings."""
    text=text.strip()
    if not re.match(r'^[/／]主动(?:\s|$)',text):return None
    now=time.time() if now is None else now
    value=state(data);action=text[3:].strip()
    if action in ('开启','开','on'):
        value.update(enabled=True,awaiting=False,paused_until=0,last_user=now)
    elif action in ('关闭','关','off'):value['enabled']=False
    elif action in ('暂停','今天暂停'):
        day=list(time.localtime(now));day[3:6]=[0,0,0];day[2]+=1
        value['paused_until']=time.mktime(tuple(day))
    elif action.startswith('时间 '):
        m=re.fullmatch(r'时间\s+(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})',action)
        if not m:return value,'格式：/主动 时间 10:00-22:00'
        h1,m1,h2,m2=map(int,m.groups())
        if max(h1,h2)>23 or max(m1,m2)>59 or (h1,m1)==(h2,m2):
            return value,'时间需为不同的两个有效时刻，例如 10:00-22:00。'
        value.update(start=h1*60+m1,end=h2*60+m2)
    elif action.startswith('频率 '):
        preset={'少':(1,360),'偶尔':(2,180),'多':(3,120)}.get(action[3:].strip())
        if not preset:return value,'可选：/主动 频率 少 / 偶尔 / 多'
        value.update(daily_limit=preset[0],gap_minutes=preset[1])
    elif action not in ('','状态','帮助'):return value,HELP
    return value,describe(value,now)+('\n'+HELP if action in ('','帮助') else '')


def describe(value,now=None):
    now=time.time() if now is None else now
    status='关闭' if not value['enabled'] else ('今天暂停' if value['paused_until']>now else
            '等待你回应，后续闲聊暂停' if value['awaiting'] else '已开启，等待合适内容和时机')
    return ('主动搭话：'+status+'。\n允许时间 '+clock_text(value['start'])+'–'+clock_text(value['end'])+
            '，每天最多 '+str(value['daily_limit'])+' 次，至少间隔 '+str(value['gap_minutes'])+' 分钟。')


def eligible(value, now=None):
    now=time.time() if now is None else now
    if not value['enabled']:return False,'已关闭'
    if value['awaiting']:return False,'等待回应'
    if value['paused_until']>now:return False,'暂停中'
    minute=time.localtime(now).tm_hour*60+time.localtime(now).tm_min
    start,end=value['start'],value['end']
    inside=start<=minute<end if start<end else minute>=start or minute<end
    if not inside:return False,'不在允许时段'
    if not value['last_user']:return False,'等待你先发一条消息'
    if now-value['last_user']<30*60:return False,'刚聊过，先不打扰'
    if now-value['last_sent']<value['gap_minutes']*60:return False,'间隔未到'
    # Generation attempts are also bounded, including skipped/failed opportunities.
    attempts=[t for t in value['attempts'] if now-t<86400]
    if attempts and now-attempts[-1]<1800:return False,'等待下次机会'
    if len(attempts)>=max(3,value['daily_limit']*2):return False,'今日尝试已够'
    day=time.strftime('%Y-%m-%d',time.localtime(now))
    count=sum(time.strftime('%Y-%m-%d',time.localtime(r['at']))==day for r in value['history'])
    if count>=value['daily_limit']:return False,'今日次数已够'
    return True,'可以尝试'


PRIVATE = re.compile(r'性|色情|荤|黄腔|住址|身份证|密码|手机号|生病|抑郁|病历|政治|自杀|伤害|考试|复习|作业|没完成')
INTEREST = re.compile(r'喜欢|爱好|有兴趣|感兴趣|最近在玩|最近在看|好吃|好看|有意思')


def candidates(memories,rows,history,now=None):
    """Conservative sourced topics, never invented off-screen observations."""
    from memory_lifecycle import active
    now=time.time() if now is None else now
    used={r.get('topic') for r in history if now-r.get('at',0)<7*86400}
    blocked=[]
    for row in rows[-100:]:
        if row.get('role')!='user':continue
        match=re.search(r'(?:不想聊|别再说|别提|不要提|不聊|别问|不要问|别聊)([^，。！？\n]{2,20})',row.get('text',''))
        if match:
            term=match[1].strip(' 了吧啊呀嘛')
            if len(term)>=2:blocked.append(term)
    options=[]
    for row in memories:
        text=row.get('content','')
        if active(row,now) and INTEREST.search(text) and not PRIVATE.search(text) and not re.search(r'不喜欢|不想聊|别提|不要提|讨厌',text):
            options.append(dict(id='memory:'+row['id'],text=text,at=row.get('created'),kind='偏好'))
    for row in rows[-80:]:
        text=row.get('text','')
        if (row.get('role')=='user' and row.get('kind') in ('chat','user','weixin')
                and 1800<now-row.get('created',0)<2*86400 and INTEREST.search(text)
                and not PRIVATE.search(text) and not re.search(r'不喜欢|不想聊|别提|不要提|讨厌',text) and len(text)<250):
            options.append(dict(id='chat:'+row['id'],text=text,at=row.get('created'),kind='近期分享'))
    result=[]
    for row in options:
        if any(term in row['text'] for term in blocked):continue
        row['topic']=hashlib.sha256(re.sub(r'\W','',row['text']).encode()).hexdigest()[:20]
        if row['topic'] not in used:result.append(row)
    return result[-8:]


def acceptable(text, history):
    if not isinstance(text,str) or not 2<=len(text.strip())<=220:return False
    if re.search(r'怎么不[回理]|(?:^|[，。！？\s])在吗|怎么还不|该.{0,5}(复习|学习|睡觉)|喝[口点]?水|记得.{0,6}(完成|复习)',text):return False
    from difflib import SequenceMatcher
    return all(SequenceMatcher(None,text,r.get('text','')).ratio()<.72 for r in history[-12:])


def invented_observation(text):
    """No live observations are available to this mode; conservative rejection."""
    return bool(re.search(r'窗外|我就没关窗|我(?:刚才|刚刚|刚|今天|昨天|上次).{0,16}(?:吃|买|遇|碰|去|看见|听见|看到|听到)|'
                          r'(?:^|[，。！？\s])(?:刚才|刚刚).{0,10}(?:遇到|看见|听见|看到|听到)|'
                          r'我(?:这边|这里)?.{0,5}(?:刚忙完|刚下课|刚下班|在上班|有点闲|没什么事|刚结束|排练完|刚起床|睡醒)|'
                          r'(?:^|[，。！？\s])刚(?:忙完|下班|下课|起床|排练完)|'
                          r'上次有人|我吃到|我在.{0,8}(?:店里|街上|路上)|今天排练|刚才.{0,10}(?:下雨|下雪|出太阳)',text))
