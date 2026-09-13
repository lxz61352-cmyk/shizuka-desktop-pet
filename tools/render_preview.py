"""Export a short preview of the same renderer used by the desktop pet."""
from pathlib import Path
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from character_packs import load_pack
from layered_renderer import LayeredRenderer

pack=load_pack(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/"experiments/archived-characters/shizuka-original-motion")
renderer=LayeredRenderer(pack)
frames=[]
for i in range(72):
    t=i/16
    frame=renderer.frame(450,t,speaking=1<t<2.8)
    background=Image.new("RGBA",frame.size,"#f3f5fa")
    background.alpha_composite(frame)
    frames.append(background.convert("RGB"))
frames[0].save(pack.directory/"preview.gif",save_all=True,append_images=frames[1:],duration=63,loop=0)
print(pack.directory/"preview.gif")
