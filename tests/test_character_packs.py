"""Character isolation, real RGBA assets, animation, and live skin-switch regression."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image, ImageChops
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_packs import discover_packs, load_pack, selected_pack
from layered_renderer import LayeredRenderer


class PacksTest(unittest.TestCase):
    def test_real_assets_and_frames(self):
        packs, errors = discover_packs(ROOT / "characters")
        self.assertFalse(errors)
        self.assertEqual({p.id for p in packs},{"shizuka-classic","shizuka-side-motion"})
        pack = load_pack(ROOT/"experiments/archived-characters/shizuka-front-motion")
        renderer = LayeredRenderer(pack)
        neutral = renderer.frame(480,animated=False)
        closed = renderer.frame(480,animated=False,eye_open=0)
        talking = renderer.frame(480,animated=False,mouth_open=True)
        self.assertEqual(neutral.size, (320,480))
        self.assertEqual(neutral.getchannel("A").getextrema()[0],0)
        self.assertIsNotNone(ImageChops.difference(neutral,closed).convert("RGB").getbbox())
        self.assertIsNotNone(ImageChops.difference(neutral,talking).convert("RGB").getbbox())
        self.assertIsNone(ImageChops.difference(neutral,renderer.frame(480,100,animated=False)).getbbox())
        started=time.perf_counter()
        for i in range(80):
            renderer.frame(480,i/20,gaze=(1,-1),speaking=True,color_key=True)
        ms=(time.perf_counter()-started)*1000/80
        print(f"Rendering: {ms:.1f} ms/frame at 480px, target 20 fps")
        # Diagnostic only: the user's desktop, game, and preview can load the CPU.
        # Functional checks above must not fail because another app is rendering.

    def test_original_pose_unchanged_and_edits_localized(self):
        pack=load_pack(ROOT/"experiments/archived-characters/shizuka-original-motion")
        original=ROOT/"assets/pet.png"
        self.assertEqual(pack.portrait.read_bytes(),original.read_bytes())
        self.assertEqual(pack.asset("layers/original.png").read_bytes(),original.read_bytes())
        with Image.open(original) as source:
            base=Image.alpha_composite(Image.new("RGBA",source.size),source.convert("RGBA"))
        renderer=LayeredRenderer(pack)
        self.assertEqual(base.tobytes(),renderer.frame(943,animated=False).tobytes())
        for kwargs, bounds in (({"eye_open":0},(508,302,620,401)),
                               ({"mouth_open":True},(451,399,502,430))):
            frame=renderer.frame(943,animated=False,**kwargs)
            box=ImageChops.difference(base,frame).convert("RGB").getbbox()
            self.assertIsNotNone(box)
            self.assertTrue(box[0]>=bounds[0] and box[1]>=bounds[1] and box[2]<=bounds[2] and box[3]<=bounds[3])

    def test_pack_paths_and_identity(self):
        classic=load_pack(ROOT / "characters/shizuka-classic")
        with tempfile.TemporaryDirectory(prefix="shizuka-pack-") as tmp:
            directory=Path(tmp)/"new-character"
            shutil.copytree(classic.directory,directory)
            m=classic.manifest.copy()
            m.update(id="new-character",character_id="new-character")
            manifest=directory/"character.json"
            manifest.write_text(json.dumps(m),encoding="utf-8")
            new=load_pack(directory)
            self.assertEqual(classic.data_directory(Path(tmp)),Path(tmp))
            self.assertEqual(new.data_directory(Path(tmp)),Path(tmp)/"characters/new-character")
            m["portrait"]="../outside.png"
            (Path(tmp)/"outside.png").write_bytes(classic.portrait.read_bytes())
            manifest.write_text(json.dumps(m),encoding="utf-8")
            with self.assertRaises(ValueError):load_pack(directory)
            self.assertEqual(selected_pack(ROOT/"characters",Path(tmp)/"missing-settings.json")[0].id,"shizuka-side-motion")
            settings=Path(tmp)/"old-settings.json"
            settings.write_text(json.dumps({"character_pack":"shizuka-front-motion"}),encoding="utf-8")
            self.assertEqual(selected_pack(ROOT/"characters",settings)[0].id,"shizuka-side-motion")
            m["portrait"]="portrait.png"
            m["status"]="archived"
            manifest.write_text(json.dumps(m),encoding="utf-8")
            self.assertEqual(discover_packs(Path(tmp))[0],[])
            self.assertEqual(len(discover_packs(Path(tmp),include_archived=True)[0]),1)

    def test_live_switch_keeps_memory_and_history(self):
        import pet
        classic=load_pack(ROOT/"characters/shizuka-classic")
        lab=load_pack(ROOT/"experiments/archived-characters/shizuka-lab")
        with tempfile.TemporaryDirectory(prefix="shizuka-switch-") as tmp:
            data=Path(tmp)
            overrides={"DATA_DIR":tmp,"SETTINGS_FILE":str(data/"settings.json"),
                       "TODO_FILE":str(data/"todos.json"),"MEMORY_FILE":str(data/"memory.json"),
                       "CHATLOG_DIR":tmp,"CHATLOG_FILE":str(data/"chat.json"),
                       "API_KEY_FILE":str(data/"api.txt"),"ACTIVE_PACK":classic,"IMG_PATH":str(classic.portrait),"_MEM":None}
            with patch.multiple(pet,**overrides),patch.object(pet,"read_api_key",return_value=""):
                app=pet.DeskPet()
                try:
                    memory=pet.get_memory()
                    memory.add("keep existing memory",pinned=True)
                    memory.save()
                    before=Path(pet.MEMORY_FILE).read_bytes()
                    app._history.append({"role":"user","content":"keep short history"})
                    app.show_characters()
                    app.root.update()
                    self.assertTrue(app._character_win.winfo_viewable())
                    app._apply_character_pack(lab)
                    app._animate_pet()
                    app.root.update()
                    self.assertEqual(app._character_pack.id,"shizuka-lab")
                    self.assertIsNotNone(app._animator)
                    app.on_wheel(type("Wheel",(),{"delta":120})())
                    app._do_wheel_apply()
                    original_motion=load_pack(ROOT/"experiments/archived-characters/shizuka-original-motion")
                    app._apply_character_pack(original_motion)
                    app.root.update()
                    self.assertEqual(app.pet.winfo_width(),app.pet_img.width)
                    app._apply_character_pack(lab)
                    self.assertEqual(json.loads(Path(pet.SETTINGS_FILE).read_text(encoding="utf-8"))["character_pack"],lab.id)
                    app.hide("left")
                    app._animate_pet()
                    app.restore()
                    app._apply_character_pack(classic)
                    self.assertIsNone(app._animator)
                    self.assertEqual(Path(pet.MEMORY_FILE).read_bytes(),before)
                    self.assertEqual(app._history[0]["content"],"keep short history")
                    self.assertFalse((data/"error.log").exists())
                finally:
                    for pending in app.root.tk.call("after","info"):
                        app.root.after_cancel(pending)
                    app.root.destroy()


if __name__ == "__main__":
    unittest.main()
