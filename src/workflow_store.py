"""Local notification inbox and recoverable focus sessions, independent of chat."""
from copy import deepcopy
from pathlib import Path
import json,math,shutil,threading,time,uuid
from sync_bridge import atomic_json


def _number(value,minimum=0,maximum=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return False
    try:return math.isfinite(value) and value>=minimum and (maximum is None or value<=maximum)
    except OverflowError:return False


def _timestamp(value):return _number(value,maximum=253402300799)


def _ident(value):return isinstance(value,str) and bool(value.strip())


def _notice_valid(row):
    return (isinstance(row,dict) and _ident(row.get('id'))
            and isinstance(row.get('text'),str) and isinstance(row.get('source'),str)
            and row.get('role','notice')=='notice' and row.get('kind','notification')=='notification'
            and _timestamp(row.get('created')) and isinstance(row.get('read',False),bool)
            and all(row.get(k) is None or isinstance(row[k],str) for k in ('key','todo_id')))


def _focus_valid(row,finished=False):
    if not isinstance(row,dict) or not _ident(row.get('id')) or row.get('phase') not in ('focus','break'):
        return False
    total=row.get('total');remaining=row.get('remaining');elapsed=row.get('elapsed')
    if (not _number(total,minimum=1,maximum=86400) or not _number(remaining,maximum=total)
            or not _number(elapsed,maximum=total) or elapsed+remaining>total+1e-6
            or not _timestamp(row.get('updated'))):return False
    todo=row.get('todo')
    if todo is not None and (not isinstance(todo,dict) or not _ident(todo.get('id'))
                             or not isinstance(todo.get('text',''),str)):return False
    return not finished or (isinstance(row.get('reason'),str) and _timestamp(row.get('ended')))


def _validated(value):
    if not isinstance(value,dict):raise ValueError('workflow state must be an object')
    data=deepcopy(value);issues=[]
    for name,valid,limit in (('notices',_notice_valid,500),('sessions',lambda r:_focus_valid(r,True),2000)):
        values=value.get(name,[]);rows=[];seen=set()
        if not isinstance(values,list):issues.append(name);values=[]
        for row in values:
            if not valid(row) or row['id'] in seen:
                issues.append(name);continue
            seen.add(row['id']);rows.append(deepcopy(row))
        if len(rows)>limit:issues.append(name)
        data[name]=rows[-limit:]
    focus=value.get('focus')
    if focus is not None and not _focus_valid(focus):issues.append('focus');focus=None
    data['focus']=deepcopy(focus)
    return data,sorted(set(issues))


class WorkflowStore:
    def __init__(self,root):
        self.path=Path(root)/'workflow-state.json';self.lock=threading.RLock()
        self.data={'notices':[],'focus':None,'sessions':[]}
        self.load_error='';self.save_error='';self.recovery_path=None;self._save_allowed=True
        try:
            raw=self.path.read_bytes()
        except FileNotFoundError:return
        except OSError as error:
            self.load_error='read: '+type(error).__name__;self._save_allowed=False
            self._log(self.load_error);return
        try:
            data,issues=_validated(json.loads(raw.decode('utf-8-sig')))
            self.data=data
            if not issues:return
            self.load_error='invalid fields: '+', '.join(issues)
        except (ValueError,TypeError,OverflowError,RecursionError) as error:
            self.load_error='parse: '+type(error).__name__
        # Preserve the exact original before any later operation can overwrite it.
        backup=self.path.with_name(self.path.name+'.bad-'+uuid.uuid4().hex)
        try:
            shutil.copy2(self.path,backup);self.recovery_path=backup
        except OSError as error:
            self._save_allowed=False;self.load_error+='; backup: '+type(error).__name__
        self._log(self.load_error)

    def _log(self,message):
        try:
            with (self.path.parent/'error.log').open('a',encoding='utf-8') as stream:
                stream.write(time.strftime('%Y-%m-%d %H:%M:%S')+' [workflow_state] '+message+'\n')
        except OSError:pass

    def save(self):
        with self.lock:
            if not self._save_allowed:
                self.save_error='original file could not be preserved';return False
            try:
                atomic_json(str(self.path),self.data);self.save_error='';return True
            except (OSError,ValueError,TypeError) as error:
                self.save_error=type(error).__name__;self._log('save: '+self.save_error);return False
    def notice(self,text,source,*,key=None,todo_id=None):
        with self.lock:
            if key and any(r.get('key')==key for r in self.data['notices']):return
            self.data['notices'].append(dict(id='n'+uuid.uuid4().hex,text=text,source=source,created=time.time(),
                role='notice',kind='notification',read=False,key=key,todo_id=todo_id))
            self.data['notices']=self.data['notices'][-500:];self.save()
    def notices(self):
        with self.lock:return deepcopy(self.data['notices'])
    def read(self,ids):
        with self.lock:
            for row in self.data['notices']:
                if row['id'] in ids:row['read']=True
            self.save()
    def begin(self,phase,seconds,todo=None):
        with self.lock:
            self.data['focus']=dict(id=uuid.uuid4().hex,phase=phase,total=seconds,remaining=seconds,
                elapsed=0,updated=time.time(),todo=deepcopy(todo));self.save()
    def checkpoint(self,remaining):
        with self.lock:
            row=self.data.get('focus')
            if not row:return
            remaining=max(0,min(float(row['remaining']),float(remaining)))
            row['elapsed']+=row['remaining']-remaining;row['remaining']=remaining;row['updated']=time.time();self.save()
    def finish(self,reason):
        with self.lock:
            row=self.data.get('focus')
            if not row:return None
            row=deepcopy(row);row.update(reason=reason,ended=time.time())
            if row['phase']=='focus' and not any(r['id']==row['id'] for r in self.data['sessions']):
                self.data['sessions'].append(row);self.data['sessions']=self.data['sessions'][-2000:]
            self.data['focus']=None;self.save();return row
    def total(self,todo_id):
        with self.lock:return sum(r['elapsed'] for r in self.data['sessions'] if (r.get('todo') or {}).get('id')==todo_id)


def chat_channel(row):return 'weixin' if row.get('kind','').startswith('weixin') else 'desktop'


def surrounding(rows,ident,before=6,after=6):
    target=next((r for r in rows if r.get('id')==ident),None)
    if not target:return [],False,False
    values=[r for r in rows if r.get('role') in ('user','assistant') and r.get('kind')!='memory_summary'
            and chat_channel(r)==chat_channel(target)]
    index=next((i for i,r in enumerate(values) if r.get('id')==ident),None)
    if index is None:return [],False,False
    return values[max(0,index-before):index+after+1],index>before,index+after+1<len(values)
