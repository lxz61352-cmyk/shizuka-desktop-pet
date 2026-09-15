"""Todo command extraction and conservative local date parsing, without GUI/network."""
from datetime import datetime,timedelta
import re
from todo_schedule import build_schedule

CATEGORIES=('生活','研究')

def command(text):
    match=re.match(r'^\s*/(?:待办|todo(?=\s|[:：]|$))\s*[:：]?\s*(.*)$',text,re.I|re.S)
    return match.group(1).strip() if match else None

def category(text):
    return '研究' if re.search(r'研究|论文|文献|实验|讲座|学术|报告会',text,re.I) else '生活'

def number(text):
    if text.isdigit():return int(text)
    digits=dict(zip('零一二三四五六七八九',range(10)));digits['两']=2
    if text=='半':return .5
    if '十' in text:
        left,right=text.split('十',1)
        return (digits.get(left,1)*10+digits.get(right,0))
    return digits.get(text)

def parse_time(text,now=None):
    """Never invent a clock time for a date-only or ambiguous instruction."""
    now=datetime.now() if now is None else now
    text=(text or '').strip()
    if not text:return None,False,''
    if re.search(r'(下次|下一次).*(启动|开机|开电脑)|下次开电脑',text):return None,True,''
    relative=list(re.finditer(r'([0-9]+(?:\.[0-9]+)?|半|[一二两三四五六七八九十]+)\s*(?:个)?(小时|分钟|天)\s*(?:以)?后',text))
    if len(relative)>1:return None,False,text
    if relative:
        rel=relative[0]
        raw=rel[1];amount=float(raw) if re.fullmatch(r'\d+(?:\.\d+)?',raw) else number(raw)
        if amount is not None and amount>0:
            seconds=amount*{'小时':3600,'分钟':60,'天':86400}[rel[2]]
            if seconds<=86400*3650:return (now+timedelta(seconds=seconds)).timestamp(),False,''
    day=now.date()
    date_match=re.search(r'(?:(\d{4})[年/-])?(\d{1,2})[月/-](\d{1,2})(?:日|号)?',text)
    try:
        if date_match:day=day.replace(year=int(date_match[1] or now.year),month=int(date_match[2]),day=int(date_match[3]))
        elif '大后天' in text:day+=timedelta(days=3)
        elif '后天' in text:day+=timedelta(days=2)
        elif '明天' in text:day+=timedelta(days=1)
        else:
            week=re.search(r'(下周|本周|这周|周|星期)([一二三四五六日天])',text)
            if week:
                weekday={'一':0,'二':1,'三':2,'四':3,'五':4,'六':5,'日':6,'天':6}[week[2]]
                delta=weekday-now.weekday()
                if week[1]=='下周':delta+=7
                elif delta<0 and week[1] in ('周','星期'):delta+=7
                day+=timedelta(days=delta)
        clock=re.findall(r'(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)',text)
        chinese=re.findall(r'([0-9一二两三四五六七八九十]+)[点时](半|[0-9一二三四五六七八九十]+分?)?',text)
        if len(clock)+len(chinese)!=1:return None,False,text
        if clock:hour,minute=map(int,clock[0])
        else:
            hour=number(chinese[0][0]);suffix=chinese[0][1]
            minute=30 if suffix=='半' else number(suffix.rstrip('分')) if suffix else 0
        if hour is None or minute is None:return None,False,text
        if re.search('下午|晚上|傍晚|中午',text) and 1<=hour<12:hour+=12
        elif re.search('凌晨|早上|上午',text) and hour==12:hour=0
        target=datetime.combine(day,datetime.min.time()).replace(hour=hour,minute=minute)
        if target<=now:return None,False,'时间已过，请重新选择：'+text
        return target.timestamp(),False,''
    except (ValueError,OverflowError,TypeError):return None,False,'时间无法确认：'+text

def fallback_items(text,now=None):
    parts=[p.strip(' \t-•') for p in re.split(r'[\n；;]+',text) if p.strip()]
    if len(parts)>20:raise ValueError('一次最多整理 20 条待办，请分批输入。')
    result=[]
    for part in parts:
        if len(part)>1000:raise ValueError('单条待办最多1000字，请拆成多个事项。')
        title,notes=local_title_notes(part)
        result.append({'text':title,'category':category(part),'source_text':part,'manual_note':notes,**build_schedule(part,now)})
    return result

