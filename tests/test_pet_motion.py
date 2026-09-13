"""Interaction regressions: intact artwork, bounded springs and actual Tk routing."""
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image,ImageChops
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from pet_motion import MotionController,Pose
from character_packs import load_pack
from layered_renderer import LayeredRenderer
from pet_ground import GroundMotion, floor_position
from pet_triggers import ActionTriggers
from pet_surfaces import WindowSurface
from dataclasses import replace

class MotionTest(unittest.TestCase):
    def test_held_petting_follows_distance_and_returns_without_moving_body(self):
        motion=MotionController();motion.trigger("pat",0)
        motion.begin_pet(.5,0);motion.pet_to(.55)
        for i in range(61):small=motion.step(i/60)
        motion.pet_to(.65)
        for i in range(61,121):large=motion.step(i/60)
        self.assertGreater(abs(large.head_dx),abs(small.head_dx)*2)
        self.assertLess(large.head_angle,small.head_angle)
        motion.pet_to(-10)
        for i in range(121,301):held=motion.step(i/60)
        self.assertEqual(held.state,"pat")
        self.assertTrue(motion.petting)
        self.assertLessEqual(abs(held.head_angle),5.41)
        self.assertEqual((held.angle,held.dy,held.body_stretch),(0,0,1))
        renderer=LayeredRenderer(load_pack(ROOT/"characters/shizuka-side-motion"))
        neutral=renderer.frame(943,animated=False)
        frame=renderer.frame(943,pose=held)
        self.assertEqual(neutral.crop((0,550,1000,943)).tobytes(),frame.crop((0,550,1000,943)).tobytes())
        motion.end_pet(5)
        self.assertEqual(motion.step(5.1).phase,"end")
        final=motion.step(5.5)
        self.assertFalse(motion.petting)
        self.assertEqual(final.state,"idle")
        self.assertEqual((final.head_angle,final.head_dx),(0,0))
        motion.trigger("pat",6);motion.begin_pet(.5,6)
        motion.begin_drag((0,0),(.5,.2),6.2)
        self.assertFalse(motion.petting)
        self.assertEqual(motion.step(6.3).expression,"lifted")

    def test_sway_release_settles_and_off_resets(self):
        motion=MotionController()
        motion.step(0)
        motion.begin_drag((-2,0),(.5,.2),0)
        poses=[]
        for i in range(1,61):
            t=i/60
            motion.drag_to((-2+.3*math.sin(t*8),0),t)
            poses.append(motion.step(t))
        self.assertGreater(max(abs(p.angle) for p in poses),5)
        self.assertLessEqual(max(abs(p.angle) for p in poses),19)
        self.assertTrue(any(p.expression=="lifted" for p in poses))
        self.assertTrue(all(p.body_stretch<=1.064 for p in poses))
        motion.release(1,falling=True)
        self.assertEqual(motion.step(1.05).state,"falling")
        self.assertEqual(motion.step(1.1).dy,0)
        motion.land(1.2)
        release=[motion.step(1+i/60) for i in range(1,241)]
        self.assertTrue(all(p.expression=="neutral" for p in release))
        self.assertLess(abs(release[-1].angle),.05)
        self.assertLess(abs(release[-1].body_stretch-1),.001)
        self.assertEqual(release[-1].state,"idle")
        motion.trigger("happy",5)
        self.assertEqual(motion.step(5.2,enabled=False),Pose())
        self.assertIsNone(motion.action)

    def test_held_pout_has_no_timeout(self):
        motion=MotionController()
        motion.begin_drag((0,0),(.5,.2),0)
        for i in range(501):
            pose=motion.step(i/50)
            self.assertEqual(pose.expression,"lifted")
        motion.release(10,falling=True)
        self.assertEqual(motion.step(10.02).expression,"falling")
        motion.land(10.5)
        self.assertEqual(motion.step(10.52).expression,"neutral")

    def test_ground_contact_and_negative_monitor(self):
        self.assertEqual(floor_position((-1920,0,0,1040),(292,76,730,872),.5,-1800),(-1800,604))
        for fps in (20,30,60):
            ground=GroundMotion()
            ground.start(100,600,0)
            ys=[];hits=0
            for i in range(1,fps*4):
                step=ground.step(i/fps)
                ys.append(step.y)
                hits+=step.impact
            self.assertEqual(hits,1)
            self.assertEqual(ys[-1],600)
            self.assertLessEqual(max(ys),600)
            self.assertTrue(any(ys[i]<ys[i-1] for i in range(1,len(ys))))
            self.assertFalse(ground.active)
            ground.start(900,600,5)
            self.assertLessEqual(ground.step(5.02).y,600)

    def test_side_local_head_leaves_body_pixels_still(self):
        pack=load_pack(ROOT/"characters/shizuka-side-motion")
        renderer=LayeredRenderer(pack)
        original=Image.open(pack.portrait).convert("RGBA")
        base=Image.alpha_composite(Image.new("RGBA",original.size),original)
        self.assertEqual(base.tobytes(),renderer.frame(943,animated=False).tobytes())
        for pose in (Pose(head_angle=3,eye_open=0,state="pat"),
                     Pose(head_angle=5,head_dy=.008,eye_open=0,state="sleep")):
            frame=renderer.frame(943,pose=pose)
            self.assertIsNotNone(ImageChops.difference(base,frame).convert("RGB").getbbox())
            self.assertEqual(base.crop((0,550,1000,943)).tobytes(),frame.crop((0,550,1000,943)).tobytes())
        held=renderer.frame(943,pose=Pose(expression="lifted",state="dragging"))
        box=ImageChops.difference(base,held).convert("RGB").getbbox()
        self.assertTrue(box and box[0]>=451 and box[1]>=399 and box[2]<=502 and box[3]<=430,box)
        falling=renderer.frame(943,pose=Pose(expression="falling"))
        box=ImageChops.difference(base,falling).convert("RGB").getbbox()
        self.assertTrue(box and box[0]>=451 and box[1]>=399 and box[2]<=502 and box[3]<=430,box)
        self.assertNotEqual(held.tobytes(),falling.tobytes())
        self.assertEqual(base.getchannel("A").tobytes(),falling.getchannel("A").tobytes())

    def test_two_hops_and_sleep_effect_does_not_change_face(self):
        self.assertEqual(set(MotionController.ACTIONS),{"pat","happy","sleep"})
        motion=MotionController();motion.trigger("happy",0)
        heights=[motion.step(i/100).dy for i in range(220)]
        intervals=sum(a==0 and b<0 for a,b in zip(heights,heights[1:]))
        self.assertEqual(intervals,2)
        self.assertAlmostEqual(min(heights[98:]),-.036,places=4)
        self.assertEqual(heights[-1],0)
        self.assertAlmostEqual(min(heights),-.045,places=4)
        renderer=LayeredRenderer(load_pack(ROOT/"characters/shizuka-side-motion"))
        motion.reset();motion.trigger("sleep",0)
        pose=motion.step(1.7)
        plain=renderer.frame(480,1.7,pose=replace(pose,sleep_fx=0))
        sleepy=renderer.frame(480,1.7,pose=pose)
        difference=ImageChops.difference(plain,sleepy).convert("RGB").getbbox()
        self.assertIsNotNone(difference)
        self.assertGreaterEqual(difference[0],round(720*480/943))
        self.assertEqual(plain.crop((0,0,365,480)).tobytes(),sleepy.crop((0,0,365,480)).tobytes())
        native=renderer.frame(480,1.7,pose=pose,color_key=True)
        native_plain=renderer.frame(480,1.7,pose=replace(pose,sleep_fx=0),color_key=True)
        self.assertIsNotNone(ImageChops.difference(native,native_plain).getbbox())
        self.assertEqual(motion.step(5.1).sleep_fx,0)

    def test_frame_rates_and_actions(self):
        angles=[]
        for fps in (20,30,60):
            motion=MotionController()
            motion.step(0)
            motion.begin_drag((0,0),(.5,.2),0)
            for i in range(1,fps+1):
                t=i/fps
                motion.drag_to((t,0),t)
                pose=motion.step(t)
            angles.append(pose.angle)
        self.assertLess(max(angles)-min(angles),1.8)
        motion=MotionController()
        for action,length in motion.ACTIONS.items():
            motion.reset()
            motion.trigger(action,0)
            self.assertEqual(motion.step(length/2).state,action)
            self.assertEqual(motion.step(length+.1).state,"idle")
        with self.assertRaises(ValueError):motion.trigger("unknown",0)

    def test_front_cutout_exact_and_expressions_local(self):
        pack=load_pack(ROOT/"experiments/archived-characters/shizuka-front-motion")
        master=ROOT/"experiments/archived-characters/shizuka-lab/source/master-alpha-v2.png"
        self.assertEqual(pack.portrait.read_bytes(),master.read_bytes())
        original=Image.open(master).convert("RGBA")
        base=Image.alpha_composite(Image.new("RGBA",original.size),original)
        renderer=LayeredRenderer(pack)
        self.assertEqual(base.tobytes(),renderer.frame(1536,animated=False).tobytes())
        for kwargs,allowed in ((dict(eye_open=0,animated=False),(312,404,676,547)),
                               (dict(mouth_open=True,animated=False),(463,550,535,603)),
                               (dict(pose=Pose(expression="lifted")),(467,548,535,586))):
            frame=renderer.frame(1536,**kwargs)
            self.assertEqual(base.getchannel("A").tobytes(),frame.getchannel("A").tobytes())
            box=ImageChops.difference(base,frame).convert("RGB").getbbox()
            self.assertIsNotNone(box)
            self.assertTrue(box[0]>=allowed[0] and box[1]>=allowed[1] and box[2]<=allowed[2] and box[3]<=allowed[3],box)
        stretched=renderer.frame(1536,pose=Pose(body_stretch=1.063))
        self.assertEqual(base.crop((0,0,1024,695)).tobytes(),stretched.crop((0,0,1024,695)).tobytes())

    def test_tk_left_pat_right_drag_double_jump_and_chat_are_separate(self):
        import pet
        pack=load_pack(ROOT/"characters/shizuka-side-motion")
        with tempfile.TemporaryDirectory(prefix="shizuka-motion-") as tmp:
            data=Path(tmp)
            changes={"DATA_DIR":tmp,"SETTINGS_FILE":str(data/"settings.json"),
                "TODO_FILE":str(data/"todos.json"),"MEMORY_FILE":str(data/"memory.json"),
                "CHATLOG_DIR":tmp,"CHATLOG_FILE":str(data/"chat.json"),
                "API_KEY_FILE":str(data/"no-key"),"ACTIVE_PACK":pack,"IMG_PATH":str(pack.portrait),"_MEM":None}
            with patch.multiple(pet,**changes),patch.object(pet,"read_api_key",return_value=""):
                app=pet.DeskPet()
                try:
                    app.root.update()
                    app._animation_on=True
                    app.pet.geometry("+600+300")
                    app.root.update()
                    now=pet.time.monotonic()
                    scale=app._cur_h/943
                    position=(app.pet.winfo_x(),app.pet.winfo_y())
                    for i,x in enumerate((400,475,400,475)):
                        with patch.object(pet.time,"monotonic",return_value=now+i*.15):
                            app.label.event_generate("<ButtonPress-1>" if i==0 else "<B1-Motion>",x=round(x*scale),y=round(190*scale),
                                rootx=app.label.winfo_rootx()+round(x*scale),
                                rooty=app.label.winfo_rooty()+round(190*scale),state=0x100 if i else 0)
                            app._update_automatic_actions(now+i*.15)
                            app.root.update()
                    self.assertEqual(app._motion.action,"pat")
                    self.assertTrue(app._motion.petting)
                    self.assertNotEqual(app._motion.pet_target,0)
                    app.label.event_generate("<ButtonRelease-1>",x=round(475*scale),y=round(190*scale),
                        rootx=app.label.winfo_rootx()+round(475*scale),rooty=app.label.winfo_rooty()+round(190*scale))
                    app.root.update()
                    self.assertEqual((app.pet.winfo_x(),app.pet.winfo_y()),position)
                    self.assertFalse(app._ground.active)
                    self.assertFalse(app._motion.dragging)
                    self.assertFalse(app._motion.petting)
                    self.assertFalse(app._toggle_pending)
                    self.assertIsNone(app._drag)
                    app._motion.reset()
                    app._triggers=ActionTriggers(pet.time.monotonic())
                    with patch.object(app._motion,"begin_drag",wraps=app._motion.begin_drag) as begin,patch.object(app,"toggle_chat") as chat:
                        def event(kind,x,y):
                            app.label.event_generate(kind,x=x,y=y,
                                rootx=app.label.winfo_rootx()+x,rooty=app.label.winfo_rooty()+y)
                            app.root.update()
                        event("<ButtonPress-3>",170,140)
                        self.assertIsNone(app._actions_win)
                        event("<B3-Motion>",172,141)
                        self.assertEqual(begin.call_count,0)
                        event("<B3-Motion>",220,143)
                        event("<B3-Motion>",270,143)
                        self.assertEqual(begin.call_count,1)
                        app._animate_pet()
                        self.assertTrue(app._motion.dragging)
                        event("<ButtonRelease-3>",270,143)
                        self.assertFalse(app._motion.dragging)
                        self.assertTrue(app._ground.active)
                        finish=app._ground.last+4
                        # Advance the real GUI loop against deterministic clock samples.
                        now=app._ground.last
                        while app._ground.active and now<finish:
                            now+=.04
                            with patch.object(pet.time,"monotonic",return_value=now):
                                app._animate_pet()
                            app.root.update_idletasks()
                        self.assertTrue(app._grounded)
                        self.assertEqual(app.pet.winfo_y(),app._floor_target()[1])
                        self.assertFalse(app._toggle_pending)
                        self.assertIsNone(app._actions_win)
                        chat.assert_not_called()
                        # Return the simulated landing clock to the real clock.
                        app._motion.land(pet.time.monotonic()-1)
                        event("<ButtonPress-1>",170,140)
                        event("<ButtonRelease-1>",170,140)
                        # Let the queued click callback execute exactly once.
                        done=pet.tk.BooleanVar(app.root,value=False)
                        app.root.after(app._click_delay_ms+50,lambda:done.set(True))
                        app.root.wait_variable(done)
                        self.assertEqual(chat.call_count,1)
                        self.assertTrue(app._grounded)
                        for _ in range(2):
                            event("<ButtonPress-1>",round(485*scale),round(570*scale))
                            event("<ButtonRelease-1>",round(485*scale),round(570*scale))
                        self.assertEqual(app._motion.action,"happy")
                        self.assertFalse(app._toggle_pending)
                        self.assertIsNone(app._click_after)
                        done.set(False)
                        app.root.after(app._click_delay_ms+50,lambda:done.set(True))
                        app.root.wait_variable(done)
                        self.assertEqual(chat.call_count,1)
                        self.assertFalse(app._ground.active)
                        app._motion.reset()
                        app._triggers=ActionTriggers(pet.time.monotonic())
                        # A left drag over the body never moves the pet or opens chat.
                        position=(app.pet.winfo_x(),app.pet.winfo_y())
                        event("<ButtonPress-1>",round(485*scale),round(570*scale))
                        event("<B1-Motion>",round(540*scale),round(580*scale))
                        event("<ButtonRelease-1>",round(540*scale),round(580*scale))
                        self.assertEqual((app.pet.winfo_x(),app.pet.winfo_y()),position)
                        self.assertFalse(app._toggle_pending)
                        event("<ButtonPress-3>",170,140)
                        event("<ButtonRelease-3>",170,140)
                        self.assertTrue(app._actions_win.winfo_viewable())
                        self.assertEqual(chat.call_count,1)
                        app.on_wheel(SimpleNamespace(delta=120))
                        app._do_wheel_apply()
                        app.root.update_idletasks()
                        self.assertEqual(app.pet.winfo_y(),app._floor_target()[1])
                    app.show_actions()
                    app.root.update()
                    self.assertTrue(app._actions_win.winfo_viewable())
                    with patch.object(pet.time,"monotonic",return_value=now+1):
                        app.play_action("happy")
                    self.assertEqual(app._motion.action,"happy")
                    app.hide()
                    self.assertIsNone(app._motion.action)
                    app.restore()
                    self.assertFalse(app._motion.dragging)
                    app._actions_win.destroy();app._actions_win=None
                    # Exercise the actual app's idle/wake/chat/restore hooks without waiting minutes.
                    start=pet.time.monotonic()
                    app._triggers=ActionTriggers(start)
                    app._last_action_check=-100
                    with patch.object(pet,"_system_idle_seconds",return_value=59):
                        app._update_automatic_actions(start+59)
                    self.assertIsNone(app._motion.action)
                    with patch.object(pet,"_system_idle_seconds",return_value=61):
                        app._update_automatic_actions(start+61)
                    self.assertEqual(app._motion.action,"sleep")
                    with patch.object(pet,"_system_idle_seconds",return_value=0):
                        app._update_automatic_actions(start+182)
                    self.assertIsNone(app._motion.action)
                    app._chat_win=object()
                    with patch.object(pet,"_system_idle_seconds",return_value=600):
                        app._update_automatic_actions(start+600)
                    app._chat_win=None
                    self.assertIsNone(app._motion.action)
                    with patch.object(pet.time,"monotonic",return_value=start+601):app.hide()
                    with patch.object(pet.time,"monotonic",return_value=start+632):app.restore()
                    with patch.object(pet,"_system_idle_seconds",return_value=0):
                        app._update_automatic_actions(start+633)
                    self.assertEqual(app._motion.action,"happy")
                    app._ambient_actions_on=False
                    with patch.object(pet,"_system_idle_seconds",return_value=0):
                        app._update_automatic_actions(start+634)
                    self.assertIsNone(app._motion.action)
                    app._save_settings()
                    self.assertFalse(pet.load_settings()["ambient_actions"])
                    app._motion.reset();app._ground.cancel()
                    app._land_on_windows=True
                    app.pet.geometry("+600+40");app.root.update_idletasks()
                    surface=WindowSurface(123,(400,650,1400,1000))
                    now=pet.time.monotonic()
                    with patch.object(pet,"monitor_workarea_of_point",return_value=(0,0,1920,1040)),patch.object(pet,"window_surfaces",return_value=[surface]) as windows:
                        app._drop_to_taskbar(now)
                        self.assertEqual(app._window_support,surface)
                        finish=now+4
                        while app._ground.active and now<finish:
                            now+=.04
                            with patch.object(pet.time,"monotonic",return_value=now):app._animate_pet()
                            app.root.update_idletasks()
                        self.assertTrue(app._grounded)
                        self.assertEqual(app.pet.winfo_y(),round(650-app._char_bbox[3]*app._cur_h/943))
                        old_x=app.pet.winfo_x()
                        moved=WindowSurface(123,(300,680,1300,1030))
                        windows.return_value=[moved]
                        app._update_window_support(now+1);app.root.update_idletasks()
                        self.assertEqual(app.pet.winfo_x(),old_x-100)
                        self.assertEqual(app.pet.winfo_y(),round(680-app._char_bbox[3]*app._cur_h/943))
                        app.on_wheel(SimpleNamespace(delta=-120));app._do_wheel_apply();app.root.update_idletasks()
                        self.assertEqual(app.pet.winfo_y(),round(680-app._char_bbox[3]*app._cur_h/943))
                        windows.return_value=[]
                        app._update_window_support(now+2)
                        self.assertIsNone(app._window_support)
                        self.assertTrue(app._ground.active)
                    app._save_settings()
                    self.assertTrue(pet.load_settings()["land_on_windows"])
                    self.assertFalse((data/"error.log").exists())
                finally:
                    for pending in app.root.tk.call("after","info"):
                        app.root.after_cancel(pending)
                    app.root.destroy()

    def test_extreme_grabs_do_not_clip_visible_pixels(self):
        for ident in ("shizuka-front-motion","shizuka-original-motion"):
            renderer=LayeredRenderer(load_pack(ROOT/"experiments/archived-characters"/ident))
            for anchor in ((.2,.2),(.5,.2),(.8,.2),(.5,.9)):
                for angle in (-19,19):
                    frame=renderer.frame(480,pose=Pose(angle=angle,body_stretch=1.063,anchor=anchor,dy=.03))
                    box=frame.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
                    self.assertGreater(box[0],0,(ident,anchor,angle,box))
                    self.assertGreater(box[1],0,(ident,anchor,angle,box))
                    self.assertLess(box[2],frame.width,(ident,anchor,angle,box))
                    self.assertLess(box[3],frame.height,(ident,anchor,angle,box))
if __name__=="__main__":unittest.main()
