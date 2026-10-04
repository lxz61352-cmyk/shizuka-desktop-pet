"""Bound interactive API waiting, including SSE heartbeats with no visible text."""
import queue
import threading
import traceback
import time
from urllib.parse import urlsplit


DEEPSEEK_MODEL = 'deepseek-flash'   # 官方当前模型名。deepseek-v4-flash-vision-exp 已下线（2026-10-02 查图像理解文档确认），
# 而且 deepseek-flash 本身就支持图片，不需要为了视觉留在旧名上。
DEEPSEEK_LEGACY_MODELS = ('deepseek-chat', 'deepseek-v4-flash',
                          'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp')

# 接口类型：chat = /v1/chat/completions（默认，兼容性最好）；responses = /v1/responses
# anthropic = /anthropic/v1/messages —— **只有它支持联网搜索**
# （`tools=[{"type":"web_search_20250305"}]`；chat 会报 expected function，
#   responses 静默忽略。见 src/anthropic_call.py 的实测记录。）
MODE_CHAT = 'chat'
MODE_RESPONSES = 'responses'
MODE_ANTHROPIC = 'anthropic'
API_MODES = (MODE_CHAT, MODE_RESPONSES, MODE_ANTHROPIC)
MODE_LABELS = {MODE_CHAT: 'chat', MODE_RESPONSES: 'response', MODE_ANTHROPIC: 'anthropic'}


def normalize_mode(value):
    """把设置里的接口类型收敛成 chat / responses / anthropic。"""
    text = str(value or '').strip().lower()
    if text in ('responses', 'response', 'resp'):
        return MODE_RESPONSES
    if text in ('anthropic', 'claude', 'messages'):
        return MODE_ANTHROPIC
    return MODE_CHAT


def mode_label(mode):
    """给用户看的叫法（说话时用这个）。"""
    return MODE_LABELS.get(normalize_mode(mode), 'chat')


def endpoint_path(mode):
    mode = normalize_mode(mode)
    if mode == MODE_RESPONSES:
        return '/v1/responses'
    if mode == MODE_ANTHROPIC:
        return '/anthropic/v1/messages'
    return '/v1/chat/completions'


# 最近一次真实请求走的哪条路：用户问「现在用的 chat 还是 response」时拿这个当证据（不是靠猜）
LAST_REQUEST = {'mode': '', 'path': '', 'model': '', 'ok': None, 'seconds': None, 'at': None, 'error': ''}
_LAST_LOCK = threading.Lock()


def _mode_log(line):
    """把"这次走了哪个接口"落盘——内存字典事后查不到。

    2026-10-02 加：用户问"现在什么接口"她答不知道，因为 LAST_REQUEST
    从来没接进对话；排查时也完全没有依据。所以直接写文件。
    """
    try:
        import datetime
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parent.parent / 'data' / 'api-mode.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%m-%d %H:%M:%S')
        with path.open('a', encoding='utf-8') as handle:
            handle.write('%s %s\n' % (stamp, line))
    except Exception:
        pass


def record_request(mode, model, ok, seconds, error=''):
    with _LAST_LOCK:
        LAST_REQUEST.update(mode=normalize_mode(mode), path=endpoint_path(mode), model=model or '',
                            ok=ok, seconds=round(seconds, 2) if seconds is not None else None,
                            at=time.time(), error=str(error or '')[:160])
    _mode_log('mode=%-9s ok=%-5s %5.1fs %s%s' % (
        normalize_mode(mode), ok, seconds or 0, model or '',
        ('  ERROR=' + str(error)[:80]) if error else ''))


def last_request():
    with _LAST_LOCK:
        return dict(LAST_REQUEST)


def current_model(base, model):
    if urlsplit(base).hostname == 'api.deepseek.com' and model in DEEPSEEK_LEGACY_MODELS:
        return DEEPSEEK_MODEL
    return model


def model_from_settings(settings):
    base=settings.get('api_base') or 'https://api.deepseek.com'
    model=settings.get('api_model') or DEEPSEEK_MODEL
    return current_model(base,model)


class ResponseDeadline(TimeoutError):
    pass


