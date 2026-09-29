"""Versioned local JSON snapshots, explicitly scoped restore, no credentials."""
from pathlib import Path,PurePosixPath
from datetime import datetime
import hashlib,json,zipfile
from sync_bridge import atomic_json


def allowed(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name:return False
    return (name in ('settings.json','experience-settings.json','dialogue-feedback.json','chat-draft.json','workflow-state.json')
            or len(p.parts)>=3 and p.parts[0]=='characters' and p.parts[1]=='shizuka'
            and (name.endswith('/memory.json') or name.endswith('/memory-review.json')
                 or name.endswith('/todos.json') or name.endswith('/todo-details.json')
                 or name.endswith('/对话记录/对话记录.json')))


def category(name):
    if name.endswith(('memory.json','memory-review.json')):return '记忆'
    if name.endswith(('todos.json','todo-details.json')):return '待办'
    if '对话记录/' in name:return '聊天'
    return '设置与反馈'


def create(data_root,reason='manual'):
    root=Path(data_root).resolve();folder=root/'backups';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+reason+'.zip')
    manifest={}
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob('*.json'):
            name=path.relative_to(root).as_posix()
            if not allowed(name):continue
            data=path.read_bytes();parsed=json.loads(data.decode('utf-8-sig'))
            if name=='settings.json':
                # The API key lives elsewhere; exclude any legacy secret-bearing setting too.
                parsed={k:v for k,v in parsed.items() if not any(s in k.lower() for s in ('key','token','password','secret'))}
                data=json.dumps(parsed,ensure_ascii=False,indent=2).encode()
            archive.writestr(name,data);manifest[name]=hashlib.sha256(data).hexdigest()
        archive.writestr('backup-manifest.json',json.dumps({'schema':1,'files':manifest}))
    return target


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        info=archive.infolist()
        if sum(i.file_size for i in info)>100*1024*1024:raise ValueError('备份过大')
        manifest=json.loads(archive.read('backup-manifest.json'))
        if manifest.get('schema')!=1:raise ValueError('不支持的备份格式')
        names=manifest['files']
        if len(names)!=len(set(names)) or len(info)!=len(names)+1:raise ValueError('备份文件列表异常')
        result={}
        for name,expected in names.items():
            if not allowed(name):raise ValueError('备份含未允许路径')
            raw=archive.read(name)
            if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('备份校验失败')
            value=json.loads(raw.decode('utf-8-sig'))
            result[name]=value
        return result


def stage_restore(data_root,path,categories):
    root=Path(data_root).resolve();items=inspect(path)
    selected={name:value for name,value in items.items() if category(name) in categories}
    if not selected:raise ValueError('未选择可恢复的数据')
    before=create(root,'before-restore')
    atomic_json(str(root/'pending-restore.json'),{'items':selected,'backup':str(before)})
    return before


def apply_pending(data_root):
    root=Path(data_root).resolve();pending=root/'pending-restore.json'
    if not pending.exists():return False
    payload=json.loads(pending.read_text('utf-8-sig'))
    for name,value in payload['items'].items():
        if not allowed(name):raise ValueError('恢复路径不合法')
    for name,value in payload['items'].items():
        target=(root/name).resolve()
        if root not in target.parents:raise ValueError('恢复路径越界')
        target.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(str(target),value)
    pending.unlink()
    return True
