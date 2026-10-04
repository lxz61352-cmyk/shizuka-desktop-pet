from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
import pre_reply_affect_runtime as runtime
import pre_reply_affect as original


NOW = '2026-09-30T14:00:00+08:00'
USER = '我拿到录用通知了！'


def plan(**overrides):
    value = dict(mood_delta=6, emotion='excited', event_kind='good_news', target='user',
                 cause='拿到录用通知', event_ref='', relation='new', intensity='clear')
    value.update(overrides)
    return json.dumps(value, ensure_ascii=False)


class FakeClient:
    def __init__(self, response=None, on_request=None):
        self.response = plan() if response is None else response
        self.on_request = on_request
        self.requests = []
        self.chat = NS(completions=self)

    @contextmanager
    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        if self.on_request:
            self.on_request(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        response = self.response(kwargs) if callable(self.response) else self.response
        yield iter([NS(choices=[NS(delta=NS(content=response, reasoning_content='not saved'))])])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.namespace = 'shizuka-side-motion'
        self.kwargs = dict(model='fake-model', temperature=.7, max_tokens=2200,
            messages=[dict(role='system', content='body persona')],
            _shizuka_profile=dict(key='deepseek', temperature=.7, max_value=6000,
                                 max_key='max_tokens', model='fake-model'),
            api_key='NEVER_SAVE_CREDENTIAL')
        self.messages = [dict(role='user', content=USER)]

    def prepare(self, client=None, **options):
        return runtime.prepare_reply(client or FakeClient(), self.kwargs,
            options.pop('messages', self.messages), options.pop('cancel', None),
            options.pop('namespace', self.namespace), self.root, options.pop('now', NOW), **options)

    def saved(self):
        return json.loads(runtime.state_path(self.root, self.namespace).read_text('utf-8'))

    def test_runtime_keeps_saved_schema_and_frozen_clock_but_isolates_assessment(self):
        self.assertEqual((ROOT / 'src/runtime_affect_lab.py').read_text('utf-8'),
                         (ROOT / 'tools/affect_lab.py').read_text('utf-8'))
        state = runtime.lab.empty(NOW)
        self.assertEqual(set(state), set(original.lab.empty(NOW)))
        payload = json.loads(runtime.affect.assessment_messages(self.messages, state, NOW)[1]['content'])
        self.assertNotIn('mood', payload['state'])
        self.assertNotIn('recent_changes', payload['state'])
        self.assertNotIn('energy', payload['state'])

    def test_preview_uses_new_state_only_successful_commit_persists(self):
        client = FakeClient()
        transaction = self.prepare(client, turn_id='turn-1')
        self.assertEqual(transaction.assessment_status, 'valid')
        self.assertIn('本轮表达倾向', transaction.rendered_context)
        self.assertNotIn('/100', transaction.rendered_context)
        self.assertIn('兴奋（明显）', transaction.rendered_context)
        self.assertNotIn('拿到录用通知', transaction.rendered_context)
        path = runtime.state_path(self.root, self.namespace)
        self.assertEqual(path.parent, self.root)
        self.assertFalse(path.exists())
        self.assertTrue(transaction.commit(True))
        self.assertEqual(self.saved()['state']['mood'], 71)
        self.assertEqual(self.saved()['state']['applied'], ['turn-1'])
        self.assertFalse(transaction.commit(True))
        self.assertEqual(self.saved()['version'], 1)
        stored = path.read_text('utf-8')
        for secret in ('NEVER_SAVE_CREDENTIAL', 'body persona', 'not saved', 'api_key', 'requests'):
            self.assertNotIn(secret, stored)

    def test_assessment_overrides_profile_without_changing_caller_data(self):
        original_input = deepcopy((self.kwargs, self.messages))
        client = FakeClient()
        acquired = []
        self.prepare(client, acquire=lambda: acquired.append(True))
        request = client.requests[0]
        self.assertEqual(acquired, [True])
        self.assertEqual((self.kwargs, self.messages), original_input)
        self.assertEqual(request['temperature'], 0)
        self.assertEqual(request['max_tokens'], 800)
        self.assertEqual(request['_shizuka_profile']['temperature'], 0)
        self.assertEqual(request['_shizuka_profile']['max_value'], 800)
        self.assertEqual(request['wait_seconds'], 45)
        self.assertEqual(request['response_format'], {'type': 'json_object'})
        self.assertEqual(request['reasoning'], {'effort': 'none'})
        self.assertEqual(request['extra_body']['thinking'], {'type': 'disabled'})
        self.assertTrue(request['stream'])
        self.assertNotIn('api_key', request)

    def test_failed_reply_and_retry_do_not_double_settle(self):
        failed = self.prepare(turn_id='same-turn')
        self.assertFalse(failed.commit(False))
        self.assertFalse(runtime.state_path(self.root, self.namespace).exists())
        retry = self.prepare(turn_id='same-turn')
        self.assertTrue(retry.commit(True))
        duplicate = self.prepare(turn_id='same-turn')
        self.assertTrue(duplicate.commit(True))
        self.assertEqual(self.saved()['state']['mood'], 71)
        self.assertEqual(self.saved()['state']['applied'], ['same-turn'])

    def test_exact_duplicate_new_event_and_repeat_keep_emotion_without_points(self):
        self.assertTrue(self.prepare(turn_id='first').commit(True))
        repeated = self.prepare(turn_id='second')
        self.assertIn('本轮表达倾向', repeated.rendered_context)
        self.assertIn('兴奋（明显）', repeated.rendered_context)
        self.assertTrue(repeated.commit(True))
        self.assertEqual(self.saved()['state']['settlements'][-1]['delta'], 0)
        self.assertEqual(self.saved()['state']['settlements'][-1]['relation'], 'repeat')

    def test_invalid_boolean_duplicate_field_and_unknown_id_fall_back(self):
        raw_values = [plan(mood_delta=True), plan()[:-1] + ',"mood_delta":6}',
                      plan(event_ref='evt_missing', relation='repeat'), 'not json']
        for index, raw in enumerate(raw_values):
            with self.subTest(raw=raw):
                transaction = self.prepare(FakeClient(raw), namespace='bad-' + str(index))
                self.assertEqual(transaction.assessment_status, 'invalid')
                self.assertIn('平常自然', transaction.rendered_context)
                self.assertNotIn('即时反应：', transaction.rendered_context)
                self.assertTrue(transaction.commit(True))
                saved = json.loads(runtime.state_path(self.root, 'bad-' + str(index)).read_text('utf-8'))
                self.assertEqual(saved['state']['applied'], [])
                self.assertEqual(saved['state']['mood'], 65)

    def test_network_failure_does_not_score_or_save_error_text(self):
        transaction = self.prepare(FakeClient(RuntimeError('NEVER_SAVE_CREDENTIAL')))
        self.assertEqual(transaction.assessment_status, 'error')
        self.assertEqual(transaction.error_type, 'RuntimeError')
        self.assertNotIn('即时反应：', transaction.rendered_context)
        self.assertTrue(transaction.commit(True))
        self.assertEqual(self.saved()['state']['mood'], 65)
        self.assertEqual(self.saved()['state']['applied'], [])

    def test_cancellation_before_during_and_after_assessment_never_commits(self):
        for when in ('before', 'during', 'after'):
            with self.subTest(when=when):
                cancel = threading.Event()
                if when == 'before':
                    cancel.set()
                client = FakeClient(on_request=(lambda _: cancel.set()) if when == 'during' else None)
                transaction = self.prepare(client, cancel=cancel, namespace=when)
                if when == 'after':
                    cancel.set()
                self.assertFalse(transaction.commit(True))
                self.assertFalse(runtime.state_path(self.root, when).exists())
                if when == 'before':
                    self.assertEqual(client.requests, [])

    def test_acquire_cancel_skips_request(self):
        cancel = threading.Event()
        client = FakeClient()
        transaction = self.prepare(client, cancel=cancel, acquire=cancel.set)
        self.assertEqual(transaction.assessment_status, 'cancelled')
        self.assertFalse(transaction.assessment_attempted)
        self.assertEqual(client.requests, [])

    def test_multimodal_uses_text_only_and_image_only_does_not_rescore_history(self):
        client = FakeClient()
        messages = [dict(role='system', content='do not assess system'),
                    dict(role='user', content=[dict(type='text', text=USER),
                         dict(type='image_url', image_url={'url': 'secret-image-url'})])]
        transaction = self.prepare(client, messages=messages)
        self.assertEqual(transaction.assessment_status, 'valid')
        payload = json.loads(client.requests[0]['messages'][1]['content'])
        self.assertEqual(payload['conversation'], self.messages)
        self.assertNotIn('secret-image-url', json.dumps(client.requests))
        image_only = FakeClient()
        transaction = self.prepare(image_only, messages=self.messages + [
            dict(role='assistant', content='恭喜！'),
            dict(role='user', content=[dict(type='image_url', image_url={'url': 'image-only'})])])
        self.assertEqual(transaction.assessment_status, 'no_text')
        self.assertEqual(image_only.requests, [])

    def test_network_does_not_hold_lock_and_stale_transaction_cannot_overwrite(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        def waiting(_):
            entered.set()
            self.assertTrue(release.wait(3))
        thread = threading.Thread(target=lambda: results.append(
            self.prepare(FakeClient(on_request=waiting), turn_id='older')))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            newer = self.prepare(turn_id='newer')
            self.assertTrue(newer.commit(True))
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].assessment_status, 'valid')
        self.assertFalse(results[0].commit(True))
        self.assertEqual(results[0].commit_status, 'stale')
        self.assertEqual(self.saved()['state']['applied'], ['newer'])

    def test_corrupt_state_is_not_overwritten_or_scored(self):
        path = runtime.state_path(self.root, self.namespace)
        path.write_bytes(b'broken state')
        client = FakeClient()
        transaction = self.prepare(client)
        self.assertEqual(transaction.assessment_status, 'storage_error')
        self.assertEqual(client.requests, [])
        self.assertFalse(transaction.commit(True))
        self.assertEqual(path.read_bytes(), b'broken state')

    def test_namespace_and_bounds_are_program_owned(self):
        for namespace, mood, delta in (('../high', 99, 6), ('../low', 1, -6)):
            path = runtime.state_path(self.root, namespace)
            self.assertEqual(path.parent, self.root)
            state = runtime.lab.empty(NOW)
            state['mood'] = mood
            runtime._write(path, 1, state)
            transaction = self.prepare(FakeClient(plan(mood_delta=delta)), namespace=namespace)
            self.assertTrue(transaction.commit(True))
            saved = json.loads(path.read_text('utf-8'))['state']
            self.assertEqual(saved['mood'], 100 if delta > 0 else 0)
        self.assertFalse(runtime.state_path(self.root, self.namespace).exists())

    def test_failed_atomic_replace_preserves_prior_state(self):
        self.assertTrue(self.prepare(turn_id='old').commit(True))
        path = runtime.state_path(self.root, self.namespace)
        before = path.read_bytes()
        transaction = self.prepare(turn_id='new')
        with patch.object(runtime.os, 'replace', side_effect=OSError('disk failure')):
            self.assertFalse(transaction.commit(True))
        self.assertEqual(transaction.commit_status, 'storage_error')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
