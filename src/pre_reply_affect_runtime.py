"""Persistent transaction wrapper for the frozen pre-reply affect semantics.

``root`` is the application's DATA_DIR, not its installation directory. A
namespace identifies the character, shared across desktop and Weixin. The app's
single-instance lock excludes other processes; this module serializes local
state access and compares the saved snapshot before replacing it. No state lock
is held during model calls. A stale transaction is discarded, never rebased.

Only the program-owned ledger is persisted. Requests, credentials, model raw
output, and reasoning are not saved. The caller must commit only after successful
delivery/display of the complete body, and must pass its cancellation callback.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

import runtime_affect_event_lab as lab
import runtime_pre_reply_affect as affect


REVISION = 'pre-reply-affect-runtime-v1'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path):
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _cancelled(cancel):
    if cancel is None:
        return False
    try:
        return bool(cancel() if callable(cancel) else cancel.is_set())
    except Exception:
        return True


def state_path(root, namespace):
    """Safe deterministic path; namespace text cannot become a filesystem path."""
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError('A character namespace is required')
    digest = hashlib.sha256(namespace.encode('utf-8')).hexdigest()
    return Path(root).resolve() / ('pre-reply-affect-' + digest + '.json')


def _read(path, now):
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return lab.empty(now), 0, None
    envelope = json.loads(content.decode('utf-8-sig'), object_pairs_hook=affect._unique,
                          parse_constant=affect._invalid_constant)
    if (not isinstance(envelope, dict) or set(envelope) != {'schema', 'version', 'state'}
            or envelope['schema'] != REVISION or type(envelope['version']) is not int
            or envelope['version'] < 1):
        raise ValueError('Invalid persisted state envelope')
    state = envelope['state']
    if (not isinstance(state, dict) or set(state) != set(lab.empty(now))
            or state.get('revision') != lab.REVISION):
        raise ValueError('Invalid persisted state fields')
    for field in ('effects', 'windows', 'applied', 'events', 'settlements'):
        if not isinstance(state[field], list):
            raise ValueError('Invalid persisted ledger')
    if not all(isinstance(value, str) for value in state['applied']):
        raise ValueError('Invalid persisted turn IDs')
    affect.render(state)
    lab.context(state)
    lab.advance(state, now)
    return state, envelope['version'], hashlib.sha256(content).hexdigest()


def _write(path, version, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = dict(schema=REVISION, version=version, state=state)
    value = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.stem + '-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def visible_text(messages):
    """Keep role-labelled text only; image/audio URLs and tool data are excluded.

    An image-only latest user turn stays empty rather than falling back to an
    older user's message. It therefore skips assessment instead of re-scoring it.
    """
    visible = []
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('user', 'assistant'):
            continue
        content = message.get('content')
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = '\n'.join(part['text'] for part in content if isinstance(part, dict)
                             and part.get('type') in ('text', 'input_text')
                             and isinstance(part.get('text'), str))
        else:
            text = ''
        visible.append(dict(role=message['role'], content=text))
    return visible


def assessment_kwargs(request_kwargs, messages):
    """Override only this assessment's request/profile, never the body request."""
    kwargs = dict(model=request_kwargs['model'], messages=messages, temperature=0,
                  max_tokens=800, response_format={'type': 'json_object'},
                  stream=True, wait_seconds=45, reasoning={'effort': 'none'})
    if 'timeout' in request_kwargs:
        kwargs['timeout'] = request_kwargs['timeout']
    kwargs['extra_body'] = deepcopy(request_kwargs.get('extra_body') or {})
    kwargs['extra_body']['thinking'] = {'type': 'disabled'}
    profile = request_kwargs.get('_shizuka_profile')
    if profile:
        kwargs['_shizuka_profile'] = deepcopy(profile)
        kwargs['_shizuka_profile'].update(temperature=0, max_value=800)
    return kwargs


