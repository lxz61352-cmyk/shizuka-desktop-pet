"""Exercise the real pet save hooks without starting GUI, APIs or voice."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pet
from sync_bridge import SyncBridge


class PetSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = SyncBridge(self.root / "data", device="windows")
        self.other = SyncBridge(self.root / "mac", device="mac")
        self.context = patch.object(pet, "_sync_runtime", return_value=(self.bridge, None))
        self.context.start()

    def tearDown(self):
        self.context.stop()
        self.bridge.close()
        self.other.close()
        self.tmp.cleanup()

    def test_memory_save_merges_remote_addition(self):
        with patch.object(pet, "MEMORY_FILE", str(self.root / "data/memory.json")):
            memory = pet.MemoryStore(pet.MEMORY_FILE)
            memory.add("Windows 记忆")
            memory.save()
            self.other.exchange(self.bridge.export())
            self.other.commit("memories", [{"id": "remote", "content": "Mac 记忆"}], [])
            self.bridge.exchange(self.other.export())
            memory.items[0]["pinned"] = True
            memory.save()
            self.assertEqual(len(memory.items), 2)
            local = next(r for r in memory.items if r["content"] == "Windows 记忆")
            self.assertTrue(local["pinned"])

    def test_chat_append_has_stable_ids_and_remote_history_survives(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        app._chat_lock = threading.RLock()
        app._chat_log = pet.load_chatlog()
        app._sync_chat_base = deepcopy(app._chat_log)
        self.other.commit("chats", [{"id": "mac_chat", "text": "Mac 消息", "role": "user", "created": 1}], [])
        self.bridge.exchange(self.other.export())
        app._log_chat("user", "Windows 消息")
        self.assertEqual(len(app._chat_log), 2)
        rows = self.bridge.read("chats")
        self.assertTrue(all(r.get("id") and "created" in r for r in rows))
        self.assertEqual({r["text"] for r in rows}, {"Mac 消息", "Windows 消息"})

    def test_todo_completion_preserves_remote_text(self):
        app = pet.DeskPet.__new__(pet.DeskPet)
        self.bridge.commit("todos", [{"id": "t1", "text": "原待办", "done": False}], [])
        app.todos = app._load_todos()
        self.other.exchange(self.bridge.export())
        original = self.other.read("todos")
        edited = deepcopy(original)
        edited[0]["text"] = "Mac 编辑标题"
        self.other.commit("todos", edited, original)
        self.bridge.exchange(self.other.export())
        app.todos[0]["done"] = True
        app._save_todos()
        self.assertTrue(app.todos[0]["done"])
        self.assertEqual(app.todos[0]["text"], "Mac 编辑标题")

    def test_credential_migration_preserves_legacy_on_failure(self):
        keyfile = self.root / "fake-key.txt"
        keyfile.write_text("test placeholder")
        app = pet.DeskPet.__new__(pet.DeskPet)
        with patch.object(pet, "API_KEY_FILE", str(keyfile)), patch.object(pet, "_read_legacy_key_file", return_value="test-placeholder"), patch.object(pet, "_cred_read", return_value=""), patch.object(pet, "_cred_write", return_value=False):
            app._migrate_api_key()
        self.assertTrue(keyfile.exists())
        with patch.object(pet, "API_KEY_FILE", str(keyfile)), patch.object(pet, "_read_legacy_key_file", return_value="test-placeholder"), patch.object(pet, "_cred_read", return_value="different-placeholder"), patch.object(pet, "_cred_write", return_value=True):
            app._migrate_api_key()
        self.assertTrue(keyfile.exists())


if __name__ == "__main__":
    unittest.main()
