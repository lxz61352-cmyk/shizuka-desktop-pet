"""Bound interactive API waiting, including SSE heartbeats with no visible text."""
import queue
import threading
import time
from urllib.parse import urlsplit


DEEPSEEK_MODEL = 'deepseek-v4-flash-vision-exp'   # DeepSeek 官方接口统一用它（唯一带视觉的 flash 实验版）
DEEPSEEK_LEGACY_MODELS = ('deepseek-chat', 'deepseek-v4-flash', 'deepseek-flash',
                          'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp')


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


def probe_generation(key,base,model,seconds=12):
    """Test visible output from the selected model, not merely authentication."""
    import openai
    started=time.monotonic();stream=None
    result={'ok':False,'model':model,'kind':'empty'}
    try:
        with openai.OpenAI(api_key=key,base_url=base,timeout=min(seconds,10),max_retries=0) as raw:
            client=configure_client(raw,base)
            with client.chat.completions.create(model=model,messages=[{'role':'user','content':'只回复ok'}],
                    max_tokens=32,stream=True,wait_seconds=seconds) as stream:
                for chunk in stream:
                    if any(getattr(c.delta,'content',None) for c in chunk.choices):
                        result.update(ok=True,kind='ready');break
    except Exception as exc:
        result['kind']='timeout' if isinstance(exc,(TimeoutError,openai.APITimeoutError)) else 'connection'
        status=getattr(exc,'status_code',None)
        if status is not None:result.update(kind='http',status=status)
    result['seconds']=round(time.monotonic()-started,2)
    return result


def probe_status(result):
    model=result['model']
    if result['ok']:return f"可正常回复：{model} · 首字 {result['seconds']:.1f} 秒"
    if result['kind']=='timeout':return f'{model} 生成超时；设置已保存，当前模型尚未返回正文。'
    if result['kind']=='empty':return f'{model} 未返回正文；设置已保存。'
    code=result.get('status')
    detail={400:'模型名或参数不被接口接受',401:'密钥未通过验证',402:'接口额度不足',403:'接口拒绝访问',429:'接口繁忙，请稍后重试'}.get(code)
    return f"{model}：{detail or ('接口错误 '+str(code) if code else '连接失败，请检查地址和网络')}。设置已保存。"


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


def _model_caps(base, model):
    key = (base, model or '')
    with _MODEL_CAPS_LOCK:
        cached = _MODEL_CAPS.get(key)
        if cached is not None:
            return cached
        if len(_MODEL_CAPS) >= _MODEL_CAPS_MAX:
            for stale in list(_MODEL_CAPS)[:max(1, _MODEL_CAPS_MAX // 4)]:
                _MODEL_CAPS.pop(stale, None)
        return _MODEL_CAPS.setdefault(key, {'max_key': 'max_tokens', 'temp': True, 'thinking': True})


def _build_kwargs(kwargs, caps):
    k = dict(kwargs)
    if 'max_tokens' in k:
        k[caps['max_key']] = k.pop('max_tokens')
    if not caps['temp']:
        k.pop('temperature', None)
    if not caps.get('thinking', True) and isinstance(k.get('extra_body'), dict):
        extra = {name: value for name, value in k['extra_body'].items() if name != 'thinking'}
        if extra:
            k['extra_body'] = extra
        else:
            k.pop('extra_body', None)
    return k


def _adaptive_call(original, base, args, kwargs):
    """按模型能力自动修正参数：不接受 temperature 就去掉；不支持 max_tokens 就换
    max_completion_tokens（o 系 / gpt-5 等）；不接受 thinking 就去掉。首次自动探测并记住。"""
    caps = _model_caps(base, kwargs.get('model'))
    for _ in range(4):   # 最多修正三次（温度、max_tokens、thinking 各一次）
        try:
            return original(*args, **_build_kwargs(kwargs, caps))
        except Exception as exc:
            msg = str(exc).lower()
            changed = False
            if 'temperature' in msg and caps['temp']:
                caps['temp'] = False
                changed = True
            # 「max_tokens is too large」这类报错不是「不支持该参数」，别误切成 max_completion_tokens
            unsupported = ('not support', 'unsupported', 'unknown', 'unexpect', 'unrecogniz',
                           'not allowed', 'does not support', 'requires')
            if (('max_tokens' in msg or 'max_completion_tokens' in msg) and caps['max_key'] != 'max_completion_tokens'
                    and any(word in msg for word in unsupported)):
                caps['max_key'] = 'max_completion_tokens'
                changed = True
            if 'thinking' in msg and caps.get('thinking', True):
                caps['thinking'] = False
                changed = True
            if not changed:
                raise
    return original(*args, **_build_kwargs(kwargs, caps))


def configure_client(client, base):
    completions = client.chat.completions
    if getattr(completions, '_shizuka_bounded', False): return client
    original = completions.create
    def create(*args, **kwargs):
        budget = kwargs.pop('wait_seconds', 25)
        kwargs.setdefault('timeout', min(budget, 20))
        if urlsplit(base).hostname == 'api.deepseek.com':
            extra = dict(kwargs.get('extra_body') or {})
            extra.setdefault('thinking', {'type': 'disabled'})
            kwargs['extra_body'] = extra
        call = lambda: _adaptive_call(original, base, args, kwargs)
        if kwargs.get('stream'): return BoundedStream(call, first_seconds=budget)
        return bounded_call(call, budget)
    completions.create = create
    completions._shizuka_bounded = True
    return client
