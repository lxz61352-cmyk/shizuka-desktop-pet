"""Recover damaged workflow state without overwriting the only original copy."""
from copy import deepcopy
import ast
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from workflow_store import WorkflowStore


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'workflow-state.json'

    def fixture(self):
        store=WorkflowStore(self.root)
        store.notice('通知','待办',key='one',todo_id='t1')
        store.begin('focus',1500,dict(id='t1',text='事项'))
        store.checkpoint(1200);store.finish('结束')
        store.begin('break',300)
        return deepcopy(store.data)

    def test_valid_resume_preserves_remaining_without_counting_offline_time(self):
        data=self.fixture()
        with patch('workflow_store.time.time',return_value=9999999999):
            store=WorkflowStore(self.root)
        self.assertEqual(store.data,data)
        self.assertEqual(store.total('t1'),300)
        self.assertEqual(store.data['focus']['remaining'],300)
        self.assertFalse(store.load_error)
        self.assertEqual(list(self.root.glob('*.bad-*')),[])

    def test_truncated_json_wrong_root_and_invalid_utf8_are_backed_up(self):
        for raw in (b'{"notices":[',b'[]',b'null',b'\xff\xfeinvalid'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                store=WorkflowStore(self.root)
                self.assertTrue(store.load_error)
                self.assertEqual(store.recovery_path.read_bytes(),raw)
                store.notice('new','系统')
                self.assertEqual(len(WorkflowStore(self.root).notices()),1)
                self.assertEqual(store.recovery_path.read_bytes(),raw)
        self.assertIn('[workflow_state]',(self.root/'error.log').read_text('utf-8'))

    def test_partial_corruption_keeps_valid_records_and_full_original(self):
        data=self.fixture();original_notice=deepcopy(data['notices'][0])
        data['notices'] += [None,dict(id='bad',text=123),deepcopy(original_notice)]
        data['sessions'] += [dict(id='bad',elapsed='oops')]
        data['focus']['remaining']='invalid'
        self.path.write_text(json.dumps(data,ensure_ascii=False),'utf-8')
        original=self.path.read_bytes();store=WorkflowStore(self.root)
        self.assertEqual(store.notices(),[original_notice])
        self.assertEqual(store.total('t1'),300)
        self.assertIsNone(store.data['focus'])
        self.assertEqual(store.recovery_path.read_bytes(),original)
        store.notice('after recovery','系统')
        self.assertFalse(WorkflowStore(self.root).load_error)

    def test_invalid_focus_numbers_and_nested_todo_are_rejected(self):
        data=self.fixture()
        for field,value in (('remaining',-1),('remaining',301),('elapsed',float('nan')),
                            ('elapsed',float('inf')),('total',True),('total',10**400),
                            ('updated',10**300),('todo',[]),('todo',dict(id='t1',text=123))):
            with self.subTest(field=field,value=value):
                broken=deepcopy(data);broken['focus'][field]=value
                self.path.write_text(json.dumps(broken),'utf-8')
                store=WorkflowStore(self.root)
                self.assertIsNone(store.data['focus'])
                self.assertEqual(store.notices(),data['notices'])

    def test_invalid_collection_types_do_not_drop_valid_focus(self):
        data=self.fixture();focus=deepcopy(data['focus'])
        data.update(notices='bad',sessions=None)
        self.path.write_text(json.dumps(data),'utf-8')
        store=WorkflowStore(self.root)
        self.assertEqual(store.data['focus'],focus)
        self.assertEqual(store.notices(),[])
        self.assertEqual(store.data['sessions'],[])

    def test_backup_failure_blocks_disk_writes_but_memory_still_works(self):
        raw=b'{broken';self.path.write_bytes(raw)
        with patch('workflow_store.shutil.copy2',side_effect=PermissionError('fixture')):
            store=WorkflowStore(self.root)
        store.notice('in memory','系统')
        store.begin('focus',300);store.checkpoint(200);store.finish('结束')
        self.assertEqual(store.notices()[0]['text'],'in memory')
        self.assertEqual(self.path.read_bytes(),raw)
        self.assertFalse(store.save())
        self.assertIsNone(store.recovery_path)

    def test_read_failure_never_overwrites_original(self):
        raw=b'{"notices":[]}';self.path.write_bytes(raw)
        with patch.object(Path,'read_bytes',side_effect=PermissionError('fixture')):
            store=WorkflowStore(self.root)
        store.notice('in memory','系统')
        self.assertEqual(self.path.read_bytes(),raw)
        self.assertTrue(store.load_error)

    def test_save_failure_preserves_disk_and_can_retry(self):
        self.fixture();original=self.path.read_bytes();store=WorkflowStore(self.root)
        with patch('sync_bridge.os.replace',side_effect=OSError('fixture')):
            store.notice('pending','系统')
        self.assertEqual(self.path.read_bytes(),original)
        self.assertTrue(store.save_error)
        self.assertTrue(store.save())
        self.assertFalse(store.save_error)
        self.assertEqual(WorkflowStore(self.root).notices()[-1]['text'],'pending')

    def test_ui_reports_recovery_once_without_recursive_store_creation(self):
        self.path.write_bytes(b'{broken')
        source=Path(__file__).resolve().parents[1]/'src/workflow_ui.py'
        tree=ast.parse(source.read_text('utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WorkflowMixin')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_workflow')
        scope={};exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),scope)
        app=SimpleNamespace();app._workflow=scope['_workflow'].__get__(app)
        with patch.dict(sys.modules,{'pet':SimpleNamespace(DATA_DIR=self.root)}):
            store=app._workflow()
            self.assertIs(app._workflow(),store)
        self.assertEqual(len(store.notices()),1)
        self.assertEqual(store.notices()[0]['source'],'系统')
        self.assertIn('error.log',store.notices()[0]['text'])
        self.assertEqual(store.recovery_path.read_bytes(),b'{broken')


if __name__=='__main__':unittest.main()
