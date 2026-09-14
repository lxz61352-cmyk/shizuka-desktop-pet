# -*- coding: utf-8 -*-
"""生成「更新包」zip：只含程序本体，排除 voice_model（音色大模型）、data（用户数据）、experiments。
用于挂到 GitHub Release 的附件，供程序内「自动更新」下载——这样更新时不会重下 328MB 模型，也不会覆盖用户数据。

用法：在程序目录（含 Shizuka.exe）下运行  python tools/make_update_zip.py
输出：程序目录的上一级生成 Shizuka-<版本>-update.zip
"""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = os.path.basename(ROOT)
EXCLUDE_DIRS = {"voice_model", "data", "experiments", ".git", "__pycache__",
                "build", "releases", ".venv", "venv"}
EXCLUDE_FILES = {"api_key.txt"}

ver = "0.0.0"
try:
    with open(os.path.join(ROOT, "src", "pet.py"), encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
        if m:
            ver = m.group(1)
except Exception:
    pass
OUT = os.path.join(os.path.dirname(ROOT), "Shizuka-%s-update.zip" % ver)

if os.path.exists(OUT):
    os.remove(OUT)

n = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS]
        for f in fn:
            if f in EXCLUDE_FILES or f.endswith((".pyc", ".log")):
                continue
            # 只排除「根目录下的打包产物」（别把 zip 打进 zip）；
            # _internal 里的 base_library.zip 是 PyInstaller 必需的，必须保留。
            if f.lower().endswith(".zip") and os.path.normpath(dp) == os.path.normpath(ROOT):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, os.path.dirname(ROOT))
            z.write(full, rel)
            n += 1

print("files:", n)
print("zip MB:", round(os.path.getsize(OUT) / 1024 / 1024, 1))
print("OUT:", OUT)

# 同步写 version.json（给「备用源/镜像」用：程序直连不上 GitHub API 时读它）
def _announcement(v):
    try:
        with open(os.path.join(ROOT, "更新公告.md"), encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        body, cur = [], False
        for ln in lines:
            m = re.match(r"^#{1,6}\s*(.+?)\s*$", ln.strip())
            if m:
                if cur:
                    break
                if m.group(1).lstrip("vV").strip() == v:
                    cur = True
                continue
            if cur:
                body.append(ln)
        return "\n".join(body).strip()
    except Exception:
        return ""

verjson = os.path.join(ROOT, "version.json")
with open(verjson, "w", encoding="utf-8") as f:
    json.dump({"version": ver, "asset": os.path.basename(OUT), "notes": _announcement(ver)},
              f, ensure_ascii=False, indent=2)
print("version.json:", verjson)
