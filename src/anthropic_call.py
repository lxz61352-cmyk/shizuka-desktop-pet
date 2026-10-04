"""Anthropic 兼容传输：外形是 chat.completions.create，内部走 /anthropic/v1/messages。

**为什么需要它**：DeepSeek 的联网搜索只在 Anthropic 兼容端点上——
`tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": N}]`。
Responses 和 chat 端点都不支持（chat 会报 `expected function`，Responses 静默忽略）。

实测（2026-10-01~02）：
  · 模型**自己决定要不要搜**、自己写检索词（还会中英各写一个）
  · 每次搜回 10 条结果，`max_uses` 控制次数
  · 拿到互相矛盾的资料时会直说矛盾——这是原生联网才有的综合质量
  · **但来源不筛**：问"GPT 最新模型的价格"会搜到 API 转售商的推广页，
    她会把推广内容当资料转述（2026-10-02 用户实际踩到）
  · 一次搜索约 1.6 万输入 token，**绝不能每轮都开**
  · 首字要等 3~5 秒（搜索在前）

**要处理的三件事**：
  1. `content` 是块列表：`thinking` / `server_tool_use` / `web_search_tool_result` / `text`
     —— **只有 text 是要说的话**，其余的漏出去她会把搜索结果念出来
  2. `system` 是顶层参数，不在 messages 里
  3. 流式事件名和 OpenAI 不一样：只看 `content_block_delta` 里的 `text_delta`

**关于二审**（2026-10-02 加）：`iter_events` 把"搜过没有 / 搜到什么"一并交出来，
让上层能在**发出去之前**判断这条该不该发——见 api_runtime 的 `_AnthropicStream`。
"""
import json
import urllib.error
import urllib.request

WEB_SEARCH_TOOL = {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3}
DEFAULT_VERSION = '2023-06-01'
# 关思考：DeepSeek 的 anthropic 端点默认开着思考。
# 文档说 `thinking` 支持（budget_tokens 被忽略）、`output_config` 仅支持 effort，
# 两个都发让服务端挑它能认的。（实测关掉后 output 里只剩 text 块）
THINKING_OFF = {'thinking': {'type': 'disabled'}, 'output_config': {'effort': 'none'}}

# 联网时追加到 system 后面：压住"我去查一下"这种过场句。
# 它会先流出去，二审撤不回来（见 api_runtime._AnthropicStream）。
SEARCH_PREAMBLE_RULE = (
    '\n\n需要联网查的时候**直接查，查之前不要先说话**——'
    '不要写"我去查一下""让我搜搜看"这类过场句。'
)

# 二审的判据（api_runtime._review_search_reply 用）
REVIEW_INSTRUCTION = (
    '你要发的这条消息是**联网搜来的**。发之前先自己审一遍，只输出 JSON：'
    '{"send": true/false, "text": "要发的内容"}。\n'
    '回 send=false 的情况：搜到的资料主要是**商业推广、转售、比价、导流**页面；'
    '消息实质是在转述广告或推销；消息只是"我去查一下"之类的过场话、没有实际内容；'
    '或者搜到的东西跟用户问的根本不是一回事。\n'
    '回 send=true 时 text 就写你原本要发的那条，不要改写、不要解释。'
)


def _text_blocks(content):
    """只取 text 块。"""
    if isinstance(content, str):
        return content
    return ''.join(block.get('text') or '' for block in (content or [])
                   if isinstance(block, dict) and block.get('type') == 'text')


