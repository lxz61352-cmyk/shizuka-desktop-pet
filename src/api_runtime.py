"""Bound interactive API waiting, including SSE heartbeats with no visible text."""
import queue
import threading
import time
from urllib.parse import urlsplit


DEEPSEEK_MODEL = 'deepseek-v4-flash-vision-exp'   # DeepSeek 官方接口统一用它（唯一带视觉的 flash 实验版）
DEEPSEEK_LEGACY_MODELS = ('deepseek-chat', 'deepseek-v4-flash', 'deepseek-flash',
                          'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp')

# 接口类型：chat = /v1/chat/completions（默认，兼容性最好）；responses = /v1/responses
MODE_CHAT = 'chat'
MODE_RESPONSES = 'responses'
API_MODES = (MODE_CHAT, MODE_RESPONSES)
MODE_LABELS = {MODE_CHAT: 'chat', MODE_RESPONSES: 'response'}


def normalize_mode(value):
    """把设置里的接口类型收敛成 chat / responses。"""
    text = str(value or '').strip().lower()
    if text in ('responses', 'response', 'resp'):
        return MODE_RESPONSES
    return MODE_CHAT


def mode_label(mode):
    """给用户看的叫法（说话时用这个）。"""
    return MODE_LABELS.get(normalize_mode(mode), 'chat')


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
            if kind == 'error': raise value
            if any(getattr(choice.delta, 'content', None) for choice in value.choices):
                self.deadline = time.monotonic() + self.idle_seconds
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

    def __init__(self, create_stream, create_plain):
        self._create_stream = create_stream
        self._create_plain = create_plain
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
            if got:
                raise
        self.close()
        # 一条文本都没拿到（有的服务商不支持流式事件）→ 退回一次性请求，别让用户干等
        text = _response_text(self._create_plain())
        if text:
            yield _Chunk(text)


def _responses_call(client, base):
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
            return _ResponsesStream(create_stream, create_plain)
        return _ChatShapedResponse(_response_text(client.responses.create(**forwarded)))
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


def configure_client(client, base, mode=MODE_CHAT):
    """包一层超时/参数自适应；mode=responses 时把 chat 形状的调用转成 responses。"""
    mode = normalize_mode(mode)
    completions = client.chat.completions
    if getattr(completions, '_shizuka_bounded', False): return client
    original = _responses_call(client, base) if mode == MODE_RESPONSES else completions.create
    def create(*args, **kwargs):
        budget = kwargs.pop('wait_seconds', 25)
        kwargs.setdefault('timeout', min(budget, 20))
        if urlsplit(base).hostname == 'api.deepseek.com':
            if mode == MODE_RESPONSES:
                # responses 那边 extra_body 的 thinking 不生效，要关思考得用 reasoning.effort=none
                # （实测：thinking=disabled 仍有 23 个思考事件，effort=none 是 0 个）
                kwargs.setdefault('reasoning', {'effort': 'none'})
            else:
                # chat 这边关思考是 deepseek 自家的 thinking 字段
                extra = dict(kwargs.get('extra_body') or {})
                extra.setdefault('thinking', {'type': 'disabled'})
                kwargs['extra_body'] = extra
        call = lambda: _adaptive_call(original, base, args, kwargs, mode)
        if kwargs.get('stream'): return BoundedStream(call, first_seconds=budget)
        return bounded_call(call, budget)
    completions.create = create
    completions._shizuka_bounded = True
    completions._shizuka_mode = mode
    return client
