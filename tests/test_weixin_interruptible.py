import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from weixin_segments import interruptible_chunks,generate,ReplyProgress


class InterruptTests(unittest.TestCase):
    def test_cancel_while_opening_stream(self):
        entered=threading.Event();release=threading.Event();cancel=threading.Event();finished=threading.Event()
        def create():
            entered.set();release.wait(3)
            return Stream([])
        values=[]
        def run():
            values.extend(interruptible_chunks(create,cancel.is_set));finished.set()
        thread=threading.Thread(target=run);thread.start()
        self.assertTrue(entered.wait(1));cancel.set()
        try:self.assertTrue(finished.wait(.5));self.assertEqual(values,[])
        finally:release.set();thread.join(1)

    def test_cancel_while_waiting_chunk_no_stale_send(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        cancel=threading.Event();progress=ReplyProgress(lambda x:None,lambda *x:self.fail('stale send'),cancel,threading.Event(),delay=False)
        class Slow(Stream):
            def __iter__(self):
                entered.set();release.wait(3)
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='旧回复'))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:Slow([]))))
        result=[]
        def run():
            result.append(generate(client,{'messages':[{'role':'system','content':'原风格'},{'role':'user','content':'第一句'}]},progress,lambda x:x,lambda x:None));finished.set()
        thread=threading.Thread(target=run);thread.start()
        self.assertTrue(entered.wait(1));progress.superseded.set()
        try:
            self.assertTrue(finished.wait(.5))
            self.assertEqual(result[0].status,'interrupted')
            self.assertEqual(result[0].text,'')
        finally:release.set();thread.join(1)

    def test_normal_order_and_errors(self):
        self.assertEqual(list(interruptible_chunks(lambda:Stream([1,2,3]),lambda:False)),[1,2,3])
        def fail():raise ValueError('failed')
        with self.assertRaises(ValueError):list(interruptible_chunks(fail,lambda:False))

    def test_cancel_before_request(self):
        def create():self.fail('request started')
        self.assertEqual(list(interruptible_chunks(create,lambda:True)),[])


class Stream:
    def __init__(self,values):self.values=values
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def __iter__(self):return iter(self.values)
