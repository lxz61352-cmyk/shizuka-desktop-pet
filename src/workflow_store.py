"""Local notification inbox and recoverable focus sessions, independent of chat."""
from copy import deepcopy
from pathlib import Path
import json,threading,time,uuid
from sync_bridge import atomic_json


class WorkflowStore:
    def __init__(self,root):
        self.path=Path(root)/'workflow-state.json';self.lock=threading.RLock()
        self.data={'notices':[],'focus':None,'sessions':[]}
        if self.path.exists():self.data.update(json.loads(self.path.read_text('utf-8-sig')))
    def save(self):atomic_json(str(self.path),self.data)
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