def probe_generation(key,base,model,seconds=12,mode=MODE_CHAT):
    """Test visible output from the selected model, not merely authentication."""
    import openai
    mode=normalize_mode(mode)
    started=time.monotonic();stream=None
    result={'ok':False,'model':model,'kind':'empty','mode':mode}
    try:
        with openai.OpenAI(api_key=key,base_url=base,timeout=min(seconds,10),max_retries=0) as raw:
            client=configure_client(raw,base,mode)
            with client.chat.completions.create(model=model,messages=[{'role':'user','content':'只回复ok'}],
                    max_tokens=32,stream=True,wait_seconds=seconds) as stream:
                for chunk in stream:
                    if any(getattr(c.delta,'content',None) for c in chunk.choices):
                        result.update(ok=True,kind='ready');break
    except Exception as exc:
        result['kind']='timeout' if isinstance(exc,(TimeoutError,openai.APITimeoutError)) else 'connection'
        status=getattr(exc,'status_code',None)
        if status is not None:result.update(kind='http',status=status)
        result['error']=_error_text(exc)
    result['seconds']=round(time.monotonic()-started,2)
    return result


def _error_text(exc):
    """把异常压成一句短话，用来告诉用户为什么没连上。"""
    message=' '.join(str(exc or '').split())
    if not message:return type(exc).__name__
    return message[:160]


def probe_reason(result):
    """连接失败的原因（说人话，短）。"""
    model=result.get('model')
    if result.get('kind')=='timeout':return f'{model} 生成超时，没在时限内返回正文。'
    if result.get('kind')=='empty':return f'{model} 没返回正文。'
    code=result.get('status')
    detail={400:'接口不接受模型名或参数',401:'密钥没通过验证',402:'接口额度不足',403:'接口拒绝访问',
            404:'接口地址不对（服务商可能不支持这种接口）',405:'服务商不允许这种调用方式',
            429:'接口繁忙，稍后再试'}.get(code)
    if detail:return f'{detail}。'
    if result.get('kind')=='connection':
        text=result.get('error') or ''
        return f'连接不上（{text}）。' if text else '连接不上，检查地址和网络。'
    return '连接失败。'


def probe_line(result):
    """连完接口之后对用户说的一句话：用了哪个模型、哪种接口，成没成。"""
    from urllib.parse import urlsplit
    model=result.get('model') or '未知'
    label=mode_label(result.get('mode'))
    if result.get('ok'):
        return f"现在使用的是 {model} 模型，{label} api 哦，连接成功啦！"
    return f"现在使用的是 {model} 模型，{label} api 哦，连接失败……{probe_reason(result)}"


def probe_status(result):
    model=result['model']
    if result['ok']:return f"可正常回复：{model} · 首字 {result['seconds']:.1f} 秒"
    return probe_reason(result)


def bounded_call(call, seconds):
    result = queue.Queue(maxsize=1)
    def work():
        try: result.put((True, call()))
        except Exception as exc: result.put((False, exc))
    threading.Thread(target=work, name='shizuka-api-request', daemon=True).start()
    try: ok, value = result.get(timeout=seconds)
    except queue.Empty: raise ResponseDeadline('接口未在时限内返回') from None
    if not ok: raise value
    return value


class BoundedStream:
    """Only content advances the response deadline; role/reasoning/heartbeat do not."""
    def __init__(self, create, first_seconds=25, idle_seconds=25, total_seconds=240):
        self.create = create
        self.first_seconds, self.idle_seconds, self.total_seconds = first_seconds, idle_seconds, total_seconds
        self.queue = queue.Queue(maxsize=128)
        self.stop = threading.Event()
        self.response = None

    def __enter__(self):
        self.started = time.monotonic()
        self.deadline = self.started + self.first_seconds
        threading.Thread(target=self._read, name='shizuka-api-stream', daemon=True).start()
        return self

    def _put(self, value):
        while not self.stop.is_set():
            try: self.queue.put(value, timeout=.1); return
            except queue.Full: pass

    def _read(self):
        try:
            with self.create() as response:
                self.response = response
                for chunk in response:
                    if self.stop.is_set(): break
                    self._put(('chunk', chunk))
                self._put(('done', None))
        except Exception as exc:
            self._put(('error', exc))

    def __iter__(self):
        while not self.stop.is_set():
            remaining = min(self.deadline, self.started + self.total_seconds) - time.monotonic()
            if remaining <= 0: raise ResponseDeadline('接口长时间没有返回正文')
            try: kind, value = self.queue.get(timeout=min(remaining, .2))
            except queue.Empty: continue
            if kind == 'done': return
            if kind == 'error':
                record = getattr(self, '_shizuka_record', None)
                if record is not None:
                    record(False, time.monotonic() - self.started, type(value).__name__)
                raise value
            if any(getattr(choice.delta, 'content', None) for choice in value.choices):
                self.deadline = time.monotonic() + self.idle_seconds
                record = getattr(self, '_shizuka_record', None)
                if record is not None:
                    record(True, time.monotonic() - self.started)
                    self._shizuka_record = None      # 只记第一次
            yield value

    def close(self):
        self.stop.set()
        response = self.response
        if response is not None:
            # Closing a blocked transport must not hold the UI or caller thread.
            def close_response():
                try: response.close()
                except Exception: pass
            threading.Thread(target=close_response, daemon=True).start()

    def __exit__(self, *args):
        self.close()


