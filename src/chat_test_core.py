"""Text-only test client: shared enhanced components, no pet/service imports."""
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
from chat_timeline import REVISION as TIMELINE_REVISION, local_now, render_timeline
from dialogue_mode import REVISION as DIALOGUE_MODE_REVISION

APP_VERSION = '0.8.7-chat-s27'
PERSONA_REVISION = 's27'
PERSONA_LABEL = 'S2.7'
FRAME_REVISION = 's27-context-v1'
CHAT_CAPABILITIES = ('【当前应用能力】这是由用户发消息触发回复的文字聊天窗口。'
                     '当前没有计时提醒、后台主动发送或操作用户手机的功能。'
                     '聊天里说过的约定不等于程序已经建立提醒，不能保证过几分钟自动回来发消息。')
DEFAULT_CONFIG = {'api_base': 'https://api.deepseek.com',
                  'api_model': 'deepseek-v4-flash-vision-exp', 'api_mode': 'responses'}
MAX_INPUT = 8000
MAX_CONTEXT = 48000
CHARACTERS = {
    'shizuka': {'name': '静香', 'label': 'S2.7 原口吻', 'revision': 's27', 'aliases': ('静香',)},
    'kokona': {'name': '心菜', 'label': 'K1 心菜', 'revision': 'k1', 'aliases': ('心菜', '凤心菜', '鳳ここな', 'ここな')},
}


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def validate_config(config):
    cleaned = {key: str(config.get(key, default)).strip() for key, default in DEFAULT_CONFIG.items()}
    parsed = urlsplit(cleaned['api_base'])
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('接口地址需为不含密码、查询参数的 HTTPS 地址。')
    if parsed.scheme != 'https' and not (local and parsed.scheme == 'http'):
        raise ValueError('远程接口需要 HTTPS；HTTP 仅限本机。')
    if cleaned['api_mode'] not in ('chat', 'responses'):
        raise ValueError('请选择 chat 或 responses 接口。')
    if not cleaned['api_model'] or len(cleaned['api_model']) > 160:
        raise ValueError('请填写有效模型名称。')
    cleaned['api_base'] = cleaned['api_base'].rstrip('/')
    return cleaned


def compile_persona(revision=PERSONA_REVISION):
    from dialogue_architecture_v2 import persona_core
    if revision not in ('s23', 's24', 's25', 's26', 's27', 's31-r', 'k1'):
        raise ValueError('Unknown test persona revision')
    path = resource_root() / ('characters/kokona/persona.k1.candidate.json' if revision == 'k1' else
                              'characters/shizuka-side-motion/persona.' + revision + '.candidate.json')
    raw = path.read_bytes()
    compiled = persona_core(path, character_neutral=revision == 'k1')
    if raw != path.read_bytes():
        raise ValueError('角色卡正在修改，请重新打开聊天窗口。')
    return compiled, hashlib.sha256(raw).hexdigest()


def compose_messages(persona, text, history, *, timestamps=(), now=None, natural_chat=False, character='shizuka', outer_variant='baseline'):
    """Use the same persona/compiler, hard contract, frame and output contract.

    This client deliberately has no tasks, observations, memory or auto messages.
    All supplied history is visible conversation; no private desktop state.
    """
    from enhanced_dialogue import compose_messages as compose
    return compose(persona,text,history,capabilities=CHAT_CAPABILITIES,natural_chat=natural_chat,
                   actor_names=CHARACTERS[character]['aliases'],outer_variant=outer_variant,
                   timeline=render_timeline(history,timestamps,now if now is not None else local_now()))


