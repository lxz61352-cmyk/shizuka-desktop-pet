"""Capture errors before pet.py can even import its GUI dependencies."""
import datetime
from pathlib import Path
import sys
import traceback
import time


def main():
    if "--self-test" in sys.argv:
        import os
        import tempfile
        with tempfile.TemporaryDirectory(prefix="shizuka-self-test-") as folder:
            os.environ["SHIZUKA_DATA_DIR"] = folder
            return _main()
    return _main()


def _main():
    try:
        if "--surface-fixture" in sys.argv:
            import tkinter as tk
            root=tk.Tk();root.title("Shizuka window landing test")
            root.geometry("600x330+200+520");root.attributes("-topmost",True)
            tk.Label(root,text="Window landing test",font=("Arial",18)).pack(pady=40)
            root.after(8000,root.destroy);root.mainloop()
            return 0
        import pet
        if "--self-test" in sys.argv:
            from release_smoke import run
            return run(pet)
        if "--preview" in sys.argv:
            import preview_character
            sys.argv=[sys.argv[0]]
            preview_character.main()
            return 0
        deadline = time.monotonic() + (15 if "--wait-for-restart" in sys.argv else 0)
        while True:
            try:
                pet.acquire_single_instance()
                break
            except pet.SingleInstanceError:
                if time.monotonic() >= deadline:
                    if "--wait-for-restart" in sys.argv:
                        raise RuntimeError("角色切换等待超时，请关闭旧桌宠后重新启动。")
                    return 0
                time.sleep(0.2)
        try:
            app = pet.DeskPet()
            if "--computer" in sys.argv:
                app.root.after(100, app.show_computer_assistant)
            if "--weixin" in sys.argv or "--weixin-pair" in sys.argv:
                def open_weixin():
                    app.show_weixin()
                    if "--weixin-pair" in sys.argv:
                        app._weixin_begin_login()
                app.root.after(300, open_weixin)
            app.run()
        finally:
            pet.release_single_instance()
        return 0
    except Exception:
        root = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent.parent
        log = root / "data" / "startup_error.log"
        testing='--self-test' in sys.argv or '--exit-self-test' in sys.argv
        if testing and '--report' in sys.argv:
            log=Path(sys.argv[sys.argv.index('--report')+1]).parent/'self-test-error.log'
        details = traceback.format_exc()
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.datetime.now().isoformat()}\n{details}\n")
        if sys.stderr is not None:
            print(details, file=sys.stderr)
        if testing:return 1
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"桌宠启动失败。\n错误详情已保存到：\n{log}", "静香助手", 0x10)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
