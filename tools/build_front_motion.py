"""Cut existing artwork with complementary masks; never redraw or resize its parts."""
from pathlib import Path
import argparse
import json
import shutil
from PIL import Image, ImageDraw, ImageChops

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--blink",required=True)
    parser.add_argument("--talk",required=True)
    parser.add_argument("--lift",required=True)
    args=parser.parse_args()
    pack=ROOT/"experiments/archived-characters/shizuka-front-motion"
    for name in ("layers","source","cubism"):
        (pack/name).mkdir(parents=True,exist_ok=True)
    master=ROOT/"experiments/archived-characters/shizuka-lab/source/master-alpha-v2.png"
    shutil.copy2(master,pack/"portrait.png")
    shutil.copy2(master,pack/"source/master-original.png")
    shutil.copy2(ROOT/"experiments/archived-characters/shizuka-lab/persona.json",pack/"persona.json")
    original=Image.open(master).convert("RGBA")
    mask=Image.new("L",original.size,0)
    # Split follows the bottom of the hair and chin. Both cuts retain canvas coordinates.
    ImageDraw.Draw(mask).polygon([(0,0),(1024,0),(1024,692),(632,692),
        (615,666),(580,649),(548,630),(530,624),(473,624),
        (451,637),(417,654),(393,678),(379,694),(0,694)],fill=255)
    head=original.copy()
    head.putalpha(ImageChops.multiply(original.getchannel("A"),mask))
    body=original.copy()
    body.putalpha(ImageChops.multiply(original.getchannel("A"),ImageChops.invert(mask)))
    head=Image.alpha_composite(Image.new("RGBA",original.size),head)
    body=Image.alpha_composite(Image.new("RGBA",original.size),body)
    head.save(pack/"layers/head-original.png")
    body.save(pack/"layers/body-original.png")
    assembled=Image.alpha_composite(body,head)
    base=Image.alpha_composite(Image.new("RGBA",original.size),original)
    # Transparent RGB is irrelevant; every visible pixel must be exactly the same.
    assert ImageChops.difference(base,assembled).convert("RGB").getbbox() is None
    assert base.getchannel("A").tobytes()==assembled.getchannel("A").tobytes()
    layers=[]
    for ident,label in (("body","身体_原图抠取"),("head","头部含头发脸型_原图抠取")):
        layers.append(dict(id=ident,image=f"layers/{ident}-original.png",
            box=[0,0,1024,1536],source_box=[0,0,1024,1536],group="figure",
            role=ident,psd_name=label))
    for kind,path in (("blink",args.blink),("talk",args.talk),("lift",args.lift)):
        shutil.copy2(path,pack/f"source/{kind}-local-edit.png")
    def patch(ident,source,box,role,polygon,label):
        x,y,w,h=box
        layers.append(dict(id=ident,image=f"source/{source}-local-edit.png",
            box=box,source_box=[x,y,x+w,y+h],group="figure",role=role,
            mask_polygon=polygon,mask_feather=2,psd_name=label))
    # Local eye masks avoid the unchanged fringe and keep face/chin boundaries intact.
    patch("blink-left","blink",[312,410,149,137],"blink_overlay",
        [[9,34],[29,13],[62,8],[108,27],[131,47],[143,64],[144,111],[119,133],[59,135],[26,116],[11,78]],
        "闭眼_画面左_局部替换")
    patch("blink-right","blink",[542,404,134,140],"blink_overlay",
        [[5,53],[17,29],[45,10],[92,8],[113,24],[131,50],[129,97],[106,128],[58,136],[23,123],[6,94]],
        "闭眼_画面右_局部替换")
    patch("talk","talk",[463,550,72,53],"talk_overlay",
        [[4,4],[66,4],[69,45],[6,48]],"说话_局部嘴型")
    patch("lift-mouth","lift",[467,548,68,38],"lift_mouth",
        [[4,4],[62,4],[63,33],[5,34]],"被提起_轻微不满嘴型")
    # Keep the original eyes and eyebrows; the tiny pout fits her composed character.
    manifest=dict(schema_version=1,id="shizuka-front-motion",character_id="shizuka",
        name="静香 · 正面原画动态",description="最初立绘原图抠件：保留脸型与头发；拖动悬摆、松手回弹和小动作。",
        renderer="layered",portrait="portrait.png",persona="persona.json",
        canvas_size=[1024,1536],body_hinge=0.455,layers=layers)
    (pack/"character.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Original-cut assembly: visible pixels and alpha exactly match the master.")
    print(pack)
if __name__=="__main__":
    main()
