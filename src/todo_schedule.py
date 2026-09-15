"""Local, inspectable reminder policy: event time, advance notice and recurrence."""
from datetime import datetime,timedelta
import calendar,re

MORNING_HOUR=9
EVENT_WORDS=r'讲座|报告会|报告|会议|开会|面试|答辩|课程|上课|预约|航班|火车|高铁'
DIGITS='零一二三四五六七八九'

def amount(value):
    if value=='半':return .5
    if value.isdigit():return int(value)
    if value=='两':return 2
    if '十' in value:
        left,right=value.split('十',1)
        return (DIGITS.index(left) if left else 1)*10+(DIGITS.index(right) if right else 0)
    return DIGITS.index(value) if value in DIGITS else None

def lead_minutes(text):
    if re.search(r'不(?:用|要|必)提前|(?:开始|到时|准点|当天)再提醒',text):return 0,'explicit'
    found=re.search(r'提前\s*(\d+|半|[一二两三四五六七八九十]+)\s*(?:个)?\s*(分钟|小时|天)',text)
    if found:
        n=amount(found[1]);value=n*{'分钟':1,'小时':60,'天':1440}[found[2]] if n is not None else -1
        if 0<=value<=43200:return int(value),'explicit'
        raise ValueError('提前提醒最多支持30天')
    if re.search(EVENT_WORDS,text) and not re.search(r'写报告|撰写报告|修改报告|读报告|看报告',text):return 60,'inferred_event'
    return 0,'none'

def _clock(text):
    # Parsing a future reference day retains the established local clock validation.
    from todo_model import parse_time
    text=re.sub(r'(?:周|星期)[一二三四五六日天]','',text)
    matches=re.findall(r'\d{1,2}[:：]\d{2}|[0-9一二两三四五六七八九十]+点(?:半|[0-9一二三四五六七八九十]+分?)?',text)
    if not matches:return MORNING_HOUR,0
    if len(matches)!=1:raise ValueError('周期提醒时间不唯一')
    prefix=next((p for p in ('凌晨','早上','上午','中午','下午','傍晚','晚上') if p in text),'')
    due,_,_=parse_time('明天'+prefix+matches[0],datetime(2026,1,1))
    if due is None:raise ValueError('周期提醒时间无效')
    target=datetime.fromtimestamp(due);return target.hour,target.minute

def recurrence(text,now):
    if re.search(r'不(?:用|要|必)提醒|不设置提醒',text):return None
    free=bool(re.search(r'有空(?:的)?时(?:候)?|有空了|有空再|抽空|空了再',text))
    frequency=None;interval=1;weekdays=[];month_day=now.day
    if re.search(r'每个?工作日',text):frequency='weekly';weekdays=list(range(5))
    else:
        period=re.search(r'每(?:隔)?\s*(\d+|[一二两三四五六七八九十]+)?\s*(?:个)?(天|日|周|星期|月)',text)
        if period:
            interval=int(amount(period[1])) if period[1] else 1
            if not 1<=interval<=366:raise ValueError('周期应在1至366个单位之间')
            frequency={'天':'daily','日':'daily','周':'weekly','星期':'weekly','月':'monthly'}[period[2]]
            if frequency=='weekly':
                tail=text[period.end():]
                days=re.match(r'([一二三四五六日天](?:(?:、|和|及|与|,|，)(?:周|星期)?[一二三四五六日天])*)',tail)
                weekdays=sorted({'一':0,'二':1,'三':2,'四':3,'五':4,'六':5,'日':6,'天':6}[ch] for ch in days[0] if ch in '一二三四五六日天') if days else [now.weekday()]
            if frequency=='monthly':
                day=re.search(r'每(?:个)?月\s*(\d{1,2}|[一二三四五六七八九十]+)(?:号|日)',text)
                if '月末' in text or '月底' in text:month_day=31
                elif day:month_day=int(amount(day[1]))
                if not 1<=month_day<=31:raise ValueError('每月日期应在1至31日之间')
    explicit=bool(frequency)
    if not frequency and free:frequency='daily'
    if not frequency:return None
    hour,minute=(MORNING_HOUR,0) if free and not re.search(r'点|\d[:：]\d',text) else _clock(text)
    return {'frequency':frequency,'interval':interval,'weekdays':weekdays,'month_day':month_day,
            'hour':hour,'minute':minute,'anchor_date':now.date().isoformat(),'until_done':free and not explicit}

def occurrence(rule,reference,direction=1,inclusive=False):
    """Nearest occurrence relative to a local datetime, with stable monthly anchoring."""
    anchor=datetime.fromisoformat(rule['anchor_date']).date();frequency=rule['frequency']
    day=reference.date();step=1 if direction>0 else -1
    # At most 366 monthly intervals are supported; calendar search remains bounded.
    limit=max(800,rule.get('interval',1)*367+32)
    for _ in range(limit):
        eligible=False;delta=(day-anchor).days
        if delta>=0:
            if frequency=='daily':eligible=delta%rule['interval']==0
            elif frequency=='weekly':
                weeks=((day-timedelta(days=day.weekday()))-(anchor-timedelta(days=anchor.weekday()))).days//7
                eligible=weeks%rule['interval']==0 and day.weekday() in rule['weekdays']
            elif frequency=='monthly':
                months=(day.year-anchor.year)*12+day.month-anchor.month
                eligible=months%rule['interval']==0 and day.day==min(rule['month_day'],calendar.monthrange(day.year,day.month)[1])
        event=datetime.combine(day,datetime.min.time()).replace(hour=rule['hour'],minute=rule['minute'])
        if eligible and ((event>reference if direction>0 else event<reference) or inclusive and event==reference):return event
        if direction<0 and day<anchor:return None
        day+=timedelta(days=step)
    raise ValueError('无法找到下次周期时间')

