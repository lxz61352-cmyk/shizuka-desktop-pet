"""Rebuild the Windows executable from the included source."""
from pathlib import Path
import argparse,shutil,subprocess,sys
root=Path(__file__).resolve().parents[1]
# 模块旁边读的数据文件必须打进包里。enhanced_dialogue.py 用
#   HARD_CONTRACT_FILE = Path(__file__).resolve().parent / "enhanced_hard_contract_v2.txt"
# 在冻结包里 __file__ 落在 _internal/，所以这个文件要放到 _internal 根下。
# 漏打的时候程序不会立刻报错——旧 _internal 里残留的历史文件会顶上，
# 直到有人清空 _internal 重新部署才会暴露（2026-10-01 就是这样发现的）。
DATA_FILES=['src/enhanced_hard_contract_v2.txt']
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=root/'build')
parser.add_argument('--no-deploy',action='store_true',help='Build and validate the bundle without replacing the installed runtime')
args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--onedir','--name','Shizuka',
 '--icon',str(root/'assets/pet_icon.ico'),'--paths',str(root/'src'),'--hidden-import','pystray._win32',
 # 下面这些是在函数内部懒加载的，PyInstaller 的静态分析会漏掉——
 # 漏了不会报错，只是冻结版里 import 失败，被调用处的 except 吞掉（2026-10-02 实测踩到）。
 '--hidden-import','slash_commands','--hidden-import','anthropic_call',
 '--hidden-import','search_decide','--hidden-import','reply_turn',
 '--hidden-import','web_search','--hidden-import','runtime_affect_event_lab',
 '--hidden-import','runtime_pre_reply_affect','--hidden-import','runtime_affect_lab',
 '--collect-all','openai','--copy-metadata','pystray']
for item in DATA_FILES:
    source=root/item
    if not source.is_file():
        raise SystemExit('Missing packaged data file: '+item)
    command+=['--add-data',str(source)+';.']
command+=['--distpath',str(out/'dist'),'--workpath',str(out/'work'),'--specpath',str(out),str(root/'src/run_pet.py')]
with (out/'pyinstaller.log').open('w',encoding='utf-8') as log:
    subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
bundle=out/'dist/Shizuka'
for item in DATA_FILES:
    if not (bundle/'_internal'/Path(item).name).is_file():
        raise SystemExit('Packaged data file missing from build: '+item)
# copytree(dirs_exist_ok) 只覆盖不删除；旧构建的残留文件会留在 _internal 里。
# 要保证部署树与构建树一致就整个换掉，所以先删干净。
if args.no_deploy:
    print('Build complete (not deployed):',bundle)
    raise SystemExit(0)
stale=root/'_internal'
if stale.resolve().parent != root.resolve() or stale.is_symlink():
    raise SystemExit('Refusing to replace runtime outside the workspace')
if stale.exists():
    shutil.rmtree(stale)
shutil.copytree(bundle/'_internal',stale)
shutil.copy2(bundle/'Shizuka.exe',root/'Shizuka.exe')
print('Build complete')