# 各模型对参数的兼容情况（按「接口地址+模型名」记）：{"max_key": ..., "temp": bool}
# 第一次踩坑后自动修正并记住，之后直接用对的参数，不再每次失败重试。
_MODEL_CAPS = {}
_MODEL_CAPS_LOCK = threading.Lock()
_MODEL_CAPS_MAX = 64      # 只是参数兼容性备忘，不落盘；超出上限就丢最早的，避免长期运行无界增长


def _model_caps(base, model, mode=MODE_CHAT):
    """按「接口地址 + 模型名 + 接口类型」记参数兼容情况。responses 的默认参数名不一样。"""
    key = (base, model or '', normalize_mode(mode))
    default = ({'max_key': 'max_output_tokens', 'temp': True, 'thinking': True, 'text_format': True}
               if key[2] == MODE_RESPONSES
               else {'max_key': 'max_tokens', 'temp': True, 'thinking': True})
    with _MODEL_CAPS_LOCK:
        cached = _MODEL_CAPS.get(key)
        if cached is not None:
            return cached
        if len(_MODEL_CAPS) >= _MODEL_CAPS_MAX:
            for stale in list(_MODEL_CAPS)[:max(1, _MODEL_CAPS_MAX // 4)]:
                _MODEL_CAPS.pop(stale, None)
        return _MODEL_CAPS.setdefault(key, dict(default))


def _build_kwargs(kwargs, caps, mode=MODE_CHAT):
    k = dict(kwargs)
    if normalize_mode(mode) == MODE_RESPONSES:
        return _responses_kwargs(k, caps)
    if 'max_tokens' in k:
        k[caps['max_key']] = k.pop('max_tokens')
    if not caps.get('temp', True):
        k.pop('temperature', None)
    if not caps.get('reasoning', True):
        k.pop('reasoning', None)
    if not caps.get('thinking', True) and isinstance(k.get('extra_body'), dict):
        extra = {name: value for name, value in k['extra_body'].items() if name != 'thinking'}
        if extra:
            k['extra_body'] = extra
        else:
            k.pop('extra_body', None)
    return k


# ---------------- Responses 接口：把 chat 的调用形状翻译过去，回包再翻译回来 ----------------
# 好处是全部调用点（29 处）都写的是 chat.completions.create，不用动一行就能切接口。

def _attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _to_responses_input(messages):
    """chat 的 messages → responses 的 input 列表（带图也一样转）。"""
    items = []
    for message in messages or []:
        if not isinstance(message, dict):
            items.append(message)
            continue
        role = message.get('role') or 'user'
        content = message.get('content')
        text_type = 'output_text' if role == 'assistant' else 'input_text'
        if isinstance(content, str) or content is None:
            items.append({'role': role, 'content': [{'type': text_type, 'text': content or ''}]})
            continue
        parts = []
        for part in content:
            if not isinstance(part, dict):
                parts.append(part)
                continue
            kind = part.get('type')
            if kind in ('text', 'input_text', 'output_text'):
                parts.append({'type': text_type, 'text': part.get('text') or ''})
            elif kind == 'image_url':
                url = part.get('image_url')
                if isinstance(url, dict):
                    url = url.get('url')
                parts.append({'type': 'input_image', 'image_url': url})
            else:
                parts.append(part)
        items.append({'role': role, 'content': parts})
    return items


def _responses_kwargs(kwargs, caps):
    """chat 形状的参数 → responses 形状的参数。"""
    k = dict(kwargs)
    if 'max_tokens' in k:
        k[caps.get('max_key') or 'max_output_tokens'] = k.pop('max_tokens')
    messages = k.pop('messages', None)
    if messages is not None:
        k['input'] = messages if isinstance(messages, str) else _to_responses_input(messages)
    fmt = k.pop('response_format', None)
    if fmt:
        if caps.get('text_format', True):
            k['text'] = {'format': fmt}
    if not caps.get('temp', True):
        k.pop('temperature', None)
    if not caps.get('reasoning', True):
        k.pop('reasoning', None)
    if not caps.get('thinking', True) and isinstance(k.get('extra_body'), dict):
        extra = {name: value for name, value in k['extra_body'].items() if name != 'thinking'}
        if extra:
            k['extra_body'] = extra
        else:
            k.pop('extra_body', None)
    return k


def _response_text(response):
    """从 responses 的回包里取正文。"""
    text = _attr(response, 'output_text')
    if isinstance(text, str) and text.strip():
        return text
    chunks = []
    for item in _attr(response, 'output') or []:
        if _attr(item, 'type') == 'reasoning':
            continue
        for part in _attr(item, 'content') or []:
            piece = _attr(part, 'text')
            if isinstance(piece, str):
                chunks.append(piece)
    return ''.join(chunks)


def _event_text(event):
    """responses 的流式事件里取增量文本。

    只认正文事件：`response.reasoning_text.delta`（思考过程）也算 text.delta，
    照收的话桌宠会把自己的推理念出来——实测 DeepSeek 的 responses 就会这样。
    """
    kind = str(_attr(event, 'type') or '')
    if 'reasoning' in kind or 'refusal' in kind:
        return ''
    if kind.endswith('output_text.delta') or kind == 'response.text.delta':
        delta = _attr(event, 'delta')
        return delta if isinstance(delta, str) else ''
    return ''


class _Delta:
    __slots__ = ('content',)

    def __init__(self, content=None):
        self.content = content


class _Choice:
    __slots__ = ('delta', 'message', 'finish_reason', 'index')

    def __init__(self, content=None, finish_reason=None, message=None):
        self.delta = _Delta(content)
        self.message = message
        self.finish_reason = finish_reason
        self.index = 0


class _Chunk:
    """伪装成 chat 的流式块：调用点只读 chunk.choices[0].delta.content。"""
    def __init__(self, content=None, finish_reason=None):
        self.choices = [_Choice(content=content, finish_reason=finish_reason)]
        self.id = 'responses'
        self.object = 'chat.completion.chunk'


class _ChatShapedResponse:
    """伪装成 chat 的非流式回包：调用点只读 .choices[0].message.content。"""
    def __init__(self, content):
        self.choices = [_Choice(message=_Message(content))]
        self.id = 'responses'


class _Message:
    __slots__ = ('content', 'role')

    def __init__(self, content):
        self.content = content
        self.role = 'assistant'


class _ResponsesStream:
    """responses 的流 → chat 形状；服务商不支持流式时退化成一次性返回。

    流是在 __iter__ 里才开的：这样「不支持流式」的报错能落到回退分支里，
    而不是从 __enter__ 抛出去让整轮对话失败。
    """

    def __init__(self, create_stream, create_plain, allow_fallback=True):
        self._create_stream = create_stream
        self._create_plain = create_plain
        self._allow_fallback = allow_fallback
        self._stream = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def __iter__(self):
        got = False
        try:
            self._stream = self._create_stream()
            enter = getattr(self._stream, '__enter__', None)
            if enter is not None:
                enter()
            for event in self._stream:
                text = _event_text(event)
                if text:
                    got = True
                    yield _Chunk(text)
            if got:
                return
        except Exception:
            if got or not self._allow_fallback:
                raise
        self.close()
        if not self._allow_fallback:
            return
        # 一条文本都没拿到（有的服务商不支持流式事件）→ 退回一次性请求，别让用户干等
        text = _response_text(self._create_plain())
        if text:
            yield _Chunk(text)


def _responses_call(client, base, allow_fallback=True):
    """返回一个「chat.completions.create 形状」的函数，内部走 responses.create。"""
    def call(*args, **kwargs):
        forwarded = dict(kwargs)
        stream = bool(forwarded.get('stream'))
        forwarded.pop('stream', None)
        if args:
            # 位置参数只可能是 model
            forwarded['model'] = args[0]
        if stream:
            def create_stream():
                return client.responses.create(stream=True, **forwarded)
            def create_plain():
                return client.responses.create(**forwarded)
            return _ResponsesStream(create_stream, create_plain, allow_fallback=allow_fallback)
        return _ChatShapedResponse(_response_text(client.responses.create(**forwarded)))
    return call


class _AnthropicChunk:
    """聊天形状的一个增量。"""

    def __init__(self, text):
        delta = type('Delta', (), {'content': text, 'reasoning_content': None})()
        self.choices = [type('Choice', (), {'delta': delta, 'message': None})()]


class _AnthropicStream:
    """anthropic 的流 → chat 形状。

    只在拿到第一个 text_delta 时才真正建立连接之外的东西；text_delta 之外的事件
    （thinking / server_tool_use / web_search_tool_result）一律不产出——
    漏出去她会把思考过程和搜索结果念给用户听。
    """

    def __init__(self, base, api_key, body, timeout=180):
        self._args = (base, api_key, body, timeout)
        self._inner = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        inner = self._inner
        self._inner = None
        if inner is not None:
            try:
                inner.close()
            except Exception:
                pass

    def __iter__(self):
        import anthropic_call
        base, api_key, body, timeout = self._args
        self._inner = anthropic_call.iter_events(base, api_key, body, timeout=timeout)
        buffered, searched, items = [], False, []
        for kind, payload in self._inner:
            if kind == 'search':
                if not searched:
                    _mode_log('  └─ 联网搜索 检索词=%s'
                              % str((payload or {}).get('query') or '')[:60])
                searched = True                     # 从这一刻起，内容先攒着不发
            elif kind == 'result':
                items.extend(payload)
            elif kind == 'text':
                if searched:
                    buffered.append(payload)
                else:
                    yield _AnthropicChunk(payload)  # 没搜过：照常流式，零开销
        if not searched:
            return
        # 搜过了：交给模型二审，判断这条该不该发
        draft = ''.join(buffered)
        final = _review_search_reply(base, api_key, body, draft, items, timeout)
        if final:
            yield _AnthropicChunk(final)


REVIEW_INSTRUCTION = (
    '你要发的这条消息是**联网搜来的**。发之前先自己审一遍，只输出 JSON：'
    '{"send": true/false, "text": "要发的内容"}。\n'
    '回 send=false 的情况：搜到的资料主要是**商业推广、转售、比价、导流**页面；'
    '消息实质是在转述广告或推销；消息只是"我去查一下"之类的过场话、没有实际内容；'
    '或者搜到的东西跟用户问的根本不是一回事。\n'
    '回 send=true 时 text 就写你原本要发的那条，不要改写、不要解释。'
)

SEARCH_PREAMBLE_RULE = (
    '\n\n需要联网查的时候**直接查，查之前不要先说话**——'
    '不要写"我去查一下""让我搜搜看"这类过场句。'
)


def _review_search_reply(base, api_key, body, draft, items, timeout=180):
    """搜过的回合，让模型自己判断该不该发。返回要发的文本；不该发就返回空串。

    **这一轮不挂 web_search**——否则它可能又去搜一次。
    """
    import anthropic_call

    if not draft.strip():
        return ''                                   # 一个字都没有，没什么可发的
    materials = []
    for item in (items or [])[:12]:
        title = (item.get('title') or '').strip()
        url = (item.get('url') or '').strip()
        if title or url:
            materials.append('- %s  %s' % (title[:80], url[:120]))
    user_text = ''
    for message in reversed(body.get('messages') or []):
        if message.get('role') == 'user':
            for block in (message.get('content') or []):
                if isinstance(block, dict) and block.get('type') == 'text':
                    user_text = block.get('text') or ''
                    break
            break
    payload = ('用户问的是：%s\n\n搜索资料的来源：\n%s\n\n你要发的消息：\n%s'
               % (user_text[:400], '\n'.join(materials) or '（没拿到来源清单）', draft[:1500]))
    try:
        check = dict(body)
        check.pop('tools', None)                    # 二审不许再搜
        check.pop('stream', None)
        check['messages'] = [{'role': 'user', 'content': [{'type': 'text', 'text': payload}]}]
        check['system'] = REVIEW_INSTRUCTION
        check['max_tokens'] = 900
        check['temperature'] = 0
        text, _raw = anthropic_call.complete(base, api_key, check, timeout=timeout)
    except Exception:
        return draft                                # 二审失败就按原样发，别把话吞了
    import json as _json
    import re as _re
    match = _re.search(r'\{.*\}', text or '', _re.S)
    if not match:
        return draft
    try:
        verdict = _json.loads(match.group(0))
    except Exception:
        return draft
    if verdict.get('send') is False:
        return ''
    return str(verdict.get('text') or draft)


def anthropic_call_shaped(client, base, fallback=None):
    """返回一个「chat.completions.create 形状」的函数，内部走 anthropic 端点。

    **注意端点前缀**：设置里的 api_base 是 https://api.deepseek.com，
    而 Anthropic 格式在它下面的 /anthropic——不补上会 404（实测踩过）。

    **`fallback`**：要 JSON 输出的调用（`response_format`）交回给 chat 端点——
    Anthropic 格式没有这个参数，硬走会拿不到合法 JSON，
    待办整理、文献评论这些功能会解析失败。
    """
    import anthropic_call

    anthropic_base = base.rstrip('/')
    if not anthropic_base.endswith('/anthropic'):
        anthropic_base += '/anthropic'

    def call(*args, **kwargs):
        if fallback is not None and kwargs.get('response_format'):
            return fallback(*args, **kwargs)
        forwarded = dict(kwargs)
        stream = bool(forwarded.pop('stream', None))
        if args:
            forwarded['model'] = args[0]
        forwarded.pop('timeout', None)
        forwarded.pop('extra_body', None)
        forwarded.pop('reasoning', None)
        forwarded.pop('wait_seconds', None)
        forwarded.pop('response_format', None)
        api_key = getattr(client, 'api_key', '') or ''
        web = getattr(anthropic_call, 'WEB_SEARCH_ENABLED', True)
        if web:
            # 压住"我去查一下"这种过场句——它会先流出去，二审撤不回来
            forwarded = dict(forwarded)
            msgs = list(forwarded.get('messages') or [])
            for index, message in enumerate(msgs):
                if message.get('role') == 'system' and isinstance(message.get('content'), str):
                    patched = dict(message)
                    patched['content'] = message['content'] + anthropic_call.SEARCH_PREAMBLE_RULE
                    msgs[index] = patched
                    break
            forwarded['messages'] = msgs
        body = anthropic_call.build_body(
            forwarded.pop('messages', []) or [],
            model=forwarded.pop('model', ''),
            max_tokens=forwarded.pop('max_tokens', None)
            or forwarded.pop('max_output_tokens', None) or 800,
            temperature=forwarded.pop('temperature', None),
            web_search=getattr(anthropic_call, 'WEB_SEARCH_ENABLED', True),
        )
        if stream:
            return _AnthropicStream(anthropic_base, api_key, body)
        text, _payload = anthropic_call.complete(anthropic_base, api_key, body)
        return _ChatShapedResponse(text)

    return call


def _adaptive_call(original, base, args, kwargs, mode=MODE_CHAT):
    """按模型能力自动修正参数：不接受 temperature 就去掉；不支持 max_tokens 就换
    max_completion_tokens（o 系 / gpt-5 等）；responses 里换 max_output_tokens；
    text.format 不被接受就去掉；不接受 thinking 就去掉。首次自动探测并记住。"""
    mode = normalize_mode(mode)
    caps = _model_caps(base, kwargs.get('model'), mode)
    for _ in range(5):   # 最多修正四次
        try:
            return original(*args, **_build_kwargs(kwargs, caps, mode))
        except Exception as exc:
            msg = str(exc).lower()
            changed = False
            if 'temperature' in msg and caps['temp']:
                caps['temp'] = False
                changed = True
            # 「max_tokens is too large」这类报错不是「不支持该参数」，别误切参数名
            unsupported = ('not support', 'unsupported', 'unknown', 'unexpect', 'unrecogniz',
                           'not allowed', 'does not support', 'requires')
            if mode == MODE_RESPONSES and caps.get('text_format', True) and 'text' in msg and (
                    'format' in msg or 'not support' in msg or 'unsupported' in msg):
                caps['text_format'] = False
                changed = True
            if (('max_tokens' in msg or 'max_completion_tokens' in msg or 'max_output_tokens' in msg)
                    and caps['max_key'] != 'max_completion_tokens'
                    and any(word in msg for word in unsupported)):
                caps['max_key'] = ('max_tokens' if mode == MODE_RESPONSES and caps['max_key'] == 'max_output_tokens'
                                   else 'max_completion_tokens')
                changed = True
            if 'thinking' in msg and caps.get('thinking', True):
                caps['thinking'] = False
                changed = True
            if 'reasoning' in msg and caps.get('reasoning', True):
                caps['reasoning'] = False
                changed = True
            if not changed:
                raise
    return original(*args, **_build_kwargs(kwargs, caps, mode))


def configure_client(client, base, mode=MODE_CHAT, *, allow_retries=True):
    """包一层超时/参数自适应；mode=responses 时把 chat 形状的调用转成 responses。"""
    mode = normalize_mode(mode)
    completions = client.chat.completions
    if getattr(completions, '_shizuka_bounded', False): return client
    if mode == MODE_RESPONSES:
        original = _responses_call(client, base, allow_fallback=allow_retries)
    elif mode == MODE_ANTHROPIC:
        original = anthropic_call_shaped(client, base, fallback=completions.create)
    else:
        original = completions.create
    def create(*args, **kwargs):
        profile = kwargs.pop('_shizuka_profile', None)
        if profile:
            from provider_profile import apply_overrides, log_request
            kwargs = apply_overrides(kwargs, profile)
            log_request(profile, kwargs)
        budget = kwargs.pop('wait_seconds', 25)
        kwargs.setdefault('timeout', min(budget, 20))
        if urlsplit(base).hostname == 'api.deepseek.com' and mode == MODE_ANTHROPIC:
            # anthropic 的关思考参数名不同（thinking + output_config），
            # 由 anthropic_call.build_body 负责，这里什么都不加。
            pass
        elif urlsplit(base).hostname == 'api.deepseek.com':
            if mode == MODE_RESPONSES:
                # responses 那边 extra_body 的 thinking 不生效，要关思考得用 reasoning.effort=none
                # （实测：thinking=disabled 仍有 23 个思考事件，effort=none 是 0 个）
                kwargs.setdefault('reasoning', {'effort': 'none'})
            else:
                # chat 这边关思考是 deepseek 自家的 thinking 字段
                extra = dict(kwargs.get('extra_body') or {})
                extra.setdefault('thinking', {'type': 'disabled'})
                kwargs['extra_body'] = extra
        model = kwargs.get('model')
        started = time.monotonic()

        def call():
            try:
                if allow_retries:
                    out = _adaptive_call(original, base, args, kwargs, mode)
                else:
                    out = original(*args, **_build_kwargs(kwargs, _model_caps(base, model, mode), mode))
            except Exception as exc:
                record_request(mode, model, False, time.monotonic() - started,
                               '%s %s' % (type(exc).__name__, str(exc)[:60]))
                # 光记类型名不够——上一轮就是靠"0.0 秒"才推出错在本地，
                # 堆栈能省掉那一轮推理。只记最后三帧。
                try:
                    _mode_log('  └─ ' + ' | '.join(
                        line.strip() for line in traceback.format_exc().strip().splitlines()[-3:]))
                except Exception:
                    pass
                raise
            if not kwargs.get('stream'):
                record_request(mode, model, True, time.monotonic() - started)
            return out

        if kwargs.get('stream'):
            stream = BoundedStream(call, first_seconds=budget)
            stream._shizuka_record = lambda ok, seconds, error='': record_request(mode, model, ok, seconds, error)
            if profile and profile.get("reasoning_isolation"):
                from provider_profile import wrap_reasoning
                stream = wrap_reasoning(stream)
            return stream
        return bounded_call(call, budget)
    completions.create = create
    completions._shizuka_bounded = True
    completions._shizuka_mode = mode

    # `with_options()` 返回的是**客户端副本**，副本里没有上面这个补丁——
    # 项目里十几处（weixin_ui / dialogue_features / todo_* / pet 的若干功能）
    # 都是 `get_client().with_options(...)` 拿客户端，不修的话它们会绕过模式，
    # 仍然走 chat 端点（实测：切了 anthropic 微信还是搜不了）。
    if not getattr(client, '_shizuka_with_options', False):
        # 用 getattr 拿：没有 with_options 的对象（测试替身、极简客户端）
        # 以前直接取属性，一缺就抛 AttributeError——而它会从 configure_client
        # 整个抛出去，**所有** get_client() 的调用都会挂（2026-10-03 修）。
        original_with_options = getattr(client, "with_options", None)

        if original_with_options is not None:
            def with_options(*args, **kwargs):
                copy = original_with_options(*args, **kwargs)
                return configure_client(copy, base, mode, allow_retries=allow_retries)

            try:
                client.with_options = with_options
                client._shizuka_with_options = True
            except Exception:
                pass
    return client
