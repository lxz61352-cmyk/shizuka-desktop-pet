"""联网判定：让模型自己决定要不要查，要就给出检索词。

**为什么单独做这一步**（2026-10-02 读官方文档后的结论）：
  · chat 端点和 responses 端点**都只支持 `function` 工具**，内置联网都没有；
  · 所以"让模型自己联网"的可靠路是——应用把 `web_search` 声明成一个 function，
    模型决定调不调，**真正去搜的仍然是应用**（用已有的 web_search.py）；
  · 本地正则（`web_search.needs_search`）实测只有 41% 准（32 条里漏搜 16），
    漏的那些正是「那个游戏什么时候出的」这类——**交给模型判断就补上了**。

**代价**：每轮多一次很便宜的调用（输入只有用户这一句话、max_tokens 200、temperature 0）。
**失败一律当作"不搜"**——判定层出问题绝不能影响正常对话。

**要不要强制搜**：`force=True` 时用 `tool_choice='required'`，
模型必须调用工具（文档：chat 端点在思考模式下不支持 required，会 400——所以这里必须关思考）。
"""
import json

TOOL = {
    'type': 'function',
    'function': {
        'name': 'web_search',
        'description': (
            '联网搜索。当用户问的事**需要实时信息才能答准**时调用：'
            '新闻时事、最新版本或价格、具体数字和日期、某个东西现在还怎么样、'
            '你不确定的事实。'
            '**不要**用于：情绪倾诉、闲聊、让你评价自己或谈角色设定、'
            '写代码/翻译/计算这类本地就能做的事。'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': '检索词。简短，保留关键名词，不要写成一句话，不要带标点。',
                },
            },
            'required': ['query'],
        },
    },
}

SYSTEM = (
    '你是检索判定器。只做一件事：判断用户这句话**要不要联网查**才能答准。\n'
    '要查就调用 web_search，把检索词放在 query 里；不要查就直接回一个空回复，不要调用任何工具。\n'
    '**不要回答用户的问题**，也不要解释你的判断。'
)

MAX_QUERY = 80
# 太短的不用问：「嗯」「哈哈」「好」这类不可能需要联网。
# 实测真实需要查的问句最短是「明天是几号」（5 字），所以 4 字以下直接跳过。
MIN_CHARS = 4


def query_from_reply(reply):
    """从模型的回包里取检索词。取不到返回空串。

    单独拆出来是为了能离线测——不用真的调 API。
    """
    try:
        choices = getattr(reply, 'choices', None) or []
        if not choices:
            return ''
        message = getattr(choices[0], 'message', None)
        calls = getattr(message, 'tool_calls', None) or []
        for call in calls:
            function = getattr(call, 'function', None)
            if function is None:
                continue
            if (getattr(function, 'name', '') or '') != 'web_search':
                continue
            raw = getattr(function, 'arguments', '') or '{}'
            try:
                args = json.loads(raw)
            except Exception:
                continue
            if not isinstance(args, dict):
                continue
            query = str(args.get('query') or '').strip()
            if query:
                return query[:MAX_QUERY]
    except Exception:
        pass
    return ''


def decide_query(text, engine, *, force=False, timeout=12):
    """问模型要不要联网。要就返回检索词，不要或出错返回空串。

    `engine` 是 pet 模块（提供 get_client / _disable_thinking / api_model / has_api_key）。
    """
    stripped = str(text or '').strip()
    if len(stripped) < MIN_CHARS:
        return ''                      # 太短，不值得多跑一次判定
    if not stripped:
        return ''
    try:
        if hasattr(engine, 'has_api_key') and not engine.has_api_key():
            return ''
        client = engine.get_client()
        if hasattr(engine, '_disable_thinking'):
            client = engine._disable_thinking(client)
        if hasattr(client, 'with_options'):
            client = client.with_options(timeout=timeout, max_retries=0)
        reply = client.chat.completions.create(
            model=engine.api_model(),
            messages=[{'role': 'system', 'content': SYSTEM},
                      {'role': 'user', 'content': stripped[:600]}],
            tools=[TOOL],
            tool_choice='required' if force else 'auto',
            temperature=0,
            max_tokens=200,
            # 判定这一步不需要思考；也避开"思考模式不支持 required"那条限制
            extra_body={'thinking': {'type': 'disabled'}},
        )
    except Exception:
        return ''
    return query_from_reply(reply)
