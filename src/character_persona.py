"""Read character-owned dialogue settings without executing anything in a pack."""
import json
from pathlib import Path


def read_card(path):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8-sig')).get('data',{})
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError,AttributeError):
        return {}


def character_name(path,pack):
    value=read_card(path).get('name')
    if isinstance(value,str) and value.strip():return value.strip()
    return pack.manifest.get('display_name',pack.name) if pack else '静香'


def dialogue_option(path,pack,key,_unused=None):
    defaults={
        'chat_style':'\n\n依照当前角色卡，以简体中文自然回应。篇幅服从问题需要，保持事实、判断与推测的区分。',
        'style_reminder':'历史对话仅供参考，保持当前角色身份与关系，不机械重复句式。',
        'dizzy_line':'请慢一些，我有些头晕。',
        'greeting_ideas':['依照当前角色卡自然问候，尊重用户正在忙碌或想安静的状态。'],
    }
    data=read_card(path);extensions=data.get('extensions',{})
    options=extensions.get('deskpet',{}) if isinstance(extensions,dict) else {}
    value=options.get(key) if isinstance(options,dict) else None
    if key=='greeting_ideas':
        if isinstance(value,list) and 1<=len(value)<=20 and all(isinstance(s,str) and 0<len(s)<=2000 for s in value):return value
    elif isinstance(value,str) and 0<len(value)<=12000:return value
    return defaults.get(key,'')


def load_character_persona(path,pack,*_unused):
    data=read_card(path);parts=[]
    keys=('description','personality','scenario','system_prompt')
    for key in keys:
        value=data.get(key)
        if isinstance(value,str) and value.strip():
            parts.append(value.replace('<character>','').replace('</character>','').strip())
    example=data.get('mes_example')
    if isinstance(example,str) and example.strip():
        heading='以下是口吻示例；示例情境不是用户的真实记忆：\n'
        parts.append(heading+example.replace('<START>','').replace('{{char}}',character_name(path,pack)).replace('{{user}}','用户'))
    if parts:
        return '\n\n'.join(parts)
    return f'你是{character_name(path,pack)}。当前角色卡不可用，请说明设定暂时无法读取，不编造身世、关系或用户记忆。'
