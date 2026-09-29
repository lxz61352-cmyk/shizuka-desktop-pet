"""Local, allowlisted, reviewable JSON exports. Heuristics are not anonymization."""
from datetime import datetime
import ipaddress
import json
from pathlib import Path
import re
from chat_timeline import valid_timestamp

SCHEMA = 'shizuka-chat-feedback-v1'
META_KEYS = ('app_version', 'character_id', 'character_name', 'persona_revision', 'persona_sha256', 'frame_revision', 'timeline_revision',
             'dialogue_mode_revision', 'natural_chat', 'outer_revision', 'outer_variant', 'session_id')
PATTERNS = (
    r'(?i)\b(?:sk|sk-proj)-[a-z0-9_-]{8,}',
    r'(?i)\bBearer\s+[^\s,;，；]+',
    r'(?i)(?:api[_ -]?key|access[_ -]?token|password|密码|密钥|令牌)\s*[=:：]\s*["\x27]?[^\s,;，；"\x27]+',
    r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
    r'(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)',
    r'(?<!\d)\d{17}[\dXx](?!\w)',
    r'(?:微信(?:号)?|QQ(?:号)?|银行卡(?:号)?|学号)\s*[=:：是为]?\s*[A-Za-z0-9_-]{5,}',
    r'https?://[^\s<>，。；）)]+',
    r'[A-Za-z]:[\\/][^\r\n<>"|，。；]+',
    r'\\\\[^\s\\]+\\[^\r\n<>"|，。；]+',
    r'/(?:Users|home)/[^\s，。；]+',
)


def redact(text, private_terms=()):
    text = str(text)
    for term in sorted(set(private_terms), key=len, reverse=True):
        if term and term.strip():
            text = text.replace(term, '[已隐去]')
    for pattern in PATTERNS:
        text = re.sub(pattern, '[已隐去]', text)
    def mask_ip(match):
        try:
            ipaddress.ip_address(match.group())
            return '[已隐去]'
        except ValueError:
            return match.group()
    return re.sub(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', mask_ip, text)


def make_export(snapshot, feedback='', private_terms=(), now=None):
    metadata = {key: snapshot.get('metadata', {}).get(key, '') for key in META_KEYS}
    messages = []
    for index, turn in enumerate(snapshot.get('exchanges', []), 1):
        for role in ('user', 'assistant'):
            text = turn.get(role)
            if isinstance(text, str) and text:
                messages.append({'turn': index, 'role': role, 'content': redact(text, private_terms),
                                 'status': turn.get('status', 'unknown'),
                                 'natural_chat': turn.get('natural_chat') if type(turn.get('natural_chat')) is bool else None,
                                 'persona_revision':turn.get('persona_revision'),
                                 'persona_sha256':turn.get('persona_sha256'),
                                 'outer_revision':turn.get('outer_revision'), 'outer_variant':turn.get('outer_variant'),
                                 'system_sha256':turn.get('system_sha256'),
                                 'recorded_at': valid_timestamp(turn.get(role + '_at')),
                                 'ended_at': valid_timestamp(turn.get('ended_at')) if role == 'assistant' else None,
                                 'model': redact(turn.get('model', ''), private_terms)})
    return {'schema': SCHEMA, 'exported_at': (now or datetime.now().astimezone()).isoformat(),
            'metadata': metadata, 'feedback': redact(feedback, private_terms), 'messages': messages,
            'privacy': {'automatic_redaction': True, 'human_review_required': True,
                        'note': '已过滤常见联系方式、密钥和路径；姓名、学校、地址及语境信息仍需本人检查。'}}


def review_payload(edited_json, original, private_terms=()):
    """Only edited visible messages/feedback survive; metadata is not user input."""
    edited = json.loads(edited_json)
    if not isinstance(edited, dict) or not isinstance(edited.get('messages'), list):
        raise ValueError('请保留 messages 数组；可以删除不愿分享的消息。')
    messages = []
    for item in edited['messages']:
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') \
                or not isinstance(item.get('content'), str):
            raise ValueError('消息只能保留 user/assistant 和文字 content。')
        messages.append({'turn': item.get('turn') if type(item.get('turn')) is int else len(messages) + 1,
                         'role': item['role'], 'content': redact(item['content'], private_terms),
                         'natural_chat': next((row.get('natural_chat') for row in original['messages']
                             if row['turn'] == item.get('turn') and row['role'] == item['role']), None),
                         'persona_revision':next((row.get('persona_revision') for row in original['messages']
                             if row['turn']==item.get('turn') and row['role']==item['role']),None),
                         'persona_sha256':next((row.get('persona_sha256') for row in original['messages']
                             if row['turn']==item.get('turn') and row['role']==item['role']),None),
                         **{key: next((row.get(key) for row in original['messages']
                             if row['turn']==item.get('turn') and row['role']==item['role']), None)
                            for key in ('outer_revision', 'outer_variant', 'system_sha256')},
                         'recorded_at': valid_timestamp(item.get('recorded_at')),
                         'ended_at': valid_timestamp(item.get('ended_at')) if item['role'] == 'assistant' else None,
                         'status': item.get('status') if item.get('status') in
                            ('complete', 'cancelled', 'failed', 'pending') else 'unknown',
                         'model': redact(str(item.get('model', ''))[:160], private_terms)})
    result = dict(original)
    result['messages'] = messages
    result['feedback'] = redact(str(edited.get('feedback', '')), private_terms)
    result['privacy'] = dict(original['privacy'], human_review_confirmed=True)
    return result


def save_export(directory, payload, now=None):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('请选择已有文件夹。')
    moment = now or datetime.now().astimezone()
    stamp = moment.strftime('%Y%m%d_%H%M%S_%f')[:-3]
    payload = dict(payload, exported_at=moment.isoformat())
    for suffix in range(1000):
        character = '心菜' if payload.get('metadata', {}).get('character_id') == 'kokona' else '静香'
        name = character + '聊天_' + stamp + (f'_{suffix:02d}' if suffix else '') + '.json'
        path = directory / name
        try:
            with path.open('x', encoding='utf-8', newline='\n') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            return path
        except FileExistsError:
            continue
    raise ValueError('同一时间已有过多导出文件，请稍后重试。')
