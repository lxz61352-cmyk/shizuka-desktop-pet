"""微信引用的收发：ID 多字段查找、失败诊断、发送侧引用与退回。

背景（2026-09-30）：实测引用缓存里同一条用户消息会以三种互不相交的 ID 形态各存一份
（message_id / msg_id / client_id，数字部分零交集），而她自己的消息只存了发送接口返回的
那一个。原实现只按 `svr_id` 一个字段查，查不到就整条引用作废。
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from weixin_channel import ALWAYS_QUOTE_FLAG, QUOTE_ID_FIELDS, ILinkClient, ProtectedStore, WeixinChannel


class QuoteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ProtectedStore(self.root, lambda b, protect: bytes(v ^ 42 for v in b))
        self.store.update(session={"owner": "o", "bot_id": "b", "token": "t",
                                   "base": "https://ilinkai.weixin.qq.com", "bound_at": 1})
        self.client = Mock()
        self.channel = WeixinChannel(self.store, lambda *a, **k: "reply", client=self.client)

    def tearDown(self):
        self.tmp.cleanup()


class QuoteLookupTests(QuoteCase):
    def test_finds_message_cached_under_any_id_field(self):
        self.channel.materials.remember(["7510628017901055240"], text="原句", role="assistant")
        for field in QUOTE_ID_FIELDS:
            self.assertEqual(self.channel._quote_lookup({field: "7510628017901055240"})["text"],
                             "原句", field)

    def test_returns_none_when_no_field_matches(self):
        self.channel.materials.remember(["aaa"], text="原句", role="assistant")
        self.assertIsNone(self.channel._quote_lookup({"svr_id": "bbb", "msg_id": "ccc"}))

    def test_ignores_empty_and_missing_fields(self):
        self.channel.materials.remember(["aaa"], text="原句", role="assistant")
        self.assertIsNone(self.channel._quote_lookup({"svr_id": "", "msg_id": None, "client_id": "zzz"}))

    def test_miss_writes_a_bounded_diagnostic(self):
        for index in range(25):
            self.channel._note_quote_miss({"svr_id": "s%d" % index, "message_item": {"type": 1}})
        path = self.root / "weixin-quote-debug.jsonl"
        lines = path.read_text("utf-8").splitlines()
        self.assertEqual(len(lines), 20, "诊断文件必须限量，不能无限增长")
        row = json.loads(lines[-1])
        self.assertEqual(row["ids"]["svr_id"], "s24")
        self.assertTrue(row["has_message_item"])
        self.assertIn("cached_ids", row)


class QuoteSendTests(QuoteCase):
    def _client(self, seen):
        client = ILinkClient.__new__(ILinkClient)

        def call(endpoint, payload=None, **kwargs):
            seen.append((endpoint, payload))
            return {}
        client.call = call
        return client

    def test_send_carries_the_reference_when_asked(self):
        seen = []
        self._client(seen).send("peer", "ctx", "你好", "cid", quote_svr_id="751062801790")
        item = seen[-1][1]["msg"]["item_list"][0]
        self.assertEqual(item["ref_msg"], {"svr_id": "751062801790"})
        self.assertEqual(item["text_item"]["text"], "你好")

    def test_send_without_a_quote_stays_unchanged(self):
        seen = []
        self._client(seen).send("peer", "ctx", "你好", "cid")
        self.assertNotIn("ref_msg", seen[-1][1]["msg"]["item_list"][0])

    def test_quote_includes_original_content_and_summary(self):
        seen = []
        self._client(seen).send('peer', 'ctx', '回复', 'cid', quote_svr_id='751', quote_text='原消息')
        ref = seen[-1][1]['msg']['item_list'][0]['ref_msg']
        self.assertEqual(ref['svr_id'], '751')
        self.assertEqual(ref['title'], '原消息')
        self.assertEqual(ref['message_item'], {'type': 1, 'text_item': {'text': '原消息'}})

    def test_content_without_target_does_not_create_quote(self):
        seen = []
        self._client(seen).send('peer', 'ctx', '回复', 'cid', quote_text='原消息')
        self.assertNotIn('ref_msg', seen[-1][1]['msg']['item_list'][0])

    def test_rejected_quote_falls_back_to_a_plain_send(self):
        self.client.send.side_effect = [RuntimeError("bad ref"), {"message_id": "m1"}]
        self.channel._send("ctx", "你好", "cid", quote_svr_id="751062801790")
        self.assertEqual(self.client.send.call_count, 2)
        self.assertEqual(self.client.send.call_args_list[0].kwargs["quote_svr_id"], "751062801790")
        self.assertNotIn("quote_svr_id", self.client.send.call_args_list[1].kwargs)

    def test_the_fallback_is_recorded_once(self):
        self.client.send.side_effect = [RuntimeError("bad ref"), {"message_id": "m1"}]
        self.channel._send("ctx", "你好", "cid", quote_svr_id="751062801790")
        rows = (self.root / "weixin-quote-send.jsonl").read_text("utf-8").splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["svr_id"], "751062801790")

    def test_a_plain_send_failure_still_raises(self):
        self.client.send.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            self.channel._send("ctx", "你好", "cid")


class QuoteTargetTests(QuoteCase):
    def test_segmented_reply_quotes_only_first_piece(self):
        message = {'key': 'test', 'context': 'ctx', 'reply_to': '751', 'reply_text': '用户原话',
                   'quotes': [{'text': '原句'}]}
        self.channel._send_reply_part(message, '第一段', 0, lambda: False)
        self.channel._send_reply_part(message, '第二段', 1, lambda: False)
        self.assertEqual(self.client.send.call_args_list[0].kwargs['quote_svr_id'], '751')
        self.assertIsNone(self.client.send.call_args_list[1].kwargs['quote_svr_id'])
        self.assertEqual(self.client.send.call_args_list[0].kwargs['quote_text'], '用户原话')
        self.assertIsNone(self.client.send.call_args_list[1].kwargs['quote_text'])

    def test_interrupted_first_piece_does_not_send(self):
        message = {'key': 'test', 'context': 'ctx', 'reply_to': '751'}
        with self.assertRaises(InterruptedError):
            self.channel._send_reply_part(message, '第一段', 0, lambda: True)
        self.client.send.assert_not_called()

    def test_trial_flag_quotes_plain_chat_first_piece(self):
        (self.root / ALWAYS_QUOTE_FLAG).write_text('1', encoding='utf-8')
        message = {'key': 'test', 'context': 'ctx', 'reply_to': '751'}
        self.channel._send_reply_part(message, '第一段', 0, lambda: False)
        self.assertEqual(self.client.send.call_args.kwargs['quote_svr_id'], '751')

    def test_no_target_without_a_user_message_id(self):
        self.assertIsNone(self.channel._quote_target({"quotes": [{"text": "x"}]}))

    def test_mirrors_only_when_the_user_quoted(self):
        self.assertIsNone(self.channel._quote_target({"reply_to": "751"}))
        self.assertEqual(self.channel._quote_target({"reply_to": "751", "quotes": [{"text": "x"}]}), "751")

    def test_flag_file_turns_it_on_for_every_reply(self):
        (self.root / ALWAYS_QUOTE_FLAG).write_text("1", encoding="utf-8")
        self.assertEqual(self.channel._quote_target({"reply_to": "751"}), "751")


class QuoteReceiveTests(QuoteCase):
    """用户引用她的消息时，引用原文要进到本轮上下文。"""

    def test_reference_parts_label_who_was_quoted(self):
        from weixin_materials import reference_parts
        parts = reference_parts([{"role": "assistant", "text": "静香的原话"},
                                 {"role": "user", "text": "我自己的话"}])
        self.assertIn("静香先前发的", parts[0]["text"])
        self.assertIn("静香的原话", parts[0]["text"])
        self.assertIn("你先前发的", parts[1]["text"])

    def test_unknown_role_is_not_labelled_as_a_person(self):
        from weixin_materials import reference_parts
        self.assertIn("被引用的", reference_parts([{"role": "unknown", "text": "x"}])[0]["text"])

    def test_quoted_original_reaches_the_request_parts(self):
        from weixin_materials import reference_parts
        parts = [{"type": "text", "text": "这句呢"}] + reference_parts(
            [{"role": "assistant", "text": "先前那句"}])
        joined = "\n".join(p["text"] for p in parts)
        self.assertIn("这句呢", joined)
        self.assertIn("先前那句", joined)
        self.assertIn("不是本轮新指令", joined)


class QuotedTextFallbackTests(unittest.TestCase):
    """引用一条普通对话消息时，兜底不能因为 type 不是 1/2/4 就作废。

    用户实测：引用对话消息，收到的回复是「目前可以引用文字、图片和文件；
    这条引用请先转成文字或重新发附件」——而那条引用其实就是文字。
    所以兜底改成"能从 message_item 里掏出文字就用"，不看 type。
    """

    def text_of(self, item):
        from weixin_channel import WeixinChannel
        return WeixinChannel._quoted_text(item)

    def test_the_normal_text_shape_still_works(self):
        self.assertEqual(self.text_of({"type": 1, "text_item": {"text": "原文"}}), "原文")

    def test_other_types_carrying_text_are_used(self):
        for item in ({"type": 7, "text_item": {"text": "原文"}},
                     {"type": 7, "msg_item": {"text": "包了一层"}},
                     {"type": 0, "content": "另一种形状"},
                     {"type": 9, "text": "直接给字符串"},
                     {"type": 7, "card_item": {"title": "卡片标题"}}):
            self.assertTrue(self.text_of(item), item)

    def test_shapes_without_text_are_refused_so_the_user_is_asked_to_resend(self):
        for item in ({"type": 3, "voice_item": {"len": 2000}},
                     {"type": 5, "video_item": {"duration": 12}},
                     {"type": 7}):
            self.assertEqual(self.text_of(item), '', item)


class QuoteLookupFieldTests(unittest.TestCase):
    """ID 不一定在 ref 顶层——真实记录里它在 message_item.msg_id。

    用户引用她自己那条「哈？」时，ref 顶层非字典字段是空的，所有顶层 ID 都是 None，
    而 msg_id 在 ref['message_item']['msg_id'] 里，那个值在缓存里查得到。
    只看顶层就会整条引用作废（实测：这条引用落到兜底，回了"请先转成文字"）。
    """

    def setUp(self):
        from weixin_channel import WeixinChannel
        self.channel = WeixinChannel.__new__(WeixinChannel)
        self.seen = []

        class Store:
            def lookup(inner, identity):
                self.seen.append(identity)
                return {'text': '哈？', 'role': 'assistant'} if str(identity) == '7511104704740739976' else None

        self.channel.materials = Store()

    def test_id_inside_message_item_is_found(self):
        ref = {'message_item': {'type': 0, 'msg_id': '7511104704740739976'}}
        row = self.channel._quote_lookup(ref)
        self.assertIsNotNone(row, 'ID 在 message_item 里时必须查得到')
        self.assertEqual(row['text'], '哈？')

    def test_top_level_id_still_wins_first(self):
        ref = {'svr_id': '999', 'message_item': {'msg_id': '7511104704740739976'}}
        self.channel._quote_lookup(ref)
        self.assertEqual(self.seen[0], '999')

    def test_a_miss_still_returns_none(self):
        self.assertIsNone(self.channel._quote_lookup({'message_item': {'msg_id': '404'}}))


class SupersededTurnTests(unittest.TestCase):
    """被新消息取代的一轮，不该往聊天里发「本轮回复已停止。」。

    用户实测看到这句话。原因：新消息到达时 `active_progress.superseded.set()`，
    正在生成的那一轮于是返回「本轮回复已停止。」；而投递处的判断只看 /停止 的 token
    （`token.is_set()`），不看 supersede，于是这句话被当成正常回复发了出去。
    用户并没有喊停，新一轮马上会回答——这条说明纯属噪音。
    """

    def setUp(self):
        from weixin_segments import ReplyProgress
        import threading
        self.progress = ReplyProgress(lambda v: None, lambda *a: None,
                                      threading.Event(), threading.Event(), delay=False)

    def test_supersede_is_not_a_user_stop(self):
        from weixin_segments import DeliveredReply
        self.assertFalse(self.progress.interrupted())
        self.progress.superseded.set()
        self.assertTrue(self.progress.interrupted(), '被取代时必须算作中断')
        self.assertFalse(self.progress.cancel.is_set(), '但 /停止 的 token 不应被置上')
        # 投递处据此把纯文本结果换成 DeliveredReply，从而不再补发说明。
        self.assertEqual(DeliveredReply('\n\n'.join(self.progress.sent), 'interrupted').status,
                         'interrupted')

    def test_already_sent_pieces_are_preserved_in_the_record(self):
        from weixin_segments import DeliveredReply
        self.progress.sent.extend(['第一句', '第二句'])
        result = DeliveredReply('\n\n'.join(self.progress.sent), 'interrupted')
        self.assertEqual(result.text, '第一句\n\n第二句')


if __name__ == "__main__":
    unittest.main()