def organized_items(payload,source,now=None):
    items=payload.get('items') if isinstance(payload,dict) else None
    if not isinstance(items,list) or not 1<=len(items)<=20:raise ValueError('整理结果数量无效')
    result=[];seen=set();covered=[False]*len(source)
    for item in items:
        if not isinstance(item,dict):raise ValueError('整理结果无效')
        quote=item.get('source');text=item.get('text');hint=item.get('time_text') or ''
        if (not isinstance(quote,str) or not quote.strip() or quote not in source
                or quote in seen or not isinstance(text,str) or not 1<=len(text.strip())<=1000
                or not isinstance(hint,str) or hint and hint not in quote):raise ValueError('整理结果缺少原文依据')
        seen.add(quote)
        start=source.find(quote)
        if any(covered[start:start+len(quote)]):raise ValueError('整理结果引用了重复事项')
        covered[start:start+len(quote)]=[True]*len(quote)
        # Keep date qualifiers even if the model returns only the clock fragment.
        note_quotes=item.get('notes',[])
        if not isinstance(note_quotes,list) or len(note_quotes)>12 or any(not isinstance(n,str) or not n.strip() or n not in quote for n in note_quotes):raise ValueError('备注缺少原文依据')
        # A title may omit surrounding phrasing but must name something the user actually said.
        if text.strip() not in quote:raise ValueError('标题缺少原文依据')
        text=text.strip()
        # A syntactically valid model response may still echo the entire command.
        # Apply the same grounded separation used when the service is unavailable.
        clean_title,local_notes=local_title_notes(text)
        if clean_title in quote:text=clean_title
        note_quotes += [n for n in local_notes.splitlines() if n and n in quote and n!=text]
        if re.fullmatch(r'(?:去听|听|参加|观看|出席).+(?:讲座|报告|会议|课程)',text):
            text=re.sub(r'^(?:去听|听|参加|观看|出席)','',text)
        note_quotes=[re.sub(r'^(?:前往|去|在)\s*','',n) if re.fullmatch(r'(?:前往|去|在).+(?:区|楼|室|馆|厅|院|中心)',n) else n for n in note_quotes]
        result.append({'text':text.strip(),'category':item.get('category') if item.get('category') in CATEGORIES else category(quote),
                       'source_text':quote,'manual_note':'\n'.join(dict.fromkeys(note_quotes)),**build_schedule(quote,now)})
    if any(not used and re.match(r'[\w\u4e00-\u9fff]',char) for char,used in zip(source,covered)):
        raise ValueError('整理结果遗漏了原文，请保留原文重新整理')
    return result


def local_title_notes(text):
    """Conservative fallback: retain the complete source separately, extract only clear spans."""
    title=text.strip();notes=[]
    event=re.search(r'[A-Za-z][A-Za-z0-9 .+/-]{0,40}(?:讲座|报告|会议|课程)',text)
    location=re.search(r'(?:前往|去|在|地点[：:])\s*([^，,。；;]{2,40}?)(?:听|参加|开展|开会|举行|出席|$)',text)
    if event:title=event[0].strip()
    else:
        clauses=[p.strip() for p in re.split(r'[，,。\n]',title) if p.strip()]
        cleaned=[]
        for clause in clauses:
            core=strip_schedule_words(clause)
            if core:cleaned.append(core)
        if cleaned:
            title=cleaned[0]
            notes.extend(cleaned[1:])
        else:title=text.strip()
    if location:
        place=location[1].strip()
        if re.search(r'(?:区|楼|室|馆|厅|院|中心)$',place) and not any(place in n for n in notes):notes.append(place)
    return title.strip() or text,'\n'.join(dict.fromkeys(n for n in notes if n and n!=title))


_AMOUNT=r'(?:\d+(?:\.\d+)?|半|[一二两三四五六七八九十]+)'
_RELATIVE=_AMOUNT+r'\s*(?:个)?(?:小时|分钟|天)\s*(?:以)?后'
_DATE=r'(?:(?:\d{4}[年/-])?\d{1,2}[月/-]\d{1,2}[日号]?|大后天|后天|明天|今天|(?:下周|本周|这周|周|星期)[一二三四五六日天])'
_PERIOD=r'(?:每(?:个)?工作日|每(?:隔)?(?:'+_AMOUNT+r')?(?:个)?(?:天|日|周[一二三四五六日天]?|月(?:\d+|[一二三四五六七八九十]+)[日号]?))'
_CLOCK=r'(?:(?:凌晨|早上|上午|下午|晚上|中午|傍晚)\s*)?(?:\d{1,2}[:：]\d{2}|[0-9一二两三四五六七八九十]+点(?:半|[0-9一二三四五六七八九十]+分?)?)'
_TIME=r'(?:'+_RELATIVE+'|'+_DATE+'|'+_PERIOD+'|'+_CLOCK+r'|有空(?:的)?时(?:候)?|有空再|抽空|下次开电脑|下次开机)'
_INSTRUCTION=r'(?:请(?:你)?|麻烦(?:你)?|帮我|替我|我要|我想|记得|提醒我|叫我|记一下|记下|要)'


def strip_schedule_words(text):
    """Only remove boundary instructions/time spans, never time-like text in a task."""
    value=text.strip()
    previous=None
    while previous!=value:
        previous=value
        value=re.sub(r'^(?:'+_INSTRUCTION+'|'+_TIME+r')\s*','',value).strip(' ，,：:')
    # A trailing reminder clause is scheduling metadata, not a note or a title.
    value=re.sub(r'(?:提前'+_AMOUNT+r'(?:个)?(?:分钟|小时|天)|'+_TIME+r')(?:提醒我?|叫我)\s*$','',value).strip(' ，,')
    return value
