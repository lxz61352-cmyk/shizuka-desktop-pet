"""Small versioned UI preferences, separate from model credentials."""
from pathlib import Path
import json
from sync_bridge import atomic_json

DEFAULTS=dict(background_file='',blur=8,darkness=.64,desktop_proactive='偶尔',startup_missed=False)


def load(root):
    value=dict(DEFAULTS);path=Path(root)/'experience-settings.json'
    if path.exists():value.update(json.loads(path.read_text('utf-8-sig')))
    return value


def save(root,value):
    clean={k:value.get(k,v) for k,v in DEFAULTS.items()}
    clean['blur']=max(0,min(20,int(clean['blur'])))
    clean['darkness']=max(.25,min(.85,float(clean['darkness'])))
    atomic_json(str(Path(root)/'experience-settings.json'),clean)
    return clean
