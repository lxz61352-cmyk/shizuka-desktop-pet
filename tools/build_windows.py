"""Rebuild the Windows executable from the included source."""
from pathlib import Path
import argparse,shutil,subprocess,sys
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=root/'build')
args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--onedir','--name','Shizuka',
 '--icon',str(root/'assets/pet_icon.ico'),'--paths',str(root/'src'),'--hidden-import','pystray._win32',
 '--collect-all','openai','--copy-metadata','pystray','--distpath',str(out/'dist'),'--workpath',str(out/'work'),
 '--specpath',str(out),str(root/'src/run_pet.py')]
with (out/'pyinstaller.log').open('w',encoding='utf-8') as log:
    subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
bundle=out/'dist/Shizuka'
shutil.copytree(bundle/'_internal',root/'_internal',dirs_exist_ok=True)
shutil.copy2(bundle/'Shizuka.exe',root/'Shizuka.exe')
print('Build complete')
