"""Render actual runtime frames for review; no artwork is generated here."""
from pathlib import Path
import sys
import math
from PIL import Image,ImageDraw,ImageFont,ImageChops
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from character_packs import load_pack
from layered_renderer import LayeredRenderer
from pet_motion import MotionController,Pose
out=ROOT/"experiments/archived-characters/shizuka-front-motion/review"
out.mkdir(exist_ok=True)
pack=load_pack(ROOT/"experiments/archived-characters/shizuka-front-motion")
renderer=LayeredRenderer(pack)
font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",19)
def solid(frame):
    bg=Image.new("RGB",frame.size,"#f4f6fb")
    bg.paste(frame.convert("RGB"),mask=frame.getchannel("A").point(lambda a:255 if a>=128 else 0))
    return bg
base=Image.alpha_composite(Image.new("RGBA",(1024,1536)),Image.open(pack.portrait).convert("RGBA"))
neutral=renderer.frame(1536,animated=False)
assert neutral.tobytes()==base.tobytes(),"Neutral cutout assembly differs from original!"
items=[("原图抠件复原",neutral),
       ("闭眼 · 脸型不变",renderer.frame(1536,animated=False,eye_open=0)),
       ("被提起 · 轻微不满",renderer.frame(1536,pose=Pose(expression="lifted")))]
sheet=Image.new("RGB",(1050,480),"#f4f6fb")
for i,(label,frame) in enumerate(items):
    crop=solid(frame).crop((190,80,830,705)).resize((330,323),Image.Resampling.LANCZOS)
    sheet.paste(crop,(i*350+10,50))
    ImageDraw.Draw(sheet).text((i*350+20,405),label,font=font,fill="#253347")
sheet.save(out/"face-check.png")
frames=[]
motion=MotionController()
for i in range(120):
    t=i/20
    if i==14:motion.begin_drag((0,0),(.5,.20),t)
    if 14<=i<48:motion.drag_to((.23*math.sin((t-.7)*7),0),t)
    if i==48:motion.release(t)
    pose=motion.step(t)
    frame=solid(renderer.frame(540,t,pose=pose))
    card=Image.new("RGB",(450,610),"#f4f6fb")
    card.paste(frame,((450-frame.width)//2,20))
    name="提起 / 悬摆" if pose.state=="dragging" else "松手 / 回弹" if pose.state=="landing" else "原画 / 待机"
    ImageDraw.Draw(card).text((135,572),name,font=font,fill="#253347")
    frames.append(card)
frames[0].save(out/"pickup-preview.gif",save_all=True,append_images=frames[1:],duration=50,loop=0,optimize=False,disposal=2)
print(out)
