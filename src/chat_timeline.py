"""Device-recorded message times for the text chat clients; no inferred event times."""
from datetime import datetime
import json
import re

REVISION = 'conversation-time-v1'
CONTRACT = (
    '【对话时间与承接】\n'
    '时间线由设备记录，索引对应本次请求中的历史消息（从 0 开始）。时间带时区；'
    'user 时间是发送时刻，assistant 时间是开始收到正文的时刻，不是文字所描述的事件发生时间。'
    'null 表示未记录或间隔无法确定，不能补猜；clock_anomaly 表示设备时间有冲突。\n'
    '历史中的活动、情绪和计划是当时的陈述。结合间隔和用户现在的话判断是否延续；'
    '换了话题就接眼前的话，不默认旧事还在进行，也不把新话题解释成逃避旧事。'
    '提过计划不等于委托你持续监督，吃饭、休息、聊天无需向你交代。\n'
    'feedback_user_indices 只标出历史里用户对交流方式的反馈，具体意思看对应原话。'
    '用户明确的纠正和不想被怎样对待，应在后续接话中继续尊重；'
    '若用户后来改变要求，以新的明确表达为准。不要因为换话题或时间过去就重复被指出的问题。'
    '这些元数据用于理解对话，无需在回复里播报。'
)


def local_now():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def valid_timestamp(value):
    # Require an explicit offset, reject free text/naive dates and impossible dates.
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
        return None
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return value


def _seconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if value else None


def build_timeline(history, timestamps, now):
    from interaction_frame import build_interaction_frame
    current = valid_timestamp(now)
    current_seconds = _seconds(current)
    stamps = [valid_timestamp(value) for value in timestamps]
    rows, previous, anomaly, feedback = [], None, False, []
    for index, message in enumerate(history):
        at = stamps[index] if index < len(stamps) else None
        seconds = _seconds(at)
        delta = seconds - previous if seconds is not None and previous is not None else None
        future = seconds is not None and current_seconds is not None and seconds > current_seconds
        anomaly |= future or (delta is not None and delta < 0)
        rows.append({'history_index': index, 'at': at,
                     'gap_seconds': int(delta) if delta is not None and delta >= 0 and not future else None})
        # Unknown times break the chain; never claim a gap across an undated message.
        previous = seconds
        if message['role'] == 'user' and build_interaction_frame(
                message['content'])['current_signal']['kind'] == 'relationship_feedback':
            feedback.append(index)
    gap = current_seconds - previous if current_seconds is not None and previous is not None else None
    return {'schema': REVISION, 'clock_source': 'device', 'current_user_at': current,
            'seconds_since_last_message': int(gap) if gap is not None and gap >= 0 else None,
            'clock_anomaly': bool(anomaly), 'messages': rows, 'feedback_user_indices': feedback}


def render_timeline(history, timestamps, now):
    return CONTRACT + '\n' + json.dumps(build_timeline(history, timestamps, now),
                                       ensure_ascii=False, sort_keys=True, separators=(',', ':'))
