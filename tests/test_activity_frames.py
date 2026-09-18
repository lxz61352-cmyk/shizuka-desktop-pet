"""活动差分：整身帧接进角色包，放 i wanna / 联网查资料 / 待办提醒时切图。"""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import activity_states  # noqa: E402
import character_packs  # noqa: E402
import layered_renderer  # noqa: E402
import pet  # noqa: E402
from pet_motion import MotionController, Pose  # noqa: E402

PACK_DIR = ROOT / "characters" / "shizuka-side-motion"
FRAMES = {"researching": "activity/researching.png",
          "reminder": "activity/reminder.png",
          "listening": "activity/listening.png"}


class ManifestTests(unittest.TestCase):
    def test_pack_ships_the_three_frames(self):
        manifest = json.loads((PACK_DIR / "character.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(manifest.get("activity_frames"), FRAMES)

    def test_frames_are_full_canvas_rgba_with_transparent_corners(self):
        from PIL import Image
        for state, relative in FRAMES.items():
            with Image.open(PACK_DIR / relative) as image:
                self.assertEqual(image.mode, "RGBA", state)
                self.assertEqual(image.size, (1000, 943), state)
                self.assertTrue(image.getchannel("A").getbbox(), state)
                for corner in ((0, 0), (999, 0), (0, 942), (999, 942)):
                    self.assertEqual(image.getpixel(corner)[3], 0, (state, corner))

    def _pack_with(self, activities):
        """拷一份角色包（7MB 上下），只换 activity_frames 再走一遍完整校验。"""
        folder = Path(tempfile.mkdtemp(prefix="shizuka-pack-"))
        self.addCleanup(shutil.rmtree, folder, True)
        pack_dir = folder / "pack"
        shutil.copytree(PACK_DIR, pack_dir)
        manifest = json.loads((pack_dir / "character.json").read_text(encoding="utf-8-sig"))
        manifest["activity_frames"] = activities
        (pack_dir / "character.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return pack_dir

    def test_unknown_state_is_rejected(self):
        folder = self._pack_with({"dancing": "activity/researching.png"})
        with self.assertRaises(ValueError):
            character_packs.load_pack(folder)

    def test_empty_map_is_rejected(self):
        with self.assertRaises(ValueError):
            character_packs.load_pack(self._pack_with({}))

    def test_partial_map_is_accepted(self):
        pack = character_packs.load_pack(self._pack_with({"reminder": "activity/reminder.png"}))
        self.assertEqual(pack.manifest["activity_frames"], {"reminder": "activity/reminder.png"})

    def test_state_names_match_the_selector(self):
        self.assertEqual(character_packs.ACTIVITY_STATES,
                         {"working", "reminder", "exit", "awaiting_answer", "researching", "listening"})


class SelectTests(unittest.TestCase):
    def pose(self):
        return Pose()

    def test_music_shows_the_kimono(self):
        self.assertEqual(activity_states.select_activity(self.pose(), listening=True).state, "listening")

    def test_search_shows_the_phone(self):
        self.assertEqual(activity_states.select_activity(self.pose(), researching=True).state, "researching")

    def test_reminder_beats_music_and_search(self):
        state = activity_states.select_activity(self.pose(), reminder=True, listening=True, researching=True).state
        self.assertEqual(state, "reminder")

    def test_search_beats_file_task_but_music_beats_search(self):
        self.assertEqual(activity_states.select_activity(self.pose(), researching=True, working=True).state,
                         "researching")
        self.assertEqual(activity_states.select_activity(self.pose(), listening=True, researching=True).state,
                         "listening")

    def test_physical_states_win(self):
        for state in ("dragging", "falling", "landing", "recover", "pat", "happy"):
            self.assertEqual(activity_states.select_activity(Pose(state=state), listening=True).state, state)

    def test_idle_when_nothing_is_happening(self):
        self.assertEqual(activity_states.select_activity(self.pose()).state, "idle")


class TriggerTests(unittest.TestCase):
    def make_pet(self):
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._researching_active = False
        obj._researching_until = 0.0
        obj._researching_since = 0.0
        obj._voice_on = False
        obj._ui = lambda fn: fn()
        obj._show_loading_bubble = lambda *a, **k: None
        return obj

    def test_search_marks_her_as_researching(self):
        obj = self.make_pet()
        obj._announce_search("日期")
        self.assertTrue(obj._researching_active)
        self.assertTrue(obj._research_art_active())

    def test_art_stays_up_until_she_starts_reading_the_reply(self):
        """从"我帮你查一下"一直挂到正文开始出声：搜索结束、组织回答期间都还在查资料。"""
        obj = self.make_pet()
        obj._announce_search("日期")
        obj._search_done()
        self.assertTrue(obj._researching_active)      # 资料到手了，但她在组织回答
        self.assertTrue(obj._research_art_active())
        obj._reporting_now()                          # 正文开始念了
        self.assertFalse(obj._researching_active)
        self.assertTrue(obj._research_art_active())   # 收尾还留一点点

    def test_art_ends_after_the_tail(self):
        obj = self.make_pet()
        obj._announce_search("日期")
        obj._search_done()
        obj._reporting_now()          # 正文开始念了，收尾倒计时才开始
        # 收尾用的是 max(最短展示, 到手后尾巴)：最短展示更靠后，就等它
        self.assertFalse(obj._research_art_active(time.monotonic() + pet.RESEARCH_ART_MIN_SEC + 0.1))

    def test_music_state_is_read_from_the_mci_state(self):
        obj = self.make_pet()
        for state, expected in (("playing", True), ("paused", True), ("stopped", False)):
            obj._music_state = state
            self.assertIs(obj._music_on(), expected, state)


class ReminderTests(unittest.TestCase):
    def make_pet(self):
        obj = pet.DeskPet.__new__(pet.DeskPet)
        obj._activity_reminder_win = None
        obj._activity_saved_until = 0.0
        obj._reminder_art_until = 0.0
        obj._reminder_hop_last = None
        obj._reply_win = None
        obj.visible = True
        obj._quitting = False
        obj._motion = SimpleNamespace(action=None)
        obj._hopped = []
        obj._start_action = lambda action, now: obj._hopped.append((action, round(now, 3))) or True
        return obj

    def test_voice_reminder_keeps_the_clock_up(self):
        """语音念提醒不经过 _play_reply：没有窗口可挂时靠时间兜底，闹钟差分照样出来。"""
        obj = self.make_pet()
        obj._reminder_art_until = time.monotonic() + pet.REMINDER_ART_SEC
        self.assertTrue(obj._reminder_art_active())

    def test_clock_goes_away_with_the_bubble(self):
        obj = self.make_pet()
        self.assertFalse(obj._reminder_art_active())

    def test_reminder_hops_in_groups_of_two_every_three_seconds(self):
        obj = self.make_pet()
        obj._reminder_art_until = time.monotonic() + 60
        now = time.monotonic()
        obj._update_reminder_hop(now)
        self.assertEqual([a for a, _ in obj._hopped], ["happy"])      # 第一组立刻跳
        obj._update_reminder_hop(now + 1.0)
        self.assertEqual(len(obj._hopped), 1)                          # 不到 3 秒不再蹦
        obj._update_reminder_hop(now + 3.05)
        self.assertEqual(len(obj._hopped), 2)

    def test_no_hopping_without_a_reminder(self):
        obj = self.make_pet()
        obj._update_reminder_hop(time.monotonic())
        self.assertEqual(obj._hopped, [])

    def test_happy_action_is_two_hops(self):
        """"一次跳两下"就落在 happy 这个动作上（和双击她一样）。"""
        motion = MotionController()
        motion.trigger("happy", 0.0)
        heights = [motion.step(i * 0.02, enabled=True).dy for i in range(90)]
        airborne = [h < -0.01 for h in heights]
        arcs = sum(1 for i, up in enumerate(airborne) if up and not airborne[i - 1])
        self.assertEqual(arcs, 2, heights)


class RenderTests(unittest.TestCase):
    """真渲染一遍：三个状态贴的就是各自那张帧，不是常态立绘。"""

    @classmethod
    def setUpClass(cls):
        cls.renderer = layered_renderer.LayeredRenderer(character_packs.load_pack(PACK_DIR))

    def fresh(self):
        """清掉渐变状态，让每次断言都从干净的一帧开始。"""
        self.renderer._fade_from = None
        self.renderer._fade_state = None
        self.renderer._last_frame = None

    def test_every_frame_renders_differently_from_idle(self):
        idle = self.renderer.frame(420, pose=Pose(), animated=False)
        idle_box = idle.getchannel("A").getbbox()
        for state in FRAMES:
            self.assertIn(state, self.renderer.activity_frames, state)
            frame = self.renderer.frame(420, pose=Pose(state=state), animated=False)
            self.assertEqual(frame.size, idle.size, state)
            self.assertTrue(frame.getchannel("A").getbbox(), state)
            self.assertNotEqual(frame.getchannel("A").getbbox(), idle_box, state)

    def test_state_without_a_frame_falls_back_to_idle(self):
        idle = self.renderer.frame(420, pose=Pose(), animated=False)
        assert "working" not in self.renderer.activity_frames
        frame = self.renderer.frame(420, pose=Pose(state="working"), animated=False)
        self.assertEqual(frame.getchannel("A").getbbox(), idle.getchannel("A").getbbox())

    def test_activity_frames_breathe_instead_of_freezing(self):
        """整身差分不会眨眼，挂着的时候得有一点呼吸起伏，不然像张静止的图。"""
        self.fresh()
        first = self.renderer.frame(420, seconds=0.0, pose=Pose(state="listening"))
        later = self.renderer.frame(420, seconds=1.0, pose=Pose(state="listening"))
        # 切进去那一帧正在淡入，跟"稳定之后的同一状态"不该一样
        self.assertNotEqual(first.tobytes(), later.tobytes())
        still = self.renderer.frame(420, seconds=1.0, pose=Pose(state="listening"), animated=False)
        self.assertNotEqual(still.tobytes(), later.tobytes())

    def test_switching_into_a_frame_is_a_crossfade(self):
        """放歌切差分要渐变：切过去那一下从上一帧开始，过一会儿才稳定成纯差分。"""
        self.fresh()
        idle = self.renderer.frame(420, pose=Pose(), animated=True)
        switching = self.renderer.frame(420, pose=Pose(state="listening"), animated=True)
        self.assertIsNotNone(self.renderer._fade_from)      # 正在淡入
        self.assertEqual(switching.tobytes(), idle.tobytes())   # 起点就是上一帧
        time.sleep(layered_renderer.LayeredRenderer.ACTIVITY_FADE_SEC / 2)
        middle = self.renderer.frame(420, pose=Pose(state="listening"), animated=True)
        self.assertNotEqual(middle.tobytes(), idle.tobytes())   # 中间是混的
        time.sleep(layered_renderer.LayeredRenderer.ACTIVITY_FADE_SEC)
        after = self.renderer.frame(420, pose=Pose(state="listening"), animated=True)
        self.assertIsNone(self.renderer._fade_from)
        self.assertNotEqual(after.tobytes(), middle.tobytes())


if __name__ == "__main__":
    unittest.main()
