"""角色包里的交互区/睡姿锚点必须在加载期就校验：pet.py 会直接下标比较这些数字。

另外 settings.json 的 character_pack 现在会被真正读取（内置包共用同一个 character_id）。
"""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_packs import load_pack, selected_pack  # noqa: E402

SOURCE = ROOT / "characters" / "shizuka-side-motion"


class PackRegionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / "pack"
        shutil.copytree(SOURCE, self.directory)
        self.manifest = json.loads((SOURCE / "character.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, mutate):
        manifest = json.loads(json.dumps(self.manifest))
        mutate(manifest)
        (self.directory / "character.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return self.directory

    def test_valid_pack_still_loads(self):
        self.assertEqual(load_pack(self.directory).id, "shizuka-side-motion")

    def test_short_region_is_rejected(self):
        target = self.write(lambda m: m["interaction_regions"].__setitem__("head_pat", [330, 110, 675]))
        with self.assertRaises(ValueError):
            load_pack(target)

    def test_reversed_region_is_rejected(self):
        target = self.write(lambda m: m["interaction_regions"].__setitem__("head_pat", [675, 110, 330, 275]))
        with self.assertRaises(ValueError):
            load_pack(target)

    def test_region_outside_canvas_is_rejected(self):
        target = self.write(lambda m: m["interaction_regions"].__setitem__("head_pat", [330, 110, 1675, 275]))
        with self.assertRaises(ValueError):
            load_pack(target)

    def test_bad_sleep_anchor_is_rejected(self):
        target = self.write(lambda m: m.__setitem__("sleep_effect_anchor", [720]))
        with self.assertRaises(ValueError):
            load_pack(target)

    def test_selected_pack_honours_the_setting(self):
        settings = Path(self.tmp.name) / "settings.json"
        pack = Path(self.tmp.name) / "characters"
        shutil.copytree(ROOT / "characters", pack)
        settings.write_text(json.dumps({"character_pack": "shizuka-classic"}), encoding="utf-8")
        chosen, errors = selected_pack(pack, settings)
        self.assertEqual(chosen.id, "shizuka-classic")
        self.assertEqual(errors, [])

    def test_selected_pack_falls_back_when_setting_is_unknown(self):
        settings = Path(self.tmp.name) / "settings.json"
        pack = Path(self.tmp.name) / "characters"
        shutil.copytree(ROOT / "characters", pack)
        settings.write_text(json.dumps({"character_pack": "no-such-pack"}), encoding="utf-8")
        chosen, _ = selected_pack(pack, settings)
        self.assertEqual(chosen.id, "shizuka-side-motion")


if __name__ == "__main__":
    unittest.main()
