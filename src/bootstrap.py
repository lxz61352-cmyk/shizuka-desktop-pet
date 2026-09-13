"""Windows launcher. Uses only the standard library; preserves existing data."""
from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"
LOG = ROOT / "data" / "launcher.log"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROBE = """
import sys
assert (3, 10) <= sys.version_info[:2] <= (3, 14), 'Use Python 3.10-3.14 with Tcl/Tk'
import tkinter as tk
import PIL, pystray, openai
from PIL import Image, ImageTk
root = tk.Tk()
root.withdraw()
image = ImageTk.PhotoImage(Image.new('RGBA', (1, 1)), master=root)
print('Python:', sys.version.split()[0], 'Tk:', root.tk.call('info', 'patchlevel'))
root.destroy()
client = openai.OpenAI(api_key='local-preflight-no-network', base_url='http://127.0.0.1:1')
client.close()
from importlib.metadata import version
for name in ('pillow', 'pystray', 'openai'):
    print(name + ':', version(name))
"""


def report(message):
    print(message, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def execute(command, timeout=120):
    """Keep import and installer errors visible and in a persistent UTF-8 log."""
    try:
        result = subprocess.run(
            [str(part) for part in command], cwd=ROOT, capture_output=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report(f"[ERROR] {type(exc).__name__}: {exc}")
        return False
    if result.stdout.strip():
        report(result.stdout.strip())
    if result.stderr.strip():
        report(result.stderr.strip())
    return result.returncode == 0


def dependencies_ok():
    return PYTHON.is_file() and execute([PYTHON, "-c", PROBE], timeout=45)


def prepare_environment():
    base = Path(getattr(sys, "_base_executable", sys.executable))
    if not execute([base, "-c", "import tkinter, venv; t=tkinter.Tk(); t.withdraw(); t.destroy()"], 30):
        raise RuntimeError("Python lacks working Tcl/Tk. Install official Python 3.10-3.14 with Tcl/Tk.")
    # A working venv may be running this launcher: do not overwrite its open EXE.
    if not PYTHON.is_file() or not execute([PYTHON, "-c", "import sys, tkinter"], 30):
        report("[SETUP] Creating the local virtual environment; existing data is preserved.")
        if not execute([base, "-m", "venv", VENV], 120):
            raise RuntimeError("Could not create .venv. See launcher.log.")
    if not execute([PYTHON, "-m", "pip", "--version"], 30):
        if not execute([PYTHON, "-m", "ensurepip", "--upgrade"], 120):
            raise RuntimeError("Could not install pip into .venv.")
    requirements = ROOT / "src" / "requirements.txt"
    if sys.version_info[:2] == (3, 14):
        requirements = ROOT / "src" / "requirements-win-py314.lock"
    for index in ("https://pypi.org/simple", "https://pypi.tuna.tsinghua.edu.cn/simple"):
        report(f"[SETUP] Installing from {index}; this can take several minutes...")
        if execute([
            PYTHON, "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "--timeout", "20", "--retries", "1",
            "--index-url", index, "-r", requirements,
        ], 600):
            return
    raise RuntimeError("Dependency installation failed on both indexes. Check the network and retry.")


def launch():
    pythonw = PYTHON.with_name("pythonw.exe")
    with (ROOT / "data" / "runtime.log").open("a", encoding="utf-8") as stream:
        child = subprocess.Popen(
            [str(pythonw if pythonw.exists() else PYTHON), str(ROOT / "src" / "run_pet.py")],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
            creationflags=CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    try:
        code = child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        report(f"[OK] Desktop pet started (PID {child.pid}).")
        return
    if code:
        raise RuntimeError("Desktop pet exited during startup. See data/startup_error.log and data/runtime.log.")
    report("[OK] Desktop pet is already running, or closed normally.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate only; do not install or launch")
    parser.add_argument("--setup-only", action="store_true", help="Prepare dependencies without launching")
    args = parser.parse_args()
    report(f"\n[{datetime.datetime.now().isoformat(timespec='seconds')}] Shizuka 0.5.2 Windows launcher")
    report(f"Project: {ROOT}")
    if sys.platform != "win32":
        raise RuntimeError("This release supports Windows. macOS support is planned, not implemented yet.")
    if not dependencies_ok():
        if args.check:
            report("[ERROR] Environment check failed. Run the launcher normally to repair it.")
            return 1
        prepare_environment()
        if not dependencies_ok():
            raise RuntimeError("Dependencies installed, but the GUI/import check still failed.")
    if not execute([PYTHON, "-m", "pip", "check"], 45):
        if args.check:
            return 1
        prepare_environment()
        if not dependencies_ok() or not execute([PYTHON, "-m", "pip", "check"], 45):
            raise RuntimeError("Dependency conflicts remain. See data/launcher.log.")
    if args.check or args.setup_only:
        report("[OK] Environment is ready. No model requests were made.")
        return 0
    launch()
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception:
        report(traceback.format_exc())
        report(f"[ERROR] Startup failed. Log: {LOG}")
        raise SystemExit(1)
