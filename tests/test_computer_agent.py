"""Real subprocess tests with a tiny fake runner; no model/network/credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from computer_agent import ComputerAgent, DshInstallation, load_config, save_config, task_prompt, validate_workspace
from computer_ui import computer_command


class Runner:
    def __init__(self, script):
        self.script = script

    def command(self, task):
        return [sys.executable, str(self.script), task]


class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / "files"
        self.workspace.mkdir()
        self.config = {"enabled": True, "workspace": str(self.workspace), "timeout_seconds": 60}

    def tearDown(self):
        # Windows can briefly retain the inherited log handle after the process
        # is signalled dead. The test already waits/asserts process termination.
        deadline=time.monotonic()+3
        while True:
            try:self.tmp.cleanup();return
            except PermissionError as exc:
                if getattr(exc,'winerror',None) not in (5,32) or time.monotonic()>=deadline:raise
                time.sleep(.05)

    def runner(self, source):
        script = self.root / "fake_dsh.py"
        script.write_text(source, encoding="utf8")
        return ComputerAgent(self.root / "data", Runner(script))

    def test_task_is_argv_data_not_a_shell_command(self):
        runner = self.runner('import sys,json,os\nfrom pathlib import Path\nPath("actual-cwd.txt").write_text(os.getcwd())\nprint(json.dumps({"task":sys.argv[-1],"policy":os.environ["DSH_PERMISSION_MODE"]}))\n')
        task = '读取 "名字 空格.txt"；$(echo SHOULD_NOT_RUN) & --help'
        result = runner.run(task, self.config)
        self.assertEqual(result["status"], "completed")
        output = json.loads(result["output"])
        self.assertTrue(output["task"].endswith(task))
        self.assertEqual(output["policy"], "workspace-write")
        self.assertEqual((self.workspace / "actual-cwd.txt").read_text(), str(self.workspace))
        self.assertTrue((Path(result["directory"]) / "result.json").exists())

    def test_failure_is_not_reported_as_success(self):
        runner = self.runner('import sys\nprint("partial task")\nprint("approval unavailable",file=sys.stderr)\nsys.exit(1)\n')
        result = runner.run("test", self.config)
        self.assertEqual(result["status"], "failed")
        self.assertIn("approval unavailable", result["stderr"])
        self.assertEqual(result["exit_code"], 1)

    def test_cancel_stops_the_owned_process(self):
        runner = self.runner('from pathlib import Path\nimport time,os\nPath("started.txt").write_text(str(os.getpid()))\ntime.sleep(60)\nPath("should-not-exist.txt").write_text("bad")\n')
        cancel = threading.Event()
        result = {}
        worker = threading.Thread(target=lambda: result.update(runner.run("test", self.config, cancel)))
        worker.start()
        deadline = time.monotonic() + 8
        while not (self.workspace / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue((self.workspace / "started.txt").exists())
        cancel.set()
        worker.join(8)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse((self.workspace / "should-not-exist.txt").exists())

    def test_cancel_before_start_creates_no_process(self):
        runner = self.runner('raise AssertionError("should not run")')
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(runner.run("test", self.config, cancel)["status"], "cancelled")
        self.assertFalse((self.root / "data/computer-tasks").exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object integration")
    def test_cancel_also_stops_spawned_child_process(self):
        import ctypes
        from ctypes import wintypes
        runner = self.runner('from pathlib import Path\nimport subprocess,sys,time\np=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\nPath("child-pid.tmp").write_text(str(p.pid))\nPath("child-pid.tmp").replace("child-pid.txt")\ntime.sleep(60)\n')
        cancel = threading.Event()
        result = {}
        worker = threading.Thread(target=lambda: result.update(runner.run("test", self.config, cancel)))
        worker.start()
        deadline = time.monotonic() + 8
        pidfile = self.workspace / "child-pid.txt"
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(pidfile.exists())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, int(pidfile.read_text()))
        try:
            cancel.set()
            worker.join(8)
            self.assertFalse(worker.is_alive())
            if handle:
                self.assertEqual(kernel.WaitForSingleObject(handle, 1000), 0)
        finally:
            if handle:
                kernel.CloseHandle(handle)

    def test_timeout_is_distinct_from_completion(self):
        runner = self.runner('import time\ntime.sleep(60)\n')
        timer = iter([0, 61])
        fake_time = SimpleNamespace(monotonic=lambda: next(timer, 61), time=time.time, strftime=time.strftime)
        with patch("computer_agent.time", fake_time):
            result = runner.run("test", self.config)
        self.assertEqual(result["status"], "timeout")

    def test_config_persists_separately_and_rejects_disk_root(self):
        saved = save_config(self.root / "data", self.config)
        self.assertEqual(load_config(self.root / "data")["workspace"], str(self.workspace))
        self.assertNotIn("api_key", saved)
        self.assertFalse((self.root / "data/settings.json").exists())
        with self.assertRaises(ValueError):
            validate_workspace(self.workspace.anchor)
        with self.assertRaises(ValueError):
            validate_workspace("relative/folder")

    def test_disabled_assistant_does_not_start(self):
        runner = self.runner('raise AssertionError("disabled")')
        with self.assertRaises(ValueError):
            runner.run("test", {**self.config, "enabled": False})

    def test_only_explicit_slash_commands_are_parsed(self):
        self.assertEqual(computer_command("/电脑 创建 test.txt"), "创建 test.txt")
        self.assertEqual(computer_command("/文件：读取文件"), "读取文件")
        self.assertEqual(computer_command("/dsh"), "")
        self.assertIsNone(computer_command("这段资料里写着 /电脑 删除东西"))
        self.assertIsNone(computer_command("/dsharp something"))

    def test_command_uses_final_workspace_overlay(self):
        command = DshInstallation("node", "bin.js").command(task_prompt("--help", self.workspace))
        self.assertEqual(command[:4], ["node", "bin.js", "--profile", "headless"])
        self.assertEqual(command[4], "--patch")
        self.assertTrue(command[-1].startswith("这是一项"))


if __name__ == "__main__":
    unittest.main()