def _get(obj, name, default=None):
    """dict 和 SDK 对象都能取——应用传进来的 message 不保证是字典。

    2026-10-02：只写 `message.get(...)` 会 AttributeError，
    而且表现为"0.0 秒就失败"，很难往这上面想。
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _image_block(url):
    """图片 → anthropic 的 image 块。data: URL 必须当 base64 传。"""
    if not url:
        return None
    if url.startswith('data:'):
        head, _, payload = url.partition(',')
        media = head[5:].split(';')[0] or 'image/png'
        return {'type': 'image',
                'source': {'type': 'base64', 'media_type': media, 'data': payload}}
    return {'type': 'image', 'source': {'type': 'url', 'url': url}}


def _to_messages(messages):
    """chat 的 messages → (system 文本, anthropic messages)。"""
    system, out = [], []
    for message in messages or []:
        role = _get(message, 'role') or 'user'
        content = _get(message, 'content')
        if role == 'system':
            system.append(content if isinstance(content, str)
                          else json.dumps(content, ensure_ascii=False))
            continue
        blocks = []
        if isinstance(content, str) or content is None:
            if content:
                blocks.append({'type': 'text', 'text': content})
        else:
            for part in content:
                kind = _get(part, 'type')
                if kind in ('text', 'input_text', 'output_text'):
                    blocks.append({'type': 'text', 'text': _get(part, 'text') or ''})
                elif kind == 'image_url':
                    url = _get(part, 'image_url')
                    if not isinstance(url, str):
                        url = _get(url, 'url')
                    block = _image_block(url)
                    if block:
                        blocks.append(block)
        out.append({'role': 'assistant' if role == 'assistant' else 'user',
                    'content': blocks or [{'type': 'text', 'text': ''}]})
    return '\n\n'.join(system), out


def build_body(messages, *, model, max_tokens, temperature=None, thinking_off=True,
               web_search=False, stream=False, max_uses=3):
    """chat 形状的参数 → anthropic 请求体。"""
    system, converted = _to_messages(messages)
    body = {'model': model, 'messages': converted, 'max_tokens': int(max_tokens or 800)}
    if system:
        body['system'] = system
    if temperature is not None:
        body['temperature'] = temperature
    if thinking_off:
        body.update(THINKING_OFF)
    if web_search:
        body['tools'] = [dict(WEB_SEARCH_TOOL, max_uses=max_uses)]
    if stream:
        body['stream'] = True
    return body


def request(base, api_key, body, timeout=180, version=DEFAULT_VERSION):
    url = base.rstrip('/') + '/v1/messages'
    req = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'), method='POST',
        headers={'Content-Type': 'application/json', 'x-api-key': api_key,
                 'Authorization': 'Bearer %s' % api_key,
                 'anthropic-version': version})
    return urllib.request.urlopen(req, timeout=timeout)


def complete(base, api_key, body, timeout=180):
    """非流式：返回 (正文, 原始回包)。"""
    with request(base, api_key, body, timeout=timeout) as response:
        payload = json.loads(response.read().decode('utf-8'))
    return _text_blocks(payload.get('content')), payload


def search_items(payload_or_blocks):
    """取出搜索到的条目（给二审用）。传非流式回包或块列表都行。"""
    blocks = (payload_or_blocks or {}).get('content') \
        if isinstance(payload_or_blocks, dict) else (payload_or_blocks or [])
    found = []
    for block in blocks or []:
        if not isinstance(block, dict) or block.get('type') != 'web_search_tool_result':
            continue
        for item in (block.get('content') or []):
            if isinstance(item, dict):
                found.append(item)
    return found


def iter_events(base, api_key, body, timeout=180):
    """流式：产出 ('text', 增量) / ('search', 检索词) / ('result', [条目…])。

    **thinking_delta 和工具参数一律不产出**——否则她会把思考过程念给用户听。
    `search` / `result` 是给上层做二审判断用的，不是要发出去的内容。
    """
    body = dict(body)
    body['stream'] = True
    with request(base, api_key, body, timeout=timeout) as response:
        for raw in response:
            line = raw.decode('utf-8', 'replace').strip()
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if not data or data == '[DONE]':
                continue
            try:
                event = json.loads(data)
            except ValueError:
                continue
            kind = event.get('type')
            if kind == 'content_block_delta':
                delta = event.get('delta') or {}
                if delta.get('type') == 'text_delta':
                    text = delta.get('text')
                    if text:
                        yield 'text', text
            elif kind == 'content_block_start':
                block = event.get('content_block') or {}
                if block.get('type') == 'server_tool_use':
                    yield 'search', block.get('input') or {}
                elif block.get('type') == 'web_search_tool_result':
                    items = block.get('content') or []
                    if isinstance(items, list):
                        yield 'result', [i for i in items if isinstance(i, dict)]
            elif kind == 'error':
                raise RuntimeError(str(event.get('error'))[:200])


def iter_text(base, api_key, body, timeout=180):
    """只要正文增量（兼容旧调用）。"""
    for kind, payload in iter_events(base, api_key, body, timeout=timeout):
        if kind == 'text':
            yield payload
