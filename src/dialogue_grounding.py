"""Fresh time, current task state and a shared gate for unsolicited speech."""
from datetime import datetime,timezone
import hashlib,json,re,threading,time
from todo_schedule import EVENT_WORDS

PASSIVE_SOURCES={'启动问候','开机待办提醒','主动搭话','前台程序','粘贴板','截图'}
# 粘贴板 / 截图这类「随复制随反应」的不按主动搭话间隔卡：只留一点防抖时间，
# 靠「同一段内容回应过就不再重复」来克制，内容换了才重新说话。
CLIP_PASSIVE_SOURCES={'粘贴板','截图','识图'}
CLIP_PASSIVE_GAP=3.0           # 粘贴板（文字）：仅防抖
IMAGE_PASSIVE_GAP=5.0          # 截图 / 识图（图片）：仅防抖
CLIP_MEMORY=12                 # 记住最近回应过的内容条数
GROUNDING_RULES=('当前日期与时间只以本轮系统时钟为准，历史中的今天、明天按原消息日期理解。'
 '当前待办状态高于历史安排；已完成事项不要再催，未勾选只表示记录未完成，不能断言用户没做。'
 '活动开始时间与提醒时间不同；已过开始时间不自动推到明天，不推断用户是否参加。'
 '没有用户本轮说明或本轮实际图片，不描写现实桌面、杯子水量或水是否动过，不将待办当作视觉观察。'
 '科研讨论和论文推荐仍以您称呼，自然需要时称主人，保留专业内容与证据，不切换为你、同学或用户。')

def clock_context(now=None):
    current=datetime.fromtimestamp(time.time() if now is None else now,timezone.utc).astimezone()
    return '本轮系统时钟：'+current.isoformat(timespec='seconds')+'（本机时区）。'+GROUNDING_RULES

def is_event(item,options):
    source=options.get('source_text') or item.get('text','')
    return bool(re.search(EVENT_WORDS,item.get('text','')+' '+source)
                and not re.search(r'写报告|撰写报告|修改报告|读报告|看报告',source))

def event_expired(item,options,now=None):
    event=options.get('schedule',{}).get('event_at')
    return bool(event and is_event(item,options) and event < (time.time() if now is None else now))

def stamp(value):
    return datetime.fromtimestamp(value,timezone.utc).astimezone().isoformat(timespec='minutes') if value else None

def todo_fact(item,options,now=None):
    now=time.time() if now is None else now
    state='已完成' if item.get('done') else '已过开始时间，是否参加未知' if event_expired(item,options,now) else '待办未标完成，不代表现实尚未执行'
    return {'id':item['id'],'事项':item['text'],'状态':state,'提醒时间':stamp(item.get('due')),
            '开始时间':stamp(options.get('schedule',{}).get('event_at')) if is_event(item,options) else None,
            '备注':options.get('manual_note','')}

def passive_text_ok(text):
    # These claims cannot be grounded by the time/task/window metadata used by passive speech.
    return not re.search(r'(?:水|杯子).{0,8}(?:没动|未动|没喝|还满|还是满|仍然满)|桌上.{0,8}水.{0,8}(?:满|没)',text)

def _clip_norm(text):
    return re.sub(r'\s+',' ',(text or '')).strip()

def clip_image_signature(data):
    return hashlib.sha1(data).hexdigest()

class GroundingMixin:
    def _clip_repeat(self,kind,payload):
        """这段内容是否已经回应过。文字还认「同一段被逐渐加长/截短」的情况
        （反复复制同一处、选区慢慢变大），避免对同一段内容反复点评。"""
        recent=list(getattr(self,'_clip_recent',[]))
        if kind=='image':
            return any(k=='image' and v==payload for k,v in recent)
        text=_clip_norm(payload)
        if not text:return True
        for k,v in recent:
            if k!='text':continue
            if v==text:return True
            if min(len(v),len(text))>=6 and (v in text or text in v):return True
        return False

    def _clip_remember(self,kind,payload):
        recent=[(k,v) for k,v in getattr(self,'_clip_recent',[]) if k!=kind or v!=(
            _clip_norm(payload) if kind=='text' else payload)]
        recent.append((kind,_clip_norm(payload) if kind=='text' else payload))
        self._clip_recent=recent[-CLIP_MEMORY:]

    def _todo_state_context(self):
        items=list(getattr(self,'todos',[]))
        return [todo_fact(row,self._todo_options(row)) for row in items[-60:]]

    def _passive_snapshot(self):
        rows=[]
        for row in getattr(self,'todos',[]):
            opt=self._todo_options(row)
            rows.append([row.get(k) for k in ('id','text','done','due','on_boot')]+[
                opt.get('schedule'),opt.get('manual_note'),opt.get('notes'),event_expired(row,opt)])
        return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def _passive_allowed(self,gap=None,ignore_user=False):
        last=getattr(self,'_last_passive_at',-1e9)
        if not ignore_user:
            last=max(last,getattr(self,'_last_user_dialogue_at',-1e9))
        if gap is None:
            gap=max(1,getattr(self,'_idle_minutes',5))*60
        return (not getattr(self,'_quitting',False) and not getattr(self,'_computer_state',{}).get('busy')
                and time.monotonic()-last>=gap)

    def _claim_passive(self,text,source=None):
        if not hasattr(self,'_passive_lock'):self._passive_lock=threading.Lock()
        # 粘贴板 / 截图这类「随复制随反应」的只留一点防抖，不按主动搭话间隔卡；
        # 也不占用主动搭话的间隔，否则粘贴板一多，主动搭话就再也轮不到。
        clip=source in CLIP_PASSIVE_SOURCES
        gap=IMAGE_PASSIVE_GAP if source in ('截图','识图') else CLIP_PASSIVE_GAP
        with self._passive_lock:
            if not passive_text_ok(text):return False
            if clip:
                if time.monotonic()-getattr(self,'_last_clip_at',-1e9)<gap:return False
                if not self._passive_allowed(0,ignore_user=True):return False
                self._last_clip_at=time.monotonic();return True
            if not self._passive_allowed():return False
            self._last_passive_at=time.monotonic();return True

    def _deliver_passive(self,text,source,snapshot):
        if text and snapshot==self._passive_snapshot() and self.visible and not self._is_speaking():
            self.say(text,source=source)
