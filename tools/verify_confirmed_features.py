"""Release integration guard for features already accepted and deployed."""
import ast
import argparse
import json
from pathlib import Path
import types

ROOT=Path(__file__).resolve().parents[1]


def verify_source():
    required={
        'pet.py':('_set_icon_hitbox','_poll_ui','_save_settings'),
        'background_tasks.py':('put_until_cancelled',),
        'history_window.py':('history_window','history_packets'),
        'workflow_store.py':('_validated',),
        'habit_reminders.py':('_water_tick',),
        'habit_settings.py':('water_controls','desktop_controls'),
    }
    for filename,names in required.items():
        path=ROOT/'src'/filename
        if not path.is_file():raise RuntimeError('Confirmed feature module missing: '+filename)
        tree=ast.parse(path.read_text('utf-8-sig'))
        functions={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        missing=set(names)-functions
        if missing:raise RuntimeError('Confirmed feature entry missing: '+filename+' '+str(sorted(missing)))
    tree=ast.parse((ROOT/'src/pet.py').read_text('utf-8-sig'))
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_create_icon_button'
               and any(k.arg=='fill_hitbox' and isinstance(k.value,ast.Constant) and k.value.value is True for k in n.keywords)
               for n in ast.walk(tree)), 'Confirmed todo fix is not wired to the real button'
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DeskPet')
    functions={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    def called(node,name):
        return any(isinstance(n,ast.Call) and ((isinstance(n.func,ast.Name) and n.func.id==name)
                   or (isinstance(n.func,ast.Attribute) and n.func.attr==name)) for n in ast.walk(node))
    assert called(functions['_save_settings'],'atomic_json'), 'Atomic settings save absent'
    assert any(isinstance(n,ast.For) for n in ast.walk(functions['_poll_ui'])), 'Bounded UI dispatch absent'
    assert called(functions['_tts_producer'],'put_until_cancelled'), 'Cancellable background handoff absent'
    bridge=ast.parse((ROOT/'src/qt_window_bridge.py').read_text('utf-8-sig'))
    assert called(bridge,'history_window') and called(bridge,'history_packets'), 'History projection/chunking absent'


def normalized(code):
    return code.replace(co_filename='<source>',co_consts=tuple(normalized(c) if isinstance(c,types.CodeType) else c for c in code.co_consts))


def verify_bundle(exe):
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(exe)).open_embedded_archive('PYZ.pyz')
    verified=[];mismatches=[]
    for source in sorted((ROOT/'src').glob('*.py')):
        try:packed=archive.extract(source.stem)
        except KeyError:continue
        compiled=compile(source.read_bytes(),str(source),'exec',optimize=0)
        if normalized(packed)!=normalized(compiled):mismatches.append(source.name)
        verified.append(source.name)
    required={'pet.py','background_tasks.py','history_window.py','habit_reminders.py','habit_settings.py','proactive_controls.py'}
    missing=required-set(verified)
    if mismatches or missing:raise RuntimeError('Executable/source mismatch: '+str(mismatches)+'; missing: '+str(sorted(missing)))
    return dict(verified_modules=verified,mismatches=mismatches)


def verify_qt_bundle(exe):
    """The window process also embeds shared application dependencies."""
    import marshal
    from PyInstaller.archive.readers import CArchiveReader
    exe=Path(exe);outer=CArchiveReader(str(exe));archive=outer.open_embedded_archive('PYZ.pyz')
    verified=[];mismatches=[]
    for source in sorted((ROOT/'src').glob('*.py')):
        try:packed=archive.extract(source.stem)
        except KeyError:continue
        verified.append(source.name)
        if normalized(packed)!=normalized(compile(source.read_bytes(),'<source>','exec',optimize=0)):mismatches.append(source.name)
    if normalized(marshal.loads(outer.extract('qt_windows')))!=normalized(compile((ROOT/'src/qt_windows.py').read_bytes(),'<source>','exec',optimize=0)):
        mismatches.append('qt_windows.py')
    for source in (ROOT/'src').glob('Qt*.qml'):
        packed=exe.parent/'_internal'/source.name
        if not packed.is_file() or source.read_text('utf-8-sig')!=packed.read_text('utf-8-sig'):mismatches.append(source.name)
    required={'qt_form_models.py','qt_form_dialogs.py','todo_editing.py','todo_model.py','todo_schedule.py'}
    missing=required-set(verified)
    if mismatches or missing:raise RuntimeError('Qt executable/source mismatch: '+str(mismatches)+'; missing: '+str(sorted(missing)))
    return dict(verified_modules=verified,mismatches=mismatches)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args();verify_source()
    result=verify_bundle(args.exe) if args.exe else {'confirmed_feature_wiring':'passed'}
    if args.report:args.report.write_text(json.dumps(result,indent=2),'utf-8')
    print('Confirmed feature guard passed; bundled modules:',len(result.get('verified_modules',[])))
