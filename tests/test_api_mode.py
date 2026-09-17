"""接口类型（chat / response）：形状翻译、流式伪装、失败回退、设置读写。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import api_runtime  # noqa: E402
import pet  # noqa: E402


class ModeTests(unittest.TestCase):
    def test_normalize_and_label(self):
        self.assertEqual(api_runtime.normalize_mode("responses"), "responses")
        self.assertEqual(api_runtime.normalize_mode("response"), "responses")
        self.assertEqual(api_runtime.normalize_mode("RESPONSES"), "responses")
        self.assertEqual(api_runtime.normalize_mode("chat"), "chat")
        self.assertEqual(api_runtime.normalize_mode(""), "chat")
        self.assertEqual(api_runtime.normalize_mode(None), "chat")
        self.assertEqual(api_runtime.mode_label("responses"), "response")
        self.assertEqual(api_runtime.mode_label("chat"), "chat")

    def test_input_translation(self):
        items = api_runtime._to_responses_input([
            {"role": "system", "content": "你是静香"},
            {"role": "user", "content": [{"type": "text", "text": "看这图"},
                                         {"type": "image_url",
                                          "image_url": {"url": "data:image/png;base64,xx"}}]},
            {"role": "assistant", "content": "好的"},
        ])
        self.assertEqual(items[0]["content"][0], {"type": "input_text", "text": "你是静香"})
        self.assertEqual(items[1]["content"][1], {"type": "input_image", "image_url": "data:image/png;base64,xx"})
        self.assertEqual(items[2]["content"][0]["type"], "output_text")

    def test_kwargs_translation(self):
        caps = api_runtime._model_caps("https://example.invalid", "m", "responses")
        out = api_runtime._responses_kwargs(
            {"model": "m", "messages": [{"role": "user", "content": "hi"}],
             "max_tokens": 100, "temperature": 0.7,
             "response_format": {"type": "json_object"}}, caps)
        self.assertNotIn("messages", out)
        self.assertEqual(out["max_output_tokens"], 100)
        self.assertNotIn("max_tokens", out)
        self.assertEqual(out["text"], {"format": {"type": "json_object"}})
        self.assertEqual(out["temperature"], 0.7)

    def test_caps_differ_per_mode(self):
        self.assertEqual(api_runtime._model_caps("https://example.invalid", "m", "chat")["max_key"], "max_tokens")
        self.assertEqual(api_runtime._model_caps("https://example.invalid", "m", "responses")["max_key"],
                         "max_output_tokens")

    def test_probe_line_success_and_failure(self):
        ok = api_runtime.probe_line({"ok": True, "model": "glm-4-flash", "mode": "chat"})
        self.assertIn("glm-4-flash", ok)
        self.assertIn("chat api", ok)
        self.assertIn("连接成功", ok)
        bad = api_runtime.probe_line({"ok": False, "model": "gpt-x", "mode": "responses",
                                      "kind": "http", "status": 404})
        self.assertIn("gpt-x", bad)
        self.assertIn("response api", bad)
        self.assertIn("连接失败", bad)


class _Event:
    def __init__(self, kind, delta=None):
        self.type = kind
        self.delta = delta


class _Stream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def close(self):
        self.closed = True

    def __iter__(self):
        return iter(self.events)


class _FakeResponses:
    def __init__(self, text="ok", events=None, stream_fails=False):
        self.text = text
        self.events = events or []
        self.stream_fails = stream_fails
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            if self.stream_fails:
                raise RuntimeError("this provider does not support streaming")
            return _Stream(self.events)
        return type("R", (), {"output_text": self.text, "output": []})()


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("M", (), {"content": "chat 回包"})()
        choice = type("C", (), {"message": message, "delta": None})()
        return type("R", (), {"choices": [choice]})()


class _FakeClient:
    def __init__(self, **kwargs):
        self.responses = _FakeResponses(**kwargs)
        self.completions = _FakeCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


BASE = "https://example.invalid/v1"


class RoutingTests(unittest.TestCase):
    def test_responses_mode_routes_to_responses(self):
        client = _FakeClient(text="responses 回包")
        api_runtime.configure_client(client, BASE, "responses")
        reply = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],
                                               max_tokens=64, wait_seconds=5)
        self.assertEqual(reply.choices[0].message.content, "responses 回包")
        self.assertEqual(client.completions.calls, [])          # 没走 chat
        sent = client.responses.calls[0]
        self.assertIn("input", sent)
        self.assertEqual(sent["max_output_tokens"], 64)

    def test_chat_mode_still_uses_chat(self):
        client = _FakeClient()
        api_runtime.configure_client(client, BASE, "chat")
        reply = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],
                                               max_tokens=64, wait_seconds=5)
        self.assertEqual(reply.choices[0].message.content, "chat 回包")
        self.assertEqual(client.responses.calls, [])

    def test_responses_stream_is_chat_shaped(self):
        client = _FakeClient(events=[_Event("response.created"),
                                     _Event("response.output_text.delta", "你"),
                                     _Event("response.output_text.delta", "好"),
                                     _Event("response.completed")])
        api_runtime.configure_client(client, BASE, "responses")
        with client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],
                                            stream=True, wait_seconds=5) as stream:
            text = "".join(chunk.choices[0].delta.content or "" for chunk in stream)
        self.assertEqual(text, "你好")

    def test_stream_failure_falls_back_to_one_shot(self):
        client = _FakeClient(text="一次性回包", stream_fails=True)
        api_runtime.configure_client(client, BASE, "responses")
        with client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],
                                           stream=True, wait_seconds=5) as stream:
            text = "".join(chunk.choices[0].delta.content or "" for chunk in stream)
        self.assertEqual(text, "一次性回包")

    def test_reasoning_events_are_not_reply_text(self):
        # 实测 DeepSeek 的 responses 会先发 response.reasoning_text.delta，
        # 那个也算 text.delta，混进来桌宠就会把推理念出来
        client = _FakeClient(events=[_Event("response.reasoning_text.delta", "用户问的是"),
                                     _Event("response.output_text.delta", "1,2,3"),
                                     _Event("response.reasoning_text.delta", "再想想")])
        api_runtime.configure_client(client, BASE, "responses")
        with client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],
                                           stream=True, wait_seconds=5) as stream:
            text = "".join(chunk.choices[0].delta.content or "" for chunk in stream)
        self.assertEqual(text, "1,2,3")

    def test_deepseek_responses_asks_for_no_reasoning(self):
        client = _FakeClient(text="ok")
        api_runtime.configure_client(client, "https://api.deepseek.com", "responses")
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}], wait_seconds=5)
        self.assertEqual(client.responses.calls[0].get("reasoning"), {"effort": "none"})
        self.assertNotIn("extra_body", client.responses.calls[0])

    def test_deepseek_chat_keeps_the_thinking_flag(self):
        client = _FakeClient(text="ok")
        api_runtime.configure_client(client, "https://api.deepseek.com", "chat")
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}], wait_seconds=5)
        self.assertEqual(client.completions.calls[0]["extra_body"]["thinking"], {"type": "disabled"})

    def test_reasoning_is_dropped_when_the_provider_rejects_it(self):
        caps = api_runtime._model_caps("https://example.invalid", "m", "responses")
        caps["reasoning"] = False
        try:
            out = api_runtime._responses_kwargs({"model": "m", "messages": [], "reasoning": {"effort": "none"}}, caps)
            self.assertNotIn("reasoning", out)
        finally:
            caps["reasoning"] = True

    def test_images_survive_translation(self):
        client = _FakeClient(text="看图了")
        api_runtime.configure_client(client, BASE, "responses")
        client.chat.completions.create(
            model="m", wait_seconds=5,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,yy"}}]}])
        sent = client.responses.calls[0]
        self.assertEqual(sent["input"][0]["content"][1],
                         {"type": "input_image", "image_url": "data:image/png;base64,yy"})


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.saved = pet.SETTINGS_FILE
        pet.SETTINGS_FILE = str(self.path)

    def tearDown(self):
        pet.SETTINGS_FILE = self.saved
        self.tmp.cleanup()

    def test_default_is_chat(self):
        self.assertEqual(pet.load_settings()["api_mode"], "chat")

    def test_stored_mode_is_read(self):
        self.path.write_text(json.dumps({"api_mode": "responses"}), encoding="utf-8")
        self.assertEqual(pet.load_settings()["api_mode"], "responses")


if __name__ == "__main__":
    unittest.main()
