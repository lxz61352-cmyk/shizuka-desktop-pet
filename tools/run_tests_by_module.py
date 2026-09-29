"""Diagnostic fallback runner: each test module in its own process.

Use when tools/run_tests.py dies mid-run without statistics (e.g. Tk teardown
from another thread). Business tests are never skipped; failed modules are
reported individually.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _run_single(pattern):
    import unittest
    os.environ["SHIZUKA_DIALOGUE_PROFILE"] = "legacy"
    sys.path.insert(0, str(ROOT / "src"))
    result = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.discover(str(TESTS), pattern=pattern))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)


def _run_in_child(pattern):
    with tempfile.TemporaryDirectory(prefix="shizuka-unit-module-") as folder:
        env = dict(os.environ)
        env["SHIZUKA_DATA_DIR"] = folder
        env["SHIZUKA_DIALOGUE_PROFILE"] = "legacy"
        proc = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--one", pattern],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
    match = re.search(r"Ran (\d+) tests?", proc.stdout or "")
    count = int(match.group(1)) if match else 0
    ok = proc.returncode == 0 and bool(re.search(r"(?m)^OK\b", proc.stdout or ""))
    return count, ok, proc.stdout or ""


def main():
    if "--one" in sys.argv:
        _run_single(sys.argv[sys.argv.index("--one") + 1])
        return 0
    modules = sorted(TESTS.glob("test_*.py"))
    total = 0
    failed = []
    for path in modules:
        count, ok, output = _run_in_child(path.name)
        total += count
        if ok:
            print("ok   %-38s ran=%d" % (path.name, count))
        else:
            tail = "\n".join(output.strip().splitlines()[-12:])
            print("FAIL %-38s ran=%d\n%s" % (path.name, count, tail))
            failed.append(path.name)
    print("-" * 64)
    if failed:
        print("FAILED modules: " + ", ".join(failed))
        return 1
    print("Ran %d tests across %d modules — OK" % (total, len(modules)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
