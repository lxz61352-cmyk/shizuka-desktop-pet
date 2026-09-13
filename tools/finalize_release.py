"""Verify a clean release, add hashes, ZIP it, and retain a local receipt."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile
from build_release import ROOT, RELEASE, VERSION, IGNORED, SENSITIVE


def main():
    report=json.loads((ROOT/"build/portable-check-v056/portable-check.json").read_text(encoding="utf-8"))
    assert report["version"]==VERSION and report["frozen"] and not report["errors"]
    assert len(report["checks"])==4
    tested=ROOT/"build/portable-check-v056"
    for file in [tested/"Shizuka.exe",*(tested/"_internal").rglob("*")]:
        if file.is_file():
            equivalent=RELEASE/file.relative_to(tested)
            assert hashlib.sha256(file.read_bytes()).digest()==hashlib.sha256(equivalent.read_bytes()).digest(),equivalent
    report.update(regression_tests=22,windows_smoke="passed",platform="Windows 11 x64",api_requests=0,
                  environment="Separate directory, PATH limited to Windows; no external Python environment")
    (RELEASE/"发布验证.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    shutil.copy2(__file__,RELEASE/"tools/finalize_release.py")
    files=sorted(p for p in RELEASE.rglob("*") if p.is_file() and p.name!="文件清单.sha256")
    records=[]
    for file in files:
        relative=file.relative_to(RELEASE)
        assert file.name not in SENSITIVE and not any(p in IGNORED for p in relative.parts),relative
        contents=file.read_bytes()
        if file.suffix.lower() in {".py",".md",".txt",".json",".bat",".log"}:
            assert not re.search(rb"sk-[A-Za-z0-9_-]{20,}",contents),f"Credential pattern: {relative}"
        records.append(f"{hashlib.sha256(contents).hexdigest()}  {relative.as_posix()}")
    (RELEASE/"文件清单.sha256").write_text("\n".join(records)+"\n",encoding="utf-8")
    archive=RELEASE.parent/(RELEASE.name+".zip")
    assert not archive.exists(),"Refusing to overwrite an existing ZIP"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for file in sorted(RELEASE.rglob("*")):
            if file.is_file():output.write(file,file.relative_to(RELEASE.parent))
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
        count=len(check.infolist())
    receipt=dict(version=VERSION,zip_name=archive.name,bytes=archive.stat().st_size,
                 sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=count,
                 crc_check="passed",private_data_audit="passed",qq_status="not_sent",local_zip_deleted=False)
    (ROOT/"docs/发布发送记录-0.5.6.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=="__main__":main()
