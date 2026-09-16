"""GitHub Release 检查、更新公告读取、更新包下载与覆盖安装（不含界面）。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from app_identity import APP_VERSION

UPDATE_REPO = "lxz61352-cmyk/shizuka-desktop-pet"   # GitHub 仓库（owner/repo）
UPDATE_API = "https://api.github.com/repos/%s/releases/latest" % UPDATE_REPO
# 直连被墙时的备用源（国内可通的 GitHub 镜像；用于读 version.json 和下载更新包）
# 按实测下载速度排序：gh-proxy.com 最快，ghfast.top 最慢放最后
UPDATE_MIRRORS = ["https://gh-proxy.com/", "https://ghproxy.net/",
                  "https://gh.ddlc.top/", "https://ghfast.top/"]
UPDATE_API_TIMEOUT = 4      # 直连 GitHub API 的等待上限（连不上就立刻转镜像）
UPDATE_MIRROR_TIMEOUT = 6   # 镜像读 version.json 的等待上限
UPDATE_DIRECT_TIMEOUT = 6   # 直连下载更新包的等待上限（连不上就转镜像）
VERSION_JSON_URL = "https://raw.githubusercontent.com/%s/main/version.json" % UPDATE_REPO

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(APP_DIR)
DATA_DIR = os.environ.get("SHIZUKA_DATA_DIR") or os.path.join(ROOT_DIR, "data")
PENDING_UPDATE_FILE = os.path.join(DATA_DIR, "_pending_update.json")   # 更新重启后要展示的更新日志
ANNOUNCE_FILE = os.path.join(ROOT_DIR, "更新公告.md")                    # 更新公告（按 ## vX.Y.Z 分节）


def version_tuple(s):
    out = []
    for p in re.split(r"[.\-+]", (s or "").strip().lstrip("vV")):
        m = re.match(r"\d+", p)
        out.append(int(m.group()) if m else 0)
    return tuple(out) if out else (0,)


def check_latest_release(timeout=None):
    """返回 (是否有更新, 最新版本号, 下载地址, 更新说明)。失败返回 (False, '', '', '')。
    直连 GitHub API 只等很短时间（连不上立刻转镜像），避免卡住。"""
    api_timeout = timeout or UPDATE_API_TIMEOUT
    mirror_timeout = timeout or UPDATE_MIRROR_TIMEOUT
    try:
        req = urllib.request.Request(UPDATE_API, headers={
            "User-Agent": "ShizukaDeskPet", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=api_timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        tag = (data.get("tag_name") or data.get("name") or "").strip()
        notes = (data.get("body") or "").strip()
        zips = [a for a in (data.get("assets") or [])
                if (a.get("name") or "").lower().endswith(".zip")]
        url = ""
        for a in zips:
            if "update" in (a.get("name") or "").lower():
                url = a.get("browser_download_url") or ""
                break
        if not url and zips:
            url = zips[0].get("browser_download_url") or ""
        return (version_tuple(tag) > version_tuple(APP_VERSION), tag.lstrip("vV"), url, notes)
    except Exception:
        pass
    # 2) 备用源：镜像读 version.json（{"version","asset","notes"}）
    for m in UPDATE_MIRRORS:
        try:
            req = urllib.request.Request(m + VERSION_JSON_URL, headers={"User-Agent": "ShizukaDeskPet"})
            with urllib.request.urlopen(req, timeout=mirror_timeout) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
            ver = (d.get("version") or "").strip().lstrip("vV")
            asset = (d.get("asset") or "").strip()
            if not ver or not asset:
                continue
            url = "%shttps://github.com/%s/releases/download/v%s/%s" % (m, UPDATE_REPO, ver, asset)
            return (version_tuple(ver) > version_tuple(APP_VERSION), ver, url, (d.get("notes") or "").strip())
        except Exception:
            continue
    return (False, "", "", "")


def read_announcement(ver):
    """从「更新公告.md」里取指定版本号那一节的正文。找不到返回空串。"""
    try:
        if not ver or not os.path.exists(ANNOUNCE_FILE):
            return ""
        with open(ANNOUNCE_FILE, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        want = str(ver).strip().lstrip("vV")
        body = []
        cur = False
        for ln in lines:
            m = re.match(r"^#{1,6}\s*(.+?)\s*$", ln.strip())
            if m:
                if cur:
                    break            # 到了下一节，结束
                title = m.group(1).lstrip("vV").strip()
                if want and (title == want or want in title or title in want):
                    cur = True
                continue
            if cur:
                body.append(ln)
        return "\n".join(body).strip()
    except Exception:
        return ""


def download_package(url, on_progress=None, on_note=None):
    """下载并解压更新包，返回 (临时目录, 含 Shizuka.exe 的目录)。失败抛异常。"""
    tmp = tempfile.mkdtemp(prefix="shizuka_upd_")
    zpath = os.path.join(tmp, "update.zip")
    # 直连只试一次、等待很短；连不上立刻转镜像，不再反复等
    direct_url = url
    for m in UPDATE_MIRRORS:
        if url.startswith(m):
            direct_url = url[len(m):]
            break
    cands = []
    if direct_url.startswith(("https://github.com/", "http://github.com/")):
        cands.append((direct_url, UPDATE_DIRECT_TIMEOUT))
        for m in UPDATE_MIRRORS:
            cands.append((m + direct_url, 30))
    else:
        cands.append((url, 30))
    ok = False
    last_err = None
    for idx, (u, tmo) in enumerate(cands):
        try:
            if idx == 1 and on_note:
                on_note("直连较慢，已自动切换镜像…")
            req = urllib.request.Request(u, headers={"User-Agent": "ShizukaDeskPet"})
            with urllib.request.urlopen(req, timeout=tmo) as r:
                try:
                    total = int(r.headers.get("Content-Length") or 0)
                except Exception:
                    total = 0
                done = 0
                with open(zpath, "wb") as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)
            ok = True
            break
        except Exception as e:
            last_err = e
            continue
    if not ok:
        raise last_err or RuntimeError("下载失败")
    if on_progress:
        on_progress(1, 1, True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    src = None
    for root, dirs, files in os.walk(tmp):
        if "Shizuka.exe" in files:
            src = root
            break
    if not src:
        raise RuntimeError("压缩包里没找到 Shizuka.exe")
    return tmp, src


def write_pending_update(ver, notes):
    """记下更新日志，重启后弹一次。"""
    try:
        with open(PENDING_UPDATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": ver, "notes": notes}, f, ensure_ascii=False)
    except Exception:
        pass


def read_pending_update():
    """读取并删除待展示的更新日志；没有则返回 None。"""
    try:
        if not os.path.exists(PENDING_UPDATE_FILE):
            return None
        with open(PENDING_UPDATE_FILE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        try:
            os.remove(PENDING_UPDATE_FILE)
        except Exception:
            pass
        return d
    except Exception:
        return None


def launch_swap(src_dir, tmp_dir, restart_cmd, pid=None):
    """写一个等待本进程退出的 bat：robocopy 覆盖到安装目录，然后重启并清理临时目录。
    保留 data / voice_model / experiments 和 api_key.txt，避免覆盖用户数据。"""
    pid = os.getpid() if pid is None else pid

    def esc(value):
        # bat 里 % 会被当变量展开，引号挡不住它；路径里带 % 会把整行搞坏。
        return str(value).replace("%", "%%")

    bat = os.path.join(tmp_dir, "_update.bat")
    with open(bat, "w", encoding="gbk", errors="ignore") as f:
        f.write("@echo off\r\n")
        f.write(":wait\r\n")
        f.write('tasklist /FI "PID eq %d" | find "%d" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)\r\n' % (pid, pid))
        f.write('robocopy "%s" "%s" /E /XD data voice_model experiments /XF api_key.txt /R:2 /W:1 >nul\r\n'
                % (esc(src_dir), esc(ROOT_DIR)))
        f.write('start "" %s\r\n' % esc(restart_cmd))
        f.write('rmdir /S /Q "%s"\r\n' % esc(tmp_dir))
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000, close_fds=True)
