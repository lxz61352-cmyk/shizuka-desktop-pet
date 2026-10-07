"""Desktop opportunity controls, independent of character wording."""
from datetime import datetime, timedelta
import time


def tomorrow(now=None):
    current = datetime.fromtimestamp(time.time() if now is None else now)
    return (current.replace(hour=0, minute=0, second=0, microsecond=0)+timedelta(days=1)).timestamp()


def desktop_eligible(prefs, rows, now=None):
    now = time.time() if now is None else now
    mode = prefs.get('desktop_proactive', '偶尔')
    if mode == '关闭':return False, '已关闭'
    if prefs.get('desktop_paused_until', 0) > now:return False, '今天暂停'
    minute = datetime.fromtimestamp(now).hour*60 + datetime.fromtimestamp(now).minute
    start, end = prefs.get('desktop_start', 0), prefs.get('desktop_end', 1440)
    if not (start <= minute < end if start < end else minute >= start or minute < end):
        return False, '不在允许时段'
    users = [r.get('created', 0) for r in rows if r.get('role') == 'user' and r.get('kind') in ('chat','user','weixin')]
    if users and now-max(users) < prefs.get('desktop_after_chat', 30)*60:
        return False, '刚聊过，先不打扰'
    last = next((r for r in reversed(rows) if r.get('role') == 'assistant' and r.get('kind') in ('proactive','weixin_proactive')), None)
    if last:
        gap = {'很少':6*3600, '偶尔':3*3600, '较活跃':2*3600}.get(mode, 3*3600)
        if now-last.get('created', 0) < gap:return False, '间隔未到'
        if not any(t > last.get('created', 0) for t in users):return False, '等待你回应'
    return True, '等待合适内容和时机'
