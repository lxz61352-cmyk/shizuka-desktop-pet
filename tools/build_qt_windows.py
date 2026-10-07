"""Build the private Qt Quick runtime for the application's tool windows."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,default=root/'build/qt-windows')
args=parser.parse_args()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--console','--onedir',
    '--name','ShizukaWindows','--icon',str(root/'assets/pet_icon.ico'),
    '--paths',str(root/'src'),
    '--hidden-import','PySide6.QtQuickControls2','--hidden-import','qt_windows_test',
    '--distpath',str(out/'dist'),'--workpath',str(out/'work'),
    '--specpath',str(out)]
for qml in sorted((root/'src').glob('Qt*.qml')):
    command+=['--add-data',str(qml)+';.']
command.append(str(root/'src/qt_windows.py'))
with (out/'pyinstaller.log').open('w',encoding='utf-8') as log:
    env=os.environ.copy()
    # Qt uses the Windows ICU API. Prefer System32 during dependency scanning;
    # unrelated tools can have a same-named, incompatible ICU DLL on PATH.
    env['PATH']=str(Path(env.get('SystemRoot',r'C:\Windows'))/'System32')+os.pathsep+env.get('PATH','')
    subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
from verify_confirmed_features import verify_qt_bundle
import json
executable=out/'dist/ShizukaWindows/ShizukaWindows.exe'
(out/'source-archive-audit.json').write_text(json.dumps(verify_qt_bundle(executable),indent=2),'utf-8')
print('Qt windows built:',executable)
