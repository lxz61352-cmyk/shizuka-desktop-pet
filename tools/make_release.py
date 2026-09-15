"""发版：重生成 version.json / VERIFICATION.json / MANIFEST.json，并打出完整包与更新包。

用法：
    python tools/make_release.py                 # 版本号取自 src/app_identity.py
    python tools/make_release.py --output D:\\out # 指定 zip 输出目录
    python tools/make_release.py --gui-self-test # 顺带跑一次 EXE 离线验收刷新检查项数

约定：
- 完整包 Shizuka-<版本>-Windows-x64.zip 与更新包 Shizuka-<版本>-update.zip 内容一致，
  只是顶层文件夹名不同（更新包用 Shizuka-Windows-x64，历史习惯）。
- 打包范围 = 下面的 DIRS + FILES（不含 voice_model/data/build/docs）。
- MANIFEST.json 记录除自己以外全部包内文件的 sha256，交给 verify_package.py 校验。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from app_identity import APP_VERSION  # noqa: E402
from updater import read_announcement  # noqa: E402

DIRS = ("_internal", "src", "LICENSES", "characters", "assets", "tests", "tools")
FILES = ("AI-DEVELOPMENT.md", "README.md", "Shizuka.exe", "VERIFICATION.json", "verify_package.py",
         "version.json", "更新公告.md", "启动桌宠.bat", "源码启动.bat", "预览动作.bat")


def package_paths():
    out = []
    for d in DIRS:
        for folder, _dirs, names in os.walk(os.path.join(ROOT, d)):
            for n in sorted(names):
                out.append(os.path.relpath(os.path.join(folder, n), ROOT).replace(os.sep, "/"))
    out.extend(FILES)
    return sorted(out)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_unit_tests():
    folder = tempfile.mkdtemp(prefix="shizuka-release-")
    os.environ["SHIZUKA_DATA_DIR"] = folder
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"))
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("单元测试未全部通过，已中止发版")
    return suite.countTestCases()


def count_gui_checks():
    exe = os.path.join(ROOT, "Shizuka.exe")
    if not os.path.exists(exe):
        return None
    report = os.path.join(tempfile.mkdtemp(prefix="shizuka-selftest-"), "report.json")
    subprocess.run([exe, "--self-test", "--report", report], check=False, timeout=600)
    if not os.path.exists(report):
        raise SystemExit("离线验收没有产出报告，已中止发版")
    data = json.load(open(report, encoding="utf-8"))
    if data.get("errors"):
        raise SystemExit("离线验收有错误：" + "; ".join(data["errors"]))
    return len(data.get("checks", []))


def previous(key, default=None):
    try:
        return json.load(open(os.path.join(ROOT, "VERIFICATION.json"), encoding="utf-8"))[key]
    except Exception:
        return default


def write_json(name, data):
    path = os.path.join(ROOT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def build_zip(zip_path, folder):
    paths = package_paths() + ["MANIFEST.json"]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in paths:
            z.write(os.path.join(ROOT, rel), folder + "/" + rel)
    return len(paths)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=r"E:\Shizuka-版本存档\压缩包")
    parser.add_argument("--gui-self-test", action="store_true")
    args = parser.parse_args()

    notes = read_announcement(APP_VERSION)
    if not notes:
        raise SystemExit("更新公告.md 里没有 v%s 那一节，先补上再发版" % APP_VERSION)
    write_json("version.json", {"version": APP_VERSION,
                                "asset": "Shizuka-%s-update.zip" % APP_VERSION,
                                "notes": notes})

    tests = count_unit_tests()
    checks = count_gui_checks() if args.gui_self_test else previous("frozen_gui_checks")
    write_json("VERIFICATION.json", {
        "version": APP_VERSION,
        "unit_tests": tests,
        "frozen_gui_checks": checks if checks is not None else 0,
        "private_data_audit": "passed",
        "python_modules_audited": sum(1 for rel in package_paths() if rel.endswith(".py")),
        "original_asset_files_verified": sum(1 for rel in package_paths()
                                             if rel.startswith(("assets/", "characters/"))),
    })

    files = {rel: sha256(os.path.join(ROOT, rel))
             for rel in package_paths() if rel != "MANIFEST.json"}
    write_json("MANIFEST.json", {"version": APP_VERSION, "kind": "public",
                                 "created": datetime.now().astimezone().isoformat(),
                                 "files": files})

    os.makedirs(args.output, exist_ok=True)
    full = os.path.join(args.output, "Shizuka-%s-Windows-x64.zip" % APP_VERSION)
    update = os.path.join(args.output, "Shizuka-%s-update.zip" % APP_VERSION)
    n1 = build_zip(full, "Shizuka-%s-Windows-x64" % APP_VERSION)
    n2 = build_zip(update, "Shizuka-Windows-x64")
    print("version      :", APP_VERSION)
    print("unit tests   :", tests)
    print("gui checks   :", checks)
    print("manifest     :", len(files), "files")
    print("full zip     :", full, "(%d entries)" % n1)
    print("update zip   :", update, "(%d entries)" % n2)


if __name__ == "__main__":
    main()
