"""Memory applicability, separate from archive retention and pinning."""
import time,re


def expiry(row):
    if isinstance(row.get('expires_at'),(int,float)):return row['expires_at']
    text=row.get('content','');at=row.get('source_time') or row.get('created')
    if re.search(r'喜欢|爱好|标题|歌名|名字|每天|总是',text):return None
    if not isinstance(at,(int,float)):return None
    days=2 if re.search(r'明天|明晚',text) else 1 if re.search(r'今天|今晚|今日',text) else None
    if re.search(r'这周|本周',text):days=7-time.localtime(at).tm_wday
    if days is None:return None
    local=list(time.localtime(at));local[2]+=days;local[3:6]=[0,0,0]
    return time.mktime(tuple(local))


def active(row,now=None):
    now=time.time() if now is None else now
    if row.get('status','active') in ('superseded','completed','archived'):return False
    expires=expiry(row)
    return not isinstance(expires,(int,float)) or expires<=0 or expires>now


def label(row,now=None):
    if row.get('status')=='completed':return '已结束'
    if row.get('status')=='superseded':return '已取代'
    if not active(row,now):return '已过期'
    return '临时' if expiry(row) else '长期'


def scope_note(rows,now=None):
    now=time.time() if now is None else now
    finished=[{'id':r.get('id'),'内容':r.get('content',''),'状态':label(r,now)} for r in rows
              if not active(r,now)]
    return finished


def undo_edit(current,before,after):
    from copy import deepcopy
    result=deepcopy(current);old={r['id']:r for r in before};new={r['id']:r for r in after};conflicts=0
    fields=('content','pinned','status','expires_at')
    for ident,prior in old.items():
        latest=next((r for r in result if r['id']==ident),None)
        changed=new.get(ident)
        if changed is None:
            if latest is None:result.append(deepcopy(prior))
            else:conflicts+=1
        elif latest:
            for key in fields:
                if prior.get(key)!=changed.get(key):
                    if latest.get(key)!=changed.get(key):conflicts+=1;continue
                    if key in prior:latest[key]=deepcopy(prior[key])
                    else:latest.pop(key,None)
    return result,conflicts
