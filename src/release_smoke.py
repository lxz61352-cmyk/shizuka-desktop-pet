"""Offline verification for the actual frozen EXE in a disposable extracted copy."""
import json
import sys
import subprocess
import time
from pathlib import Path
from unittest.mock import patch
from character_packs import discover_packs
from pet_motion import Pose
from pet_surfaces import window_surfaces


def run(pet):
    report=Path(sys.argv[sys.argv.index("--report")+1]) if "--report" in sys.argv else Path(pet.DATA_DIR)/"release-check.json"
    errors=[]
    checks=[]
    with patch.object(pet,"read_api_key",return_value=""):
        app=pet.DeskPet()
        app.root.report_callback_exception=lambda *args:errors.append(str(args[1]))
        try:
            app.root.update()
            assert Path(pet.ROOT_DIR).resolve()==Path(sys.executable).resolve().parent
            packs,issues=discover_packs(pet.CHARACTERS_DIR)
            assert not issues and {p.id for p in packs}=={"shizuka-side-motion","shizuka-classic"}
            assert app._character_pack.id=="shizuka-side-motion"
            assert app._animator is not None
            for expression in ("neutral","lifted","falling"):
                app._animator.frame(480,pose=Pose(expression=expression),color_key=True)
            checks.append("Portable paths, active packs, all local expressions")
            app.show_characters();app.root.update()
            app.show_actions();app.root.update()
            app.play_action("pat");app._motion.begin_pet(.4,0);app._motion.pet_to(.55)
            app._animator.frame(480,pose=app._motion.step(.1),color_key=True)
            app._motion.end_pet(.2)
            checks.append("Tk menus, ImageTk, petting renderer")
            from openai import OpenAI
            client=OpenAI(api_key="offline-self-test",base_url="http://127.0.0.1:1")
            client.close()
            checks.append("Bundled OpenAI client imports without network")
            fixture=subprocess.Popen([sys.executable,"--surface-fixture"],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            try:
                deadline=time.monotonic()+5
                support=None
                while time.monotonic()<deadline:
                    support=next((s for s in window_surfaces() if s.pid==fixture.pid),None)
                    if support:break
                    app.root.update();time.sleep(.05)
                assert support is not None,"Native window enumeration missed the fixture"
                app._motion.reset();app._ground.cancel()
                app._land_on_windows=True
                scale=app._cur_h/app.pet_img_full.height
                left,top,right,bottom=support.bounds
                x=round((left+right)/2-(app._char_bbox[0]+app._char_bbox[2])*.5*scale)
                y=round(top-app._char_bbox[3]*scale-80)
                app.pet.geometry(f"+{x}+{y}");app.root.update_idletasks()
                now=time.monotonic();app._drop_to_taskbar(now)
                assert app._window_support and app._window_support.pid==fixture.pid
                for _ in range(100):
                    now+=.04
                    with patch.object(pet.time,"monotonic",return_value=now):app._animate_pet()
                    app.root.update_idletasks()
                    if not app._ground.active:break
                assert app._grounded and abs(app.pet.winfo_y()-(top-app._char_bbox[3]*scale))<=1
                checks.append("Native external-window detection and actual Tk landing")
            finally:
                if fixture.poll() is None:fixture.terminate()
                fixture.wait(timeout=5)
            assert not errors,errors
        finally:
            for pending in app.root.tk.call("after","info"):
                app.root.after_cancel(pending)
            app.root.destroy()
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(dict(version=pet.APP_VERSION,frozen=bool(getattr(sys,"frozen",False)),checks=checks,errors=errors),indent=2)+"\n",encoding="utf-8")
    return 0
