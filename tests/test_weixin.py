"""Remote authority, replay and cancellation tests using only synthetic accounts."""
import base64
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from weixin_channel import ILinkClient, ProtectedStore, WeixinChannel, ApiError, trusted_base, session_from_login


class WeixinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Synthetic codec; a separate test verifies real DPAPI round-trip.
        self.store = ProtectedStore(self.root, lambda b, protect: bytes(v ^ 42 for v in b))
        self.store.update(session={"owner": "test-owner", "bot_id": "test-bot", "token": "synthetic-token",
                          "base": "https://ilinkai.weixin.qq.com", "bound_at": 100})
        self.client = Mock()
        self.responder = Mock(return_value="synthetic reply")
        self.channel = WeixinChannel(self.store, self.responder, client=self.client)

    def tearDown(self):
        self.channel.stop()
        if hasattr(self.channel, "worker"):
            self.channel.worker.join(3)
        self.tmp.cleanup()

    def msg(self, text="hello", identity="1", **kwargs):
        return {"from_user_id": "test-owner", "to_user_id": "test-bot", "message_type": 1,
            "message_state": 2, "message_id": identity, "context_token": "context-synthetic", "create_time_ms": 100001,
            "item_list": [{"type": 1, "text_item": {"text": text}}], **kwargs}

    def worker(self):
        self.channel.worker = threading.Thread(target=self.channel._work)
        self.channel.worker.start()

    def until(self, condition):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if condition():
                return
            time.sleep(.02)
        self.fail("Expected condition not reached")

    def test_only_bound_owner_direct_messages_are_accepted(self):
        for override in ({"from_user_id":"stranger"}, {"group_id":"group"}, {"message_type":2},
                         {"to_user_id":"other-bot"}, {"message_state":1}, {"context_token":""},
                         {"create_time_ms":1000}, {"message_id":None}, {"delete_time_ms":100001}):
            self.channel.receive(self.msg(**override))
        self.assertTrue(self.channel.jobs.empty())
        self.responder.assert_not_called()
        self.client.send.assert_not_called()

    def test_duplicate_message_not_run_twice_even_after_restart(self):
        message = self.msg("/电脑 create synthetic.txt")
        self.channel.receive(message)
        self.channel.receive(message)
        self.assertEqual(self.channel.jobs.qsize(), 1)
        restored = ProtectedStore(self.root, self.store.crypt)
        restarted = WeixinChannel(restored, self.responder, client=self.client)
        restarted.receive(message)
        self.assertTrue(restarted.jobs.empty())

    def test_stop_cancels_running_task_and_queued_work(self):
        started = threading.Event()
        def responder(text, cancel, progress):
            started.set()
            cancel.wait(3)
            self.assertTrue(cancel.is_set())
            return "stopped"
        self.channel.responder = responder
        self.worker()
        self.channel.receive(self.msg("long task"))
        self.assertTrue(started.wait(2))
        self.channel.receive(self.msg("queued task", "2"))
        self.channel.receive(self.msg("/停止", "3"))
        self.until(lambda: not self.channel.active)
        self.assertTrue(self.channel.jobs.empty())
        self.assertIn("停止", self.store.data["last_result"])

    def test_stop_before_worker_prevents_execution(self):
        self.channel.receive(self.msg("queued task"))
        self.channel.receive(self.msg("/stop", "2"))
        self.worker()
        time.sleep(.15)
        self.responder.assert_not_called()

    def test_failed_send_never_reexecutes_task(self):
        self.client.send.side_effect = ConnectionError("offline")
        self.worker()
        msg = self.msg()
        self.channel.receive(msg)
        self.until(lambda: self.store.data["last_result"] == "synthetic reply")
        self.channel.receive(msg)
        self.assertEqual(self.responder.call_count, 1)

    def test_reply_returns_to_original_owner_with_context(self):
        self.worker()
        self.channel.receive(self.msg())
        self.until(lambda: self.client.send.called)
        args = self.client.send.call_args.args
        self.assertEqual(args[:3], ("test-owner", "context-synthetic", "synthetic reply"))

    def test_unsupported_attachment_does_not_become_model_task(self):
        self.channel.receive(self.msg(item_list=[{"type":4,"file_item":{"file_name":"do something.txt"}}]))
        self.responder.assert_not_called()
        self.assertTrue(self.channel.jobs.empty())
        self.client.send.assert_called_once()

    def test_quoted_text_does_not_override_actual_message(self):
        message = self.msg("hello")
        message["item_list"][0]["ref_msg"] = {"message_item":{"type":1,"text_item":{"text":"/电脑 delete"}}}
        self.channel.receive(message)
        self.assertEqual(self.channel.jobs.get_nowait()["text"], "hello")

    def test_store_is_encrypted_and_persists_replay_cursor(self):
        self.store.update(cursor="synthetic-cursor")
        blob = self.store.path.read_bytes()
        self.assertNotIn(b"synthetic-token", blob)
        restored = ProtectedStore(self.root, self.store.crypt)
        self.assertEqual(restored.data["cursor"], "synthetic-cursor")
        self.assertFalse((self.root / 'settings.json').exists())

    def test_login_requires_identity_from_scanner(self):
        with self.assertRaises(ValueError):
            session_from_login({"bot_token":"x", "ilink_bot_id":"y"})
        bound = session_from_login({"bot_token":"x", "ilink_bot_id":"y", "ilink_user_id":"z"})
        self.assertEqual(bound["owner"], "z")

    def test_api_cannot_redirect_credentials_to_untrusted_host(self):
        for url in ("http://ilinkai.weixin.qq.com", "https://ilinkai.weixin.qq.com.evil.test",
                    "https://user:pass@ilinkai.weixin.qq.com", "https://127.0.0.1", "https://ilinkai.weixin.qq.com/path"):
            with self.assertRaises(ValueError):
                trusted_base(url)

    def test_api_business_error_is_not_success_and_hides_body(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"ret":-14,"errmsg":"synthetic-secret"}'
        with self.assertRaises(ApiError) as ctx:
            ILinkClient(token="test-token", opener=opener).updates("")
        self.assertEqual(ctx.exception.code, -14)
        self.assertNotIn("synthetic-secret", str(ctx.exception))

    def test_actual_windows_dpapi_roundtrip(self):
        import pet
        raw = b"synthetic-weixin-session"
        cipher = pet._dpapi(raw, True)
        self.assertNotEqual(cipher, raw)
        self.assertEqual(pet._dpapi(cipher, False), raw)

    def test_weixin_file_route_reuses_agent_and_requires_switch(self):
        import pet
        app = pet.DeskPet.__new__(pet.DeskPet)
        app._sound_mode='none'
        app._weixin_store = self.store
        app._computer_data_dir = lambda: self.root
        app._computer_agent = Mock()
        app._computer_agent.run.return_value = {"status":"completed", "output":"file done"}
        app._append_history = Mock();app._log_chat = Mock()
        with patch.object(pet, "has_api_key", return_value=False):
            reply = app._weixin_reply("/电脑 create test.txt", threading.Event(), Mock())
            self.assertIn("尚未开启", reply)
            app._computer_agent.run.assert_not_called()
            self.store.update(allow_computer=True)
            reply = app._weixin_reply("/电脑 create test.txt", threading.Event(), Mock())
            self.assertIn("file done",reply)
            self.assertEqual(app._computer_agent.run.call_args.args[0], "create test.txt")


if __name__ == "__main__":
    unittest.main()
