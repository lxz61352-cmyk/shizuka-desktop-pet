"""Local reply diagnostics and explicit feedback, never prompt training data."""
from copy import deepcopy
import hashlib,json,threading,time,uuid
from pathlib import Path
from sync_bridge import atomic_json

TAGS=('太像台词','乱接前文','一直催我','事实不对','这句不错','其他')


def capture(app,channel,messages):
    import pet
    from app_identity import APP_VERSION
    lock=getattr(app,'_chat_lock',None) or threading.RLock()
    with lock:
        if not hasattr(app,'_request_traces'):app._request_traces=threading.local()
    trace_id=uuid.uuid4().hex
    if channel=='desktop':app._last_reply_status='请求已发出，等待回复'
    clean=[]
    for message in messages:
        content=message.get('content','')
        if isinstance(content,list):content=[p if p.get('type')=='text' else {'type':p.get('type'),'omitted':True} for p in content]
        clean.append(dict(role=message['role'],content=content))
    record=dict(id=trace_id,created=time.time(),channel=channel,app_version=APP_VERSION,
                profile=pet.DESKTOP_DIALOGUE_PROFILE,model=pet.api_model(),messages=clean,
                system_sha256=hashlib.sha256(str(clean[0]['content']).encode()).hexdigest())
    folder=Path(pet.DATA_DIR)/'reply-diagnostics';folder.mkdir(parents=True,exist_ok=True)
    atomic_json(str(folder/(trace_id+'.json')),record)
    # A bounded local working set. A marked reply copies its trace into feedback.
    for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime)[:-100]:path.unlink(missing_ok=True)
    setattr(app._request_traces,channel,trace_id)
    return trace_id


def trace_for(app,kind):
    local=getattr(app,'_request_traces',None)
    return getattr(local,'weixin' if kind.startswith('weixin') else 'desktop',None) if local else None


def post_with_trace(app,text,reply,trace):
    if trace and hasattr(app,'_request_traces'):app._request_traces.desktop=trace
    app._post_memory(text,reply)


class FeedbackStore:
    def __init__(self,data_root):
        self.root=Path(data_root);self.path=self.root/'dialogue-feedback.json'
        self.lock=threading.RLock()

    def rows(self):
        if not self.path.exists():return []
        return json.loads(self.path.read_text('utf-8-sig'))['items']

    def mark(self,row,tag,note='',context=()):
        if row.get('role')!='assistant' or tag not in TAGS:raise ValueError('请选择一条角色回复及反馈类型')
        trace=None
        ident=row.get('trace_id','')
        if re_identifier(ident):
            path=self.root/'reply-diagnostics'/(ident+'.json')
            if path.exists():trace=json.loads(path.read_text('utf-8-sig'))
        record=dict(id=uuid.uuid4().hex,created=time.time(),tag=tag,note=note[:1000],
                    reply=deepcopy(row),context=deepcopy(list(context)[-8:]),trace=trace)
        with self.lock:
            rows=self.rows();rows.append(record);atomic_json(str(self.path),{'items':rows})
        return record

    def export(self,ids):
        from chat_test_export import redact
        rows=[r for r in self.rows() if r['id'] in set(ids)]
        # Preview uses exactly this payload; no hidden files or credentials.
        raw=json.dumps({'schema':'shizuka-reply-feedback-v1','items':rows},ensure_ascii=False,indent=2)
        def walk(value):
            if isinstance(value,str):return redact(value)
            if isinstance(value,list):return [walk(x) for x in value]
            if isinstance(value,dict):return {k:walk(v) for k,v in value.items()}
            return value
        return json.dumps(walk(json.loads(raw)),ensure_ascii=False,indent=2)


def re_identifier(value):
    return isinstance(value,str) and len(value)==32 and all(c in '0123456789abcdef' for c in value)
