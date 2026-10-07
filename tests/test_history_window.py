"""History paging, full-archive search and compact JSON storage compatibility."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from history_window import history_window,history_packets,PAGE_SIZE
from sync_bridge import atomic_json
import test_storage_history_regressions as storage_tests


class PagingTests(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(id=str(i),role='user',text='fixture-'+str(i),kind='chat') for i in range(1000)]

    def test_initial_tail_and_loading_older_preserve_order(self):
        original=deepcopy(self.rows)
        first,total=history_window(self.rows)
        self.assertEqual(total,1000)
        self.assertEqual(first,self.rows[-PAGE_SIZE:])
        older,total=history_window(self.rows,limit=PAGE_SIZE*2)
        self.assertEqual(older,self.rows[-PAGE_SIZE*2:])
        self.assertEqual(history_window(self.rows,limit=1200)[0],self.rows)
        self.assertEqual(self.rows,original)

    def test_search_covers_messages_outside_initial_page(self):
        rows,total=history_window(self.rows,' FIXTURE-1 ')
        expected=[r for r in self.rows if 'fixture-1' in r['text']]
        self.assertEqual(rows,expected)
        self.assertEqual(total,len(expected))

    def test_excludes_sources_and_summaries(self):
        self.rows += [dict(role='source',text='fixture-source'),
                      dict(role='assistant',kind='memory_summary',text='fixture-summary')]
        self.assertEqual(history_window(self.rows)[1],1000)
        self.assertEqual(history_window(self.rows,'not found'),([],0))

    def test_bridge_paging_search_and_stale_load_request(self):
        harness=storage_tests.HistoryTests();harness.setUp()
        bridge=harness.bridge
        harness.rows[:]=self.rows
        bridge.history_limit=PAGE_SIZE;bridge.history_query=''
        bridge.publish_history(force=True)
        self.assertEqual(len(harness.received),PAGE_SIZE)
        self.assertTrue(harness.packets[-1]['has_more'])
        bridge.action('history_more',dict(query=''))
        self.assertEqual(harness.received,self.rows[-600:])
        bridge.action('history_filter',dict(query='fixture-1'))
        self.assertEqual(harness.received,history_window(self.rows,'fixture-1')[0])
        count=len(harness.packets)
        bridge.action('history_more',dict(query=''))
        self.assertEqual(len(harness.packets),count)

    def test_live_append_and_old_edit_survive_page_boundary(self):
        harness=storage_tests.HistoryTests();harness.setUp()
        bridge=harness.bridge;bridge.history_limit=PAGE_SIZE;bridge.history_query=''
        harness.rows[:]=self.rows
        bridge.publish_history(force=True)
        harness.rows.append(dict(id='1000',role='assistant',text='new reply',kind='chat'))
        bridge.publish_history()
        self.assertEqual(harness.received,harness.rows[-PAGE_SIZE:])
        harness.rows[10]['text']='edited old reply'
        bridge.action('history_more',dict(query=''))
        bridge.action('history_more',dict(query=''))
        bridge.action('history_more',dict(query=''))
        self.assertEqual(harness.received,harness.rows)
        self.assertFalse(harness.packets[-1]['has_more'])

    def test_unicode_packets_stay_within_byte_limit_and_reconstruct(self):
        rows=[dict(id=str(i),role='user',text='中文'*80) for i in range(20)]
        packets=list(history_packets(rows,2,[],dict(query='',total=22,has_more=False),1200))
        self.assertGreater(len(packets),1)
        received=[dict(id='old'),dict(id='older')]
        for packet in packets:
            self.assertLessEqual(len(json.dumps(packet,ensure_ascii=False,separators=(',',':')).encode()),1200)
            received=received[:packet['offset']]+packet['rows']
        self.assertEqual(received[2:],rows)
        empty=list(history_packets([],2,[],{},1200))
        self.assertEqual(empty[0]['rows'],[])
        self.assertEqual(empty[0]['offset'],2)


class ControllerTests(unittest.TestCase):
    def test_search_discards_stale_reply_and_requests_older_page(self):
        tree=ast.parse((ROOT/'src/qt_windows.py').read_text('utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Controller')
        names=('filterHistory','loadOlderHistory','receive','_history')
        methods=[deepcopy(n) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
        for method in methods:method.decorator_list=[]
        scope={}
        exec(compile(ast.Module(body=methods,type_ignores=[]),'qt history methods','exec'),scope)
        app=SimpleNamespace(history_query='',history_mode='对话',all_history=[],notices=[],
                            history_more=False,history_total=0,history=SimpleNamespace(replace=Mock()),
                            stateChanged=SimpleNamespace(emit=Mock()),request=Mock())
        for name in names:setattr(app,name,scope[name].__get__(app))
        app.filterHistory('older','对话')
        app.request.assert_called_with('history_filter',dict(query='older'))
        app.receive(dict(type='history',query='',rows=[dict(text='stale')]))
        self.assertEqual(app.all_history,[])
        app.receive(dict(type='history',query='older',rows=[dict(text='older')],total=999,has_more=True))
        self.assertEqual(app.all_history,[dict(text='older')])
        self.assertTrue(app.history_more)
        app.loadOlderHistory()
        app.request.assert_called_with('history_more',dict(query='older'))


class CompactTests(unittest.TestCase):
    def test_compact_preserves_unicode_fields_and_reduces_file_size(self):
        rows=[dict(id=str(i),role='user',text='完整中文与换行\n内容',turn_id='wxreply:a') for i in range(100)]
        with tempfile.TemporaryDirectory() as folder:
            normal=Path(folder)/'normal.json';compact=Path(folder)/'compact.json'
            atomic_json(normal,rows);atomic_json(compact,rows,compact=True)
            self.assertEqual(json.loads(compact.read_text('utf-8')),rows)
            self.assertLess(compact.stat().st_size,normal.stat().st_size)
            original=compact.read_bytes()
            with patch('sync_bridge.os.replace',side_effect=OSError('fixture')):
                with self.assertRaises(OSError):atomic_json(compact,[],compact=True)
            self.assertEqual(compact.read_bytes(),original)
            self.assertEqual(list(Path(folder).glob('.sync-write-*.tmp')),[])


if __name__=='__main__':unittest.main()
