"""Original-pixel side-pose cuts; expressions are cropped, never whole-face replacements."""
import argparse,json,shutil
from pathlib import Path
from PIL import Image,ImageDraw,ImageChops
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--pout",required=True)
    parser.add_argument("--fall",required=True)
    args=parser.parse_args()
    pack=ROOT/"characters/shizuka-side-motion"
    for folder in ("layers","source","cubism","review"):
        (pack/folder).mkdir(parents=True,exist_ok=True)
    original=Image.open(ROOT/"assets/pet.png").convert("RGBA")
    shutil.copy2(ROOT/"assets/pet.png",pack/"portrait.png")
    shutil.copy2(ROOT/"assets/pet.png",pack/"source/master-original.png")
    old=ROOT/"experiments/archived-characters/shizuka-original-motion"
    shutil.copy2(old/"persona.json",pack/"persona.json")
    for name in ("blink-generated.png","talk-generated.png"):
        shutil.copy2(old/"source"/name,pack/"source"/name)
    for source,name in ((args.pout,"pout-local-edit.png"),(args.fall,"fall-local-edit.png")):
        target=pack/"source"/name
        if Path(source).resolve()!=target.resolve():
            shutil.copy2(source,target)
    def polygon(points):
        m=Image.new("L",original.size)
        ImageDraw.Draw(m).polygon(points,fill=255)
        return m
    remaining=Image.new("L",original.size,255)
    pieces=[]
    def cut(ident,label,mask):
        nonlocal remaining
        selected=ImageChops.multiply(remaining,mask)
        remaining=ImageChops.subtract(remaining,selected)
        rgba=original.copy()
        rgba.putalpha(ImageChops.multiply(original.getchannel("A"),selected))
        rgba=Image.alpha_composite(Image.new("RGBA",original.size),rgba)
        rgba.save(pack/f"layers/{ident}.png")
        pieces.append(dict(id=ident,image=f"layers/{ident}.png",box=[0,0,1000,943],
            source_box=[0,0,1000,943],group="figure",role=ident,psd_name=label))
    cut("hair-right","原图_画面右侧发梢",polygon([(631,266),(744,250),(785,514),(566,512),(552,484),(596,451),(631,395)]))
    cut("hair-left","原图_画面左侧发梢",polygon([(273,291),(323,282),(345,369),(369,406),(367,442),(415,485),(275,501)]))
    cut("head","原图_头部脸型前发",polygon([(0,0),(1000,0),(1000,505),(548,505),
        (536,478),(524,457),(503,453),(482,459),(458,457),(442,460),(423,482),(396,495),(0,495)]))
    cut("leg-right","原图_画面右腿",polygon([(462,689),(585,681),(670,943),(468,943),(454,735)]))
    cut("leg-left","原图_画面左腿",polygon([(350,688),(463,688),(463,943),(300,943)]))
    cut("skirt","原图_裙摆",polygon([(0,626),(1000,626),(1000,710),(0,710)]))
    cut("body","原图_身体与抱臂",Image.new("L",original.size,255))
    assembled=Image.new("RGBA",original.size)
    for spec in pieces:assembled.alpha_composite(Image.open(pack/spec["image"]))
    base=Image.alpha_composite(Image.new("RGBA",original.size),original)
    assert assembled.tobytes()==base.tobytes()
    legacy=json.loads((old/"character.json").read_text(encoding="utf-8"))
    pieces.extend(legacy["layers"][1:])
    pieces.append(dict(id="pout",image="source/pout-local-edit.png",
        box=[451,399,51,31],source_box=[576,501,625,538],group="figure",role="lift_mouth",
        mask_polygon=[[3,3],[47,3],[48,27],[3,27]],mask_feather=2,psd_name="提起_持续撇嘴_局部覆盖"))
    pieces.append(dict(id="fall-mouth",image="source/fall-local-edit.png",
        box=[451,399,51,31],source_box=[576,519,642,559],group="figure",role="fall_mouth",
        mask_polygon=[[3,3],[47,3],[48,27],[3,27]],mask_feather=2,psd_name="下落_轻微惊讶_局部嘴型"))
    manifest=dict(schema_version=1,id="shizuka-side-motion",character_id="shizuka",
        name="静香 · 侧面多动作",description="保留原姿势：左键摸头、打盹 zzz、连跳两次；右键提起撇嘴，松手轻微惊讶，落回任务栏。",
        renderer="layered",portrait="portrait.png",persona="persona.json",canvas_size=[1000,943],
        body_hinge=.55,rig=dict(type="local_mesh_v1",head_pivot=[474,470],head_band=[440,545],
            hair_regions=[[273,278,399,510,-1],[560,235,755,520,1]],
            chest_region=[464,566,102,79],leg_regions=[[442,698,52,163,-1],[521,699,72,143,1]]),
        interaction_regions=dict(head_pat=[330,110,675,275]),sleep_effect_anchor=[720,280],layers=pieces)
    (pack/"character.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PASS: seven original-pixel cuts reconstruct exactly; eleven layers including local expressions.")
if __name__=="__main__":main()
