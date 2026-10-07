"""Small versioned UI preferences, separate from model credentials."""
from pathlib import Path
import json
import re
from sync_bridge import atomic_json

DEFAULTS=dict(background_file='',blur=8,darkness=.64,desktop_proactive='偶尔',startup_missed=False,
              desktop_start=0,desktop_end=1440,desktop_after_chat=30,desktop_paused_until=0,
              water_enabled=False,water_times='10:00, 14:00, 16:00',water_sound='')


def blur_from_percent(text):
    """Keep the stored radius compatible with existing 0–20 preferences."""
    value=str(text).strip()
    if not re.fullmatch(r'[0-9]{1,3}',value) or int(value)>100:
        raise ValueError('背景模糊度请输入 0–100 的整数。')
    return int(value)/5


def load(root):
    value=dict(DEFAULTS);path=Path(root)/'experience-settings.json'
    if path.exists():value.update(json.loads(path.read_text('utf-8-sig')))
    return value


def save(root,value):
    clean={k:value.get(k,v) for k,v in DEFAULTS.items()}
    clean['blur']=max(0,min(20,float(clean['blur'])))
    clean['darkness']=max(.25,min(.85,float(clean['darkness'])))
    from habit_reminders import parse_times
    clean['water_times']=parse_times(clean['water_times'])
    clean['water_enabled']=clean['water_enabled'] is True
    for key, maximum in [('desktop_start',1439),('desktop_end',1440),('desktop_after_chat',1440)]:
        clean[key]=int(clean[key])
        if not 0<=clean[key]<=maximum:raise ValueError('主动搭话时间设置无效。')
    if clean['desktop_start']==clean['desktop_end']:raise ValueError('允许时段的开始与结束不能相同。')
    atomic_json(str(Path(root)/'experience-settings.json'),clean)
    return clean
