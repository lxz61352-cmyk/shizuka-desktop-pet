"""Proof frames from the side rig and the same gravity controller as the app."""
from pathlib import Path
import math,sys,time
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from character_packs import load_pack
from layered_renderer import LayeredRenderer
from pet_motion import MotionController,Pose
from pet_ground import GroundMotion
pack=load_pack(ROOT/"characters/shizuka-side-motion")
out=pack.directory/"review/v056";out.mkdir(parents=True,exist_ok=True)
renderer=LayeredRenderer(pack)
font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",18)
height=420
def card(frame,label,y=18,ground=None):
    bg=Image.new("RGB",(510,560),"#f3f5fa")
    d=ImageDraw.Draw(bg)
    if ground is not None:
        d.rectangle((0,ground,510,559),fill="#dce5f3")
        d.line((0,ground,510,ground),fill="#8aa3c5",width=2)
    bg.paste(frame.convert("RGB"),((510-frame.width)//2,round(y)),mask=frame.getchannel("A"))
    d.text((26,525),label,font=font,fill="#2c425f")
    return bg
def savegif(name,frames):
    frames[0].save(out/name,save_all=True,append_images=frames[1:],duration=50,loop=0,optimize=False,disposal=2)
frames=[]
for action,label in (("pat","左键按住头顶来回摸头"),("sleep","空闲一分钟：打盹、zzz 浮起"),("happy","双击身体：跳两下，随后站稳")):
    motion=MotionController();motion.step(0);motion.trigger(action,0)
    if action=="pat":motion.begin_pet(.4,0)
    action_frames=[]
    for i in range(round((5 if action=="pat" else motion.ACTIONS[action]+.35)*20)):
        t=i/20
        if action=="pat":
            if t<4:motion.pet_to(.4+(.045 if t<2 else .17)*math.sin(t*4))
            elif i==80:motion.end_pet(t)
        pose=motion.step(t)
        action_frames.append(card(renderer.frame(height,t,pose=pose),label))
    savegif(action+".gif",action_frames)
    if action=="sleep":
        action_frames[34].save(out/"sleep-check.png")
    frames.extend(action_frames)
savegif("local-actions.gif",frames)
motion=MotionController();ground=GroundMotion();motion.step(0)
motion.begin_drag((0,0),(.5,.2),0)
neutral=renderer.frame(height,animated=False)
floor=502;neutral_foot=neutral.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()[3]
target=floor-neutral_foot
frames=[]
for i in range(116):
    t=i/20
    if i<64:
        motion.drag_to((.15*math.sin(t*6) if t<1.6 else 0,0),t)
        y=target-140
    if i==64:
        motion.release(t,falling=True);ground.start(y,target,t,gravity=height*6)
    if ground.active:
        step=ground.step(t);y=step.y
        if step.impact:motion.land(t)
    pose=motion.step(t)
    label="右键提起：始终保持撇嘴" if i<64 else "右键松手：轻微惊讶 → 着地恢复"
    frames.append(card(renderer.frame(height,t,pose=pose),label,y,floor))
savegif("pickup-fall.gif",frames)
sheet=Image.new("RGB",(1040,465),"#f3f5fa")
for i,(label,pose) in enumerate((("原版侧面",Pose()),("提起撇嘴",Pose(expression="lifted",state="dragging")),("下落轻微惊讶",Pose(expression="falling",state="falling")))):
    frame=renderer.frame(943,pose=pose)
    bg=Image.new("RGB",frame.size,"#f3f5fa")
    bg.paste(frame.convert("RGB"),mask=frame.getchannel("A").point(lambda a:255 if a>=128 else 0))
    crop=bg.crop((270,70,755,560)).resize((320,323),Image.Resampling.LANCZOS)
    sheet.paste(crop,(i*345+10,25))
    ImageDraw.Draw(sheet).text((i*345+30,390),label,font=font,fill="#2c425f")
sheet.save(out/"side-check.png")
started=time.perf_counter()
motion=MotionController();motion.trigger("sleep",0)
for i in range(60):renderer.frame(480,i/25,pose=motion.step(i/25),color_key=True)
print("Side rig ms/frame:",round((time.perf_counter()-started)*1000/60,1))
print(out)
