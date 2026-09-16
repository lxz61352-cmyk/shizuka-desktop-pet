"""恢复帧的角色包不一定有 expression_frames；渲染不能因此抛 KeyError。

渲染线程一旦抛异常，pet.py 的 _take_render 会把动态绘制整体关掉、退回静态立绘，
所以这条回退必须有测试守着。
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PIL import Image, ImageDraw  # noqa: E402
from character_packs import CharacterPack  # noqa: E402
from layered_renderer import LayeredRenderer  # noqa: E402
from pet_motion import Pose  # noqa: E402

CANVAS = (64, 64)
BODY_STATES = ("dragging", "falling", "landing", "recover")


class RecoverFrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        (self.directory / "body").mkdir()
        for name in BODY_STATES:
            self._figure(self.directory / "body" / f"{name}.png")
        self._figure(self.directory / "body" / "settle.png")
        self._figure(self.directory / "neutral.png")

    def tearDown(self):
        self.tmp.cleanup()

    def _figure(self, path):
        """全画布 RGBA：alpha 最小值必须是 0（真透明），且非空。"""
        image = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 40, 40), fill=(120, 140, 180, 255))
        image.save(path)

    def manifest(self, with_expression_frames):
        manifest = {
            "canvas_size": list(CANVAS),
            "layers": [{"id": "body", "image": "body/recover.png", "box": [0, 0, *CANVAS],
                        "group": "figure", "role": "body"}],
            "body_frames": {name: f"body/{name}.png" for name in BODY_STATES},
            "recover_frames": [{"id": "settle", "path": "body/settle.png", "duration": 0.2}],
        }
        if with_expression_frames:
            manifest["expression_frames"] = {"neutral": "neutral.png"}
        return manifest

    def renderer(self, with_expression_frames=False):
        pack = CharacterPack(self.directory, self.manifest(with_expression_frames))
        return LayeredRenderer(pack)

    def render(self, renderer, phase):
        # animated=True 才会保留传入的 pose（animated=False 时 frame() 会退回默认 Pose，
        # 也就走不到 recover 分支——测试必须走真实运行时那一条）。
        return renderer.frame(CANVAS[1], seconds=0.0, animated=True, color_key=True,
                              pose=Pose(state="recover", phase=phase))

    def test_recover_prepare_without_expression_frames_does_not_raise(self):
        frame = self.render(self.renderer(), "prepare")
        self.assertEqual(frame.size, CANVAS)
        self.assertEqual(frame.mode, "RGB")   # 色键输出是 RGB

    def test_recover_authored_frame_is_used(self):
        frame = self.render(self.renderer(), "settle")
        self.assertEqual(frame.size, CANVAS)

    def test_recover_tidy_falls_back_to_the_body_frame(self):
        frame = self.render(self.renderer(), "tidy")
        self.assertEqual(frame.size, CANVAS)

    def test_recover_prepare_prefers_neutral_when_available(self):
        frame = self.render(self.renderer(with_expression_frames=True), "prepare")
        self.assertEqual(frame.size, CANVAS)


if __name__ == "__main__":
    unittest.main()
