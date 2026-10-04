"""斜杠指令：桌面和微信共用一份。

**为什么要有这个模块**：指令原本只写在 `weixin_channel.py` 里，
所以**桌面窗口发 `/接口` 会被当成普通聊天**——用户实际遇到的就是这个
（「桌宠问我为什么要发指令」）。

这里放"两边都通用"的几条（看状态、看待办、看心情）；微信特有的
（/图片 /附件 /停止 /电脑 那些依赖微信会话状态的）留在 weixin_channel 里。

**所有指令都不进对话记录**：调用方拿到回复后直接显示、直接返回，
不把它交给模型，所以对她后面说话没有任何影响。
"""
import json
import os
import time

HELP_TEXT = (
    '直接聊天就行；下面是斜杠指令（都不进对话记录，不会影响她后面说话）。\n'
    '\n【看状态】\n'
    '/接口  现在走哪个接口（chat / responses / anthropic），以及最近一次请求\n'
    '/心情（或 /mood、/情绪）  她现在的心情和精力\n'
    '/状态  在线与任务状态\n'
    '/结果  最近一次的结果\n'
    '\n【看东西】\n'
    '/待办  未完成的待办和时间\n'
    '\n微信里还有：/图片（最近图片编号）、/附件（最近文件）、'
    '/电脑 加要求（执行文件任务）、/停止（取消任务）、/主动（主动搭话设置）。'
)

# 中文全角斜杠也认（手机上容易打出来）
SLASHES = ('/', '／')


def looks_like_command(text):
    """是不是一条指令。"""
    stripped = str(text or '').strip()
    return bool(stripped) and stripped.startswith(SLASHES) and len(stripped) <= 40


def _mood_text():
    """心情与精力。读文件和 `/心情` 用的是同一份账本，只读不写。"""
    try:
        import pet as engine
        import pre_reply_affect_runtime as runtime
        import runtime_affect_event_lab as lab
        namespace = getattr(getattr(engine, 'ACTIVE_PACK', None), 'character_id', None) \
            or 'shizuka'
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        path = runtime.state_path(base, namespace)
        if not path.is_file():
            return '还没有心情记录。'
        blob = json.loads(path.read_text('utf-8'))
        state = blob.get('state') if isinstance(blob, dict) else None
        if not isinstance(state, dict):
            return '心情文件格式不认识，先不动它。'
        mood = float(state.get('mood') or 0)
        energy = lab.base.energy(state.get('updated_at'), state.get('wake_hour', 8.0))
        if mood < 30:
            word = '挺低的'
        elif mood < 45:
            word = '偏低'
        elif mood < 60:
            word = '一般'
        elif mood < 75:
            word = '还不错'
        else:
            word = '很好'
        lines = ['心情 %.1f/100（%s）' % (mood, word), '精力 %.1f/100' % energy]
        last = state.get('settlements') or []
        if isinstance(last, list) and last and isinstance(last[-1], dict):
            delta = last[-1].get('delta')
            if delta is not None:
                lines.append('上一次心情变化：%+.1f' % float(delta or 0))
        lines.append('这条指令只看状态，不进对话记录，也不影响她之后说话。')
        return '\n'.join(lines)
    except Exception as exc:
        return '心情读不出来：%s' % type(exc).__name__


def _api_text():
    """当前接口与最近一次请求（真实记录，不是猜的）。"""
    try:
        import api_runtime
        import pet as engine
    except Exception:
        return '暂时读不到接口信息。'
    mode = api_runtime.normalize_mode(engine.api_mode())
    lines = ['接口类型：%s' % api_runtime.mode_label(mode),
             '端点：%s' % api_runtime.endpoint_path(mode),
             '模型：%s' % engine.api_model(),
             '地址：%s' % engine.api_base()]
    last = dict(api_runtime.LAST_REQUEST)
    if last.get('at'):
        lines.append('最近一次：%s，%s，%.1f 秒（%s）' % (
            api_runtime.mode_label(last.get('mode')),
            '成功' if last.get('ok') else '失败',
            last.get('seconds') or 0,
            time.strftime('%H:%M:%S', time.localtime(last['at']))))
        if last.get('error'):
            lines.append('错误：%s' % last['error'])
    else:
        lines.append('最近一次：还没有记录（还没发过请求）')
    if mode == api_runtime.MODE_ANTHROPIC:
        lines.append('（这个接口支持联网搜索，需要时她会自己去查）')
    elif mode == api_runtime.MODE_RESPONSES:
        lines.append('（DeepSeek 的 responses 端点不支持联网搜索，也不会更省）')
    else:
        lines.append('（这个接口不联网；要联网得选 anthropic）')
    return '\n'.join(lines)


def _todo_text():
    """未完成的待办清单。只读。"""
    try:
        import pet as engine
        path = getattr(engine, 'TODO_FILE', '')
    except Exception:
        return '暂时读不到待办。'
    if not path or not os.path.exists(path):
        return '还没有待办。'
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            items = json.load(handle).get('items', [])
    except Exception:
        return '待办文件读不出来，请在电脑端看一下。'
    alive = [it for it in items if not it.get('done')]

    def when(it):
        return str(it.get('due') or it.get('time') or it.get('when') or '').strip()

    if not alive:
        return '没有未完成的待办（共 %d 条，都做完了）。' % len(items)
    alive.sort(key=lambda it: when(it) or '9999')
    lines = ['未完成的待办（%d 条）：' % len(alive)]
    for it in alive[:40]:
        title = str(it.get('title') or it.get('text') or it.get('content') or '').strip()
        moment = when(it)
        lines.append('· %s%s' % (title[:60], ('  —  %s' % moment) if moment else ''))
    if len(alive) > 40:
        lines.append('…还有 %d 条' % (len(alive) - 40))
    return '\n'.join(lines)


def _status_text():
    try:
        import pet as engine
        parts = ['程序在跑。']
        if getattr(engine, 'ENHANCED_MODE', False):
            parts.append('用的是增强对话模式。')
        return ' '.join(parts)
    except Exception:
        return '在跑。'


def run(text):
    """执行一条指令。不是指令 / 不认识的指令返回 None。

    返回文本时，调用方应当**直接显示并返回**，不要交给模型。
    """
    stripped = str(text or '').strip()
    if not looks_like_command(stripped):
        return None
    word = stripped[1:].strip().lower()
    if word in ('帮助', 'help', '?', '？', '指令', 'commands'):
        return HELP_TEXT
    if word in ('接口', 'api', '接口类型'):
        return _api_text()
    if word in ('待办', 'todo', 'todos'):
        return _todo_text()
    if word in ('心情', 'mood', '情绪', '情感'):
        return _mood_text()
    if word in ('状态', 'status'):
        return _status_text()
    return None