def build_schedule(text,now=None):
    from todo_model import parse_time
    now=now or datetime.now()
    if re.search(r'不(?:用|要|必)提醒|不设置提醒',text):return {'due':None,'on_boot':False,'time_hint':'','schedule':{'version':1,'lead_minutes':0,'event_at':None,'rule':None,'disabled':True}}
    rule=recurrence(text,now);lead,reason=lead_minutes(text)
    if rule:
        if rule.get('until_done'):lead=0;reason='free_time_policy'
        event=occurrence(rule,now+timedelta(minutes=lead))
        return {'due':event.timestamp()-lead*60,'on_boot':False,'time_hint':'',
                'schedule':{'version':1,'event_at':event.timestamp(),'lead_minutes':lead,'lead_reason':reason,'rule':rule}}
    # Explicit reminder clocks override inferred advance notice. Carry the event's date qualifier.
    cleaned=re.sub(r'提前\s*(\d+|半|[一二两三四五六七八九十]+)\s*(?:个)?(分钟|小时|天)(?:提醒我?|叫我)?','',text)
    parts=re.split(r'[，,。；;]',cleaned);reminder_part=next((p for p in parts if re.search(r'提醒|叫我',p) and re.search(r'点|\d[:：]\d',p)),None)
    event_parts=[p for p in parts if p!=reminder_part]
    explicit_due=None
    if reminder_part and event_parts and re.search(r'点|\d[:：]\d',''.join(event_parts)):
        prefix=re.search(r'(?:\d{4}[年/-])?\d{1,2}[月/-]\d{1,2}[日号]?|大后天|后天|明天|今天|(?:下周|本周|这周|周|星期)[一二三四五六日天]',''.join(event_parts))
        explicit_due,_,_=parse_time((prefix[0] if prefix else '')+reminder_part,now)
        cleaned='，'.join(event_parts)
    due,boot,hint=parse_time(cleaned,now)
    if boot:return {'due':None,'on_boot':True,'time_hint':'','schedule':{'version':1,'event_at':None,'lead_minutes':0,'rule':None}}
    event=due
    if due is not None:
        if explicit_due is not None:lead=max(0,round((due-explicit_due)/60));due=explicit_due;reason='explicit_clock'
        elif reminder_part and not re.search(r'点|\d[:：]\d',''.join(event_parts)):
            lead=0;reason='explicit_clock'
        else:due=max(now.timestamp(),due-lead*60)
    if not re.search(r'点|时|天|周|星期|\d[:：/-]',text):hint=''
    return {'due':due,'on_boot':False,'time_hint':hint,
            'schedule':{'version':1,'event_at':event,'lead_minutes':lead,'lead_reason':reason,'rule':None}}

def next_schedule(schedule,after):
    from copy import deepcopy
    result=deepcopy(schedule);lead=result.get('lead_minutes',0)
    event=occurrence(result['rule'],datetime.fromtimestamp(after)+timedelta(minutes=lead))
    result['event_at']=event.timestamp()
    return result,event.timestamp()-lead*60

def latest_due_schedule(schedule,now):
    from copy import deepcopy
    result=deepcopy(schedule);lead=result.get('lead_minutes',0)
    event=occurrence(result['rule'],datetime.fromtimestamp(now)+timedelta(minutes=lead),-1,True)
    if event is None:return None,None
    result['event_at']=event.timestamp();return result,event.timestamp()-lead*60

def rule_label(rule):
    if not rule:return '不重复'
    unit={'daily':'天','weekly':'周','monthly':'月'}[rule['frequency']]
    label='每'+(str(rule['interval']) if rule['interval']!=1 else '')+unit
    if rule['frequency']=='weekly':label+='、'.join('一二三四五六日'[d] for d in rule['weekdays'])
    if rule['frequency']=='monthly':label+=str(rule['month_day'])+'日'
    label+=f" {rule['hour']:02d}:{rule['minute']:02d}"
    if rule.get('until_done'):label+='，完成后停止'
    return label

def schedule_facts(item,options):
    schedule=options.get('schedule',{});event=schedule.get('event_at');due=item.get('due');parts=[]
    if event and event!=due:parts.append('事项 '+datetime.fromtimestamp(event).strftime('%m-%d %H:%M'))
    if due:parts.append('提醒 '+datetime.fromtimestamp(due).strftime('%m-%d %H:%M'))
    elif item.get('on_boot'):parts.append('下次启动提醒')
    else:parts.append('未定提醒时间')
    if schedule.get('lead_minutes') and event and due:
        actual=max(0,int((event-due)//60))
        if actual:parts.append('提前 '+str(actual)+' 分钟')
    if schedule.get('rule'):parts.append(rule_label(schedule['rule']))
    return '；'.join(parts)