class ReplyAffectTransaction:
    """A one-shot preview; ``commit(True)`` returns whether disk was updated."""
    def __init__(self, path, version, fingerprint, old, preview, context, cancel,
                 now, status, writable=True, attempted=False, error_type=None, plan=None):
        self.rendered_context = context
        self.assessment_status = status
        self.assessment_attempted = attempted
        self.error_type = error_type
        # 本轮判断结果（emotion / intensity 等），判断失败或取消时为 None。
        # 表情包触发要读它——渲染后的文本里读不出结构化情绪。
        self.instant = deepcopy(plan) if isinstance(plan, dict) else None
        self.commit_status = 'pending'
        self._path, self._version, self._fingerprint = path, version, fingerprint
        self._old, self._preview = deepcopy(old), deepcopy(preview)
        self._cancel, self._now, self._writable = cancel, now, writable
        self._finished = False
        self._guard = threading.Lock()

    def commit(self, success):
        with self._guard:
            if self._finished:
                return False
            self._finished = True
            if success is not True:
                self.commit_status = 'reply_failed'
                return False
            if self.assessment_status == 'cancelled' or _cancelled(self._cancel):
                self.commit_status = 'cancelled'
                return False
            if not self._writable:
                self.commit_status = 'storage_unavailable'
                return False
            try:
                with _lock(self._path):
                    _, version, fingerprint = _read(self._path, self._now)
                    if (version, fingerprint) != (self._version, self._fingerprint):
                        self.commit_status = 'stale'
                        return False
                    if _cancelled(self._cancel):
                        self.commit_status = 'cancelled'
                        return False
                    state = affect.finish(self._old, self._preview, 'complete')
                    _write(self._path, version + 1, state)
                self.commit_status = 'committed'
                return True
            except Exception as error:
                self.error_type = type(error).__name__
                self.commit_status = 'storage_error'
                return False


def prepare_reply(client, request_kwargs, history_and_user_messages, cancel,
                  namespace, root, now=None, *, acquire=lambda: None, turn_id=None):
    """Assess once, render its preview now, and persist only after body success.

    ``root`` must be DATA_DIR. ``cancel`` accepts a callable or threading.Event.
    ``acquire`` is the caller's provider limiter, invoked without the state lock.
    Reuse ``turn_id`` for retries of the same application turn when available.
    JSON/transport failures return old-state context without immediate labels.
    """
    now = now or datetime.now().astimezone().isoformat()
    lab.base.instant(now)
    path = state_path(root, namespace)
    turn_id = turn_id or uuid.uuid4().hex
    writable, error_type = True, None
    try:
        with _lock(path):
            stored, version, fingerprint = _read(path, now)
        before = lab.advance(stored, now)
    except Exception as error:
        before, version, fingerprint = lab.empty(now), 0, None
        writable, error_type = False, type(error).__name__
    preview, plan = deepcopy(before), None
    attempted = False
    status = 'storage_error' if not writable else 'no_text'
    if writable:
        try:
            visible = visible_text(history_and_user_messages)
            if _cancelled(cancel):
                status = 'cancelled'
            elif visible and visible[-1]['role'] == 'user' and visible[-1]['content'].strip():
                messages = affect.assessment_messages(visible, before, now)
                kwargs = assessment_kwargs(request_kwargs, messages)
                acquire()
                if _cancelled(cancel):
                    raise InterruptedError('Cancelled before assessment')
                attempted = True
                chunks = []
                size = 0
                with client.chat.completions.create(**kwargs) as stream:
                    for chunk in stream:
                        if _cancelled(cancel):
                            raise InterruptedError('Cancelled during assessment')
                        for choice in getattr(chunk, 'choices', None) or ():
                            value = getattr(getattr(choice, 'delta', None), 'content', None)
                            if isinstance(value, str):
                                size += len(value)
                                if size > 65536:
                                    raise ValueError('Assessment exceeded JSON size limit')
                                chunks.append(value)
                if _cancelled(cancel):
                    raise InterruptedError('Cancelled after assessment')
                try:
                    plan = affect.resolve_plan(before, visible[-1]['content'],
                                               affect.validate(''.join(chunks), visible))
                    preview, _ = affect.prepare(before, turn_id, visible[-1]['content'], plan, now)
                    status = 'valid'
                except (ValueError, TypeError, KeyError) as error:
                    plan, preview = None, deepcopy(before)
                    status, error_type = 'invalid', type(error).__name__
        except InterruptedError:
            plan, preview, status = None, deepcopy(before), 'cancelled'
        except Exception as error:
            plan, preview = None, deepcopy(before)
            status, error_type = 'error', type(error).__name__
    context = affect.render(preview, plan)
    return ReplyAffectTransaction(path, version, fingerprint, before, preview, context,
        cancel, now, status, writable, attempted, error_type, plan)
