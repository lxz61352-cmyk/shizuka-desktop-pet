"""Exercise real Tk widgets and persistence using isolated data, without network."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="shizuka-smoke-") as folder:
        data = Path(folder)
        pet.DATA_DIR = folder
        for attr, name in (("SETTINGS_FILE", "settings.json"), ("MEMORY_FILE", "memory.json"),
                           ("TODO_FILE", "todos.json"), ("API_KEY_FILE", "api_key.txt"),
                           ("LOCK_FILE", ".pet.lock"), ("CHATLOG_FILE", "chat.json")):
            setattr(pet, attr, str(data / name))
        pet.CHATLOG_DIR = folder
        pet._MEM = None
        pet.read_api_key = lambda: ""
        pet.PROACTIVE_FOREGROUND = False
        pet.IDLE_CHAT_ENABLED = False
        app = pet.DeskPet()
        app._sound_mode = "none"
        app._clip_on = False
        try:
            app.root.update()
            assert app.pet.winfo_viewable()
            assert pet.monitor_workarea_of_point(0, 0)
            print("PASS: Tk window, transparent image, monitor workarea")
            app.open_chat_input()
            app.root.update()
            assert app._chat_win.winfo_viewable()
            app.close_chat_win()
            app.show_menu(SimpleNamespace(x_root=400, y_root=300))
            app.root.update()
            assert app.popup.winfo_viewable()
            app.close_popup()
            print("PASS: chat input and settings menu")
            app._prompt_api_key()
            app.root.update()
            key_windows = [w for w in app.root.winfo_children() if isinstance(w, pet.tk.Toplevel)
                           and w.title() == "设置 API Key"]
            assert len(key_windows) == 1
            assert any(isinstance(w, pet.tk.Entry) and w.cget("show") == "*"
                       for w in key_windows[0].winfo_children())
            key_windows[0].destroy()
            print("PASS: provider selection and masked credential field")
            app.show_todos()
            app.root.update()
            assert app._todo_win.winfo_viewable()
            item = app.add_todo("isolated smoke reminder", due_ts=pet.time.time() + 600)
            assert json.loads(Path(pet.TODO_FILE).read_text(encoding="utf-8"))["items"][0]["id"] == item["id"]
            app._close_todo_window()
            memory = pet.get_memory()
            memory.add("isolated smoke memory", pinned=True)
            memory.save()
            assert pet.MemoryStore(pet.MEMORY_FILE).items[0]["pinned"]
            app.show_memory()
            app.root.update()
            assert app._mem_win.winfo_viewable()
            app._close_memory_window()
            app._log_chat("user", "isolated chat record")
            assert pet.load_chatlog()[0]["text"] == "isolated chat record"
            app.show_chat_log()
            app.root.update()
            assert app._chatlog_win.winfo_viewable()
            app._close_chat_log()
            print("PASS: todo, memory, chat history windows and disk round-trip")
            app.on_wheel(SimpleNamespace(delta=120))
            app._do_wheel_apply()
            app.root.update()
            assert app._cur_h > pet.DISPLAY_H
            app.hide("left")
            app.root.update()
            assert not app.visible
            app.restore()
            app.root.update()
            assert app.visible and app.pet.winfo_viewable()
            print("PASS: scaling, hide and restore")
            with patch("openai.OpenAI") as factory:
                factory.return_value.__enter__.return_value.models.list.side_effect = RuntimeError("offline test")
                assert pet.detect_provider("synthetic-test-key", base_url="https://api.deepseek.com") is None
                assert factory.call_count == 1
                assert factory.call_args.kwargs["base_url"] == "https://api.deepseek.com"
            print("PASS: API failure never tries a second provider")
            # Test the mutex in its own namespace; do not conflict with the running pet.
            pet._MUTEX_NAME = "Local\\ShizukaSmoke_" + pet.uuid.uuid4().hex
            pet.acquire_single_instance()
            try:
                try:
                    pet.acquire_single_instance()
                except pet.SingleInstanceError:
                    pass
                else:
                    raise AssertionError("Second instance was accepted")
            finally:
                pet.release_single_instance()
            pet.acquire_single_instance()
            pet.release_single_instance()
            assert not (data / "error.log").exists()
            print("PASS: single instance, release and restart; no Tk callback errors")
            if args.preview:
                app.pet.overrideredirect(False)
                app.pet.title("静香桌宠 · 兼容性验收")
                app.pet.geometry("+480+250")
                app.pet.protocol("WM_DELETE_WINDOW", app.root.destroy)
                app.root.after(120000, app.root.destroy)
                print("PREVIEW_READY", flush=True)
                app.root.mainloop()
        finally:
            try:
                app.root.destroy()
            except pet.tk.TclError:
                pass


if __name__ == "__main__":
    main()
