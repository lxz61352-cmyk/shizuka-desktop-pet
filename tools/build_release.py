"""Build a clean, portable Windows share folder. Never copy local runtime data."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
VERSION="0.6.0"
BUILD=ROOT/"build"/"v060"
RELEASE=ROOT/"releases"/f"Shizuka-{VERSION}-Windows-x64"
IGNORED={"__pycache__",".venv","node_modules",".git","data"}
SENSITIVE={"api_key.txt","settings.json","memory.json","todos.json","runtime.log","error.log","startup_error.log",
           "_dizzy.wav","_tts.wav","_tts_warm.wav"}
# 运行时生成的语音临时/预制音频一律不进包（_tts_p0..7.wav 等）
def _is_private(relative, file):
    name=file.name
    return (name in SENSITIVE or name.startswith("_tts") or name.startswith("_dizzy")
            or any(part in IGNORED for part in relative.parts))


def copy_tree(source,target):
    for file in sorted(source.rglob("*")):
        relative=file.relative_to(source)
        if file.is_file() and not _is_private(relative,file):
            dest=target/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(file,dest)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--reuse-build",action="store_true")
    args=parser.parse_args()
    if RELEASE.exists():
        raise SystemExit(f"Release already exists; inspect it before rebuilding: {RELEASE}")
    BUILD.mkdir(parents=True,exist_ok=True)
    if not args.reuse_build:
        command=[sys.executable,"-m","PyInstaller","--noconfirm","--windowed","--onedir",
            "--name","Shizuka","--icon",str(ROOT/"assets/pet_icon.ico"),
            "--paths",str(ROOT/"src"),"--paths",str(ROOT/"tools"),
            "--hidden-import","pystray._win32","--collect-all","openai",
            "--copy-metadata","pystray","--distpath",str(BUILD/"dist"),
            "--workpath",str(BUILD/"work"),"--specpath",str(BUILD),str(ROOT/"src/run_pet.py")]
        with (BUILD/"pyinstaller.log").open("w",encoding="utf-8") as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    shutil.copytree(BUILD/"dist/Shizuka",RELEASE)
    for name in ("src","tools","tests","assets","persona","characters","experiments","references","docs"):
        copy_tree(ROOT/name,RELEASE/name)
    # Public docs are written for this release, not copied from local project notes.
    shutil.copy2(ROOT/"README.md",RELEASE/"README.md")
    (RELEASE/"启动桌宠.bat").write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0Shizuka.exe"\r\n',encoding="ascii",newline="")
    (RELEASE/"预览动作.bat").write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0Shizuka.exe" --preview\r\n',encoding="ascii",newline="")
    # A clean source launcher remains available for developers with Python.
    shutil.copy2(ROOT/"启动桌宠.bat",RELEASE/"源码启动.bat")
    licenses=RELEASE/"LICENSES";licenses.mkdir()
    python_license=Path(sys.base_prefix)/"LICENSE.txt"
    if python_license.exists():shutil.copy2(python_license,licenses/"Python-LICENSE.txt")
    versions={}
    for dist in metadata.distributions():
        name=dist.metadata.get("Name","")
        versions[name]=dist.version
        for path in dist.files or []:
            if any(word in path.name.lower() for word in ("license","copying","notice")) and path.suffix.lower() in (".txt",".md",""):
                original=dist.locate_file(path)
                if original.is_file():
                    target=licenses/re.sub(r"[^a-zA-Z0-9_.-]","_",name)/path.name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(original,target)
    versions["Python"]=sys.version.split()[0]
    (licenses/"build-versions.json").write_text(json.dumps(versions,indent=2)+"\n",encoding="utf-8")
    issues=[]
    for file in RELEASE.rglob("*"):
        if not file.is_file():continue
        relative=file.relative_to(RELEASE)
        if _is_private(relative,file):
            issues.append(str(relative))
        if (file.suffix.lower() in (".py",".md",".txt",".json",".bat",".log",".ini",".cfg",".yaml",".yml",".toml","")
                and file.stat().st_size < 2_000_000):
            data=file.read_bytes()
            if re.search(rb"sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{16,}",data):
                issues.append("Possible credential in "+str(relative))
    if issues:raise RuntimeError("Release audit failed: "+", ".join(issues))
    print(json.dumps(dict(release=str(RELEASE),files=sum(p.is_file() for p in RELEASE.rglob("*")),version=VERSION),ensure_ascii=False))


if __name__=="__main__":main()
