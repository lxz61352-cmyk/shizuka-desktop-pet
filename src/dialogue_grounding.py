"""Fresh time, current task state and a shared gate for unsolicited speech."""
from datetime import datetime,timezone
import hashlib,json,re,threading,time
from todo_schedule import EVENT_WORDS

PASSIVE_SOURCES={'启动问候','开机待办提醒','主动搭话','前台程序','粘贴板','截图'}
# 粘贴板 / 截图这类「随复制随反应」的不按主动搭话间隔卡：只留一点防抖时间，
# 靠「同一段内容回应过就不再重复」来克制，内容换了才重新说话。
CLIP_PASSIVE_SOURCES={'粘贴板','截图'}
IMAGE_PASSIVE_SOURCES={'截图'}    # 图片类反应另给更长的防抖
CLIP_PASSIVE_GAP=3.0           # 粘贴板（文字）：仅防抖
IMAGE_PASSIVE_GAP=5.0          # 截图 / 识图（图片）：仅防抖
CLIP_MEMORY=200                # 记住最近回应过的内容条数（落盘，重启不清空）
CLIP_RECENT_TTL=14*24*3600     # 已回应记录保留多久（秒）：太老的记录不再参与去重
PHASH_TOLERANCE=16             # 图片感知哈希（dHash 16x16=256bit）允许的汉明距离：近似画面算同一张
GROUNDING_RULES=('当前日期与时间只以本轮系统时钟为准，历史中的今天、明天按原消息日期理解。'
 '当前待办状态高于历史安排；已完成事项不要再催，未勾选只表示记录未完成，不能断言用户没做。'
 '活动开始时间与提醒时间不同；已过开始时间不自动推到明天，不推断用户是否参加。'
 '没有用户本轮说明或本轮实际图片，不描写现实桌面、杯子水量或水是否动过，不将待办当作视觉观察。'
 '科研讨论和论文推荐保留专业内容与证据，不要切换成同学、用户这类旁白视角。')

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

def _text_overlap(a,b):
    """两段话的字符二元组重合度（0~1），用来判断主动发言是不是又说了同一句。"""
    if not a or not b:return 0.0
    sa={a[i:i+2] for i in range(len(a)-1)}
    sb={b[i:i+2] for i in range(len(b)-1)}
    if not sa or not sb:return 0.0
    return len(sa&sb)/max(1,min(len(sa),len(sb)))

def clip_image_signature(data):
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()

def clip_image_phash(img):
    """dHash 16x16（256bit，hex 64 位）：画面相近时哈希也相近，用于「同一张图换个程序再复制」的去重。"""
    try:
        small=img.convert('L').resize((17,16))
        px=small.tobytes()
        bits=''.join('1' if px[r*17+c]>px[r*17+c+1] else '0' for r in range(16) for c in range(16))
        return format(int(bits,2),'064x')
    except Exception:
        return ''

def _hamming_hex(a,b):
    try:
        return bin(int(a,16)^int(b,16)).count('1')
    except Exception:
        return 1<<30

class GroundingMixin:
    def _clip_recent_lock(self):
        lock=getattr(self,'_clip_recent_lock_obj',None)
        if lock is None:
            lock=threading.Lock();self._clip_recent_lock_obj=lock
        return lock

    def _clip_repeat(self,kind,payload):
        """这段内容是否已经回应过。文字还认「同一段被逐渐加长/截短」的情况
        （反复复制同一处、选区慢慢变大），避免对同一段内容反复点评；
        图片除了 sha1 精确匹配，还按 dHash 近似匹配（重新截图 / 换程序复制同一画面也算重复）。"""
        now=time.time()
        text=_clip_norm(payload) if kind=='text' else ''
        if kind=='text' and not text:return True
        with self._clip_recent_lock():
            recent=list(getattr(self,'_clip_recent',[]))
        for k,v,at in recent:
            if now-at>CLIP_RECENT_TTL:continue
            if kind=='image':
                if k=='image' and v==payload:return True
            elif kind=='phash':
                if k=='phash' and _hamming_hex(v,payload)<=PHASH_TOLERANCE:return True
            else:
                if k!='text':continue
                if v==text:return True
                if min(len(v),len(text))>=6 and (v in text or text in v):return True
        return False

    def _clip_remember(self,kind,payload):
        now=time.time()
        value=_clip_norm(payload) if kind=='text' else payload
        save=getattr(self,'_save_clip_recent',None)
        # 落盘也放进锁里：并发 remember 时保证写出去的是最新一份，别被旧列表覆盖
        with self._clip_recent_lock():
            recent=[(k,v,at) for k,v,at in getattr(self,'_clip_recent',[]) if not (k==kind and v==value)]
            recent.append((kind,value,now))
            recent=recent[-CLIP_MEMORY:]
            self._clip_recent=recent
            if save:
                try:save(recent)
                except Exception:pass

    def _proactive_recent_ok(self,text):
        """主动发言去重：和最近几条太像就不说（主动搭话/窗口问候最容易复读）。"""
        norm=_clip_norm(text)
        if not norm:return False
        for value,_at in getattr(self,'_proactive_recent',[])[-6:]:
            if value==norm:return False
            if min(len(value),len(norm))>=6 and (value in norm or norm in value):return False
            if _text_overlap(value,norm)>=0.7:return False
        return True

    def _proactive_remember(self,text):
        norm=_clip_norm(text)
        recent=[(v,at) for v,at in getattr(self,'_proactive_recent',[]) if v!=norm]
        recent.append((norm,time.time()))
        self._proactive_recent=recent[-20:]

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
        gap=IMAGE_PASSIVE_GAP if source in IMAGE_PASSIVE_SOURCES else CLIP_PASSIVE_GAP
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