class ChatSession:
    def __init__(self, persona=None, persona_hash=None, clock=None, *, natural_chat=False, spoken=False, character='shizuka', outer_variant='baseline'):
        if character not in CHARACTERS:
            raise ValueError('未知的试聊角色。')
        self.character = character
        from outer_dialogue_trial import REVISION as OUTER_REVISION, validate_variant
        validate_variant(outer_variant)
        revision='s31-r' if spoken and character == 'shizuka' else CHARACTERS[character]['revision']
        if persona is None:
            persona, persona_hash = compile_persona(revision)
        self.persona = persona
        self.meta = {'app_version': APP_VERSION, 'character_id': character,
                     'character_name': CHARACTERS[character]['name'], 'persona_revision': revision,
                     'persona_sha256': persona_hash or '', 'frame_revision': FRAME_REVISION,
                     'timeline_revision': TIMELINE_REVISION, 'session_id': uuid4().hex,
                     'dialogue_mode_revision': DIALOGUE_MODE_REVISION, 'natural_chat': natural_chat is True,
                     'outer_revision': OUTER_REVISION, 'outer_variant': outer_variant}
        self.clock = clock or local_now
        self.exchanges = []
        self.started = time.monotonic()
        self.busy = False

    @property
    def outer_variant(self):
        return self.meta['outer_variant']

    @property
    def spoken(self):
        return self.meta['persona_revision']=='s31-r'

    def set_spoken(self,enabled):
        if self.busy:raise ValueError('请等本轮结束后再切换。')
        if self.character != 'shizuka':raise ValueError('当前角色使用独立角色卡。')
        revision='s31-r' if enabled else PERSONA_REVISION
        persona,digest=compile_persona(revision)
        self.persona=persona
        self.meta.update(persona_revision=revision,persona_sha256=digest)

    @property
    def natural_chat(self):
        return self.meta['natural_chat']

    def set_natural_chat(self, enabled):
        if self.busy:
            raise ValueError('请等本轮结束后再切换。')
        self.meta['natural_chat'] = enabled is True

    def _history_turns(self):
        pairs, size = [], 0
        for turn in reversed(self.exchanges):
            if turn['status'] not in ('complete', 'failed', 'cancelled'):
                continue
            pair_size = len(turn['user']) + (len(turn['assistant']) if turn['status'] == 'complete' else 0)
            if len(pairs) >= 50 or size + pair_size > MAX_CONTEXT:
                break
            pairs.append(turn)
            size += pair_size
        return list(reversed(pairs))

    def history(self):
        result = []
        for turn in self._history_turns():
            # A failed reply must not erase a visible constraint the user gave.
            # Partial model text is excluded; the user's original text survives.
            result.append({'role': 'user', 'content': turn['user']})
            if turn['status'] == 'complete' and turn['assistant']:
                result.append({'role': 'assistant', 'content': turn['assistant']})
        return result

    def history_timestamps(self):
        result = []
        for turn in self._history_turns():
            result.append(turn.get('user_at'))
            if turn['status'] == 'complete' and turn['assistant']:
                result.append(turn.get('assistant_at'))
        return result

    def begin(self, text, model):
        text = text.strip()
        if self.busy:
            raise ValueError('请等本轮结束。')
        if not text or len(text) > MAX_INPUT:
            raise ValueError('每条消息请输入 1–8000 个字符。')
        now = self.clock()
        request = compose_messages(self.persona, text, self.history(),
                                   timestamps=self.history_timestamps(), now=now, natural_chat=self.natural_chat,
                                   character=self.character, outer_variant=self.outer_variant)
        self.exchanges.append({'user': text, 'assistant': '', 'status': 'pending',
                               'elapsed_seconds': round(time.monotonic() - self.started), 'model': model,
                               'user_at': now, 'natural_chat': self.natural_chat,
                               'persona_revision': self.meta['persona_revision'], 'persona_sha256':self.meta['persona_sha256'],
                               'outer_revision': self.meta['outer_revision'], 'outer_variant': self.outer_variant,
                               'system_sha256': hashlib.sha256(request[0]['content'].encode('utf-8')).hexdigest()})
        self.busy = True
        return request

    def reply_started(self):
        if self.busy and not self.exchanges[-1].get('assistant_at'):
            self.exchanges[-1]['assistant_at'] = self.clock()

    def finish(self, reply='', status='complete'):
        if not self.busy:
            return
        if reply:
            self.reply_started()
        self.exchanges[-1].update(assistant=reply, status=status, ended_at=self.clock())
        self.busy = False

    def snapshot(self):
        return {'metadata': deepcopy(self.meta), 'exchanges': deepcopy(self.exchanges)}


def safe_error(exc):
    # Never show repr/str of remote errors: they may contain URLs, prompts or keys.
    status = getattr(exc, 'status_code', None)
    return {400: '接口不接受当前参数，请核对模型和接口类型。',
            401: '测试 key 未通过验证，请在连接设置中检查。',
            402: '测试接口额度不足。', 403: '接口拒绝访问，请联系提供测试 key 的人。',
            404: '接口或模型不存在，请核对地址与接口类型。',
            429: '请求较多或额度受限，请稍后再试。'}.get(status,
                '本轮未完成，请检查网络或连接设置后重试；没有自动重发。')


def stream_reply(config, key, messages, cancel, emit, client_factory=None):
    """One user-triggered request; reuse the existing tested protocol adapter."""
    from api_runtime import configure_client
    if client_factory is None:
        from openai import OpenAI
        client_factory = OpenAI
    if cancel.is_set():
        return ''
    chunks = []
    with client_factory(api_key=key, base_url=config['api_base'], timeout=15,
                        max_retries=0) as raw:
        client = configure_client(raw, config['api_base'], config['api_mode'], allow_retries=False)
        with client.chat.completions.create(model=config['api_model'], messages=messages,
                temperature=0.7, max_tokens=6000, stream=True, wait_seconds=60) as stream:
            for chunk in stream:
                if cancel.is_set():
                    break
                for choice in getattr(chunk, 'choices', ()) or ():
                    value = getattr(getattr(choice, 'delta', None), 'content', None)
                    if isinstance(value, str) and value:
                        chunks.append(value)
                        emit(value)
    return ''.join(chunks).strip()
