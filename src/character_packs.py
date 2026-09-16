"""Data-only character packs. No Python or JavaScript supplied by a pack is run."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import math

IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class CharacterPack:
    directory: Path
    manifest: dict

    @property
    def id(self):
        return self.manifest["id"]

    @property
    def character_id(self):
        return self.manifest["character_id"]

    @property
    def name(self):
        return self.manifest["name"]

    @property
    def renderer(self):
        return self.manifest["renderer"]

    def asset(self, relative):
        if not isinstance(relative, str) or not relative:
            raise ValueError("Missing asset path")
        path = (self.directory / relative).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise ValueError(f"Asset is missing or outside the character pack: {relative}")
        return path

    @property
    def portrait(self):
        return self.asset(self.manifest["portrait"])

    @property
    def persona(self):
        return self.asset(self.manifest["persona"])

    def data_directory(self, data_root):
        return Path(data_root) / "characters" / self.character_id


def load_pack(directory):
    directory = Path(directory).resolve()
    path = directory / "character.json"
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Character manifest is too large")
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("Character manifest must be an object")
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError("Unsupported character manifest version")
    for field in ("id", "character_id"):
        if not isinstance(manifest.get(field), str) or not IDENTIFIER.fullmatch(manifest[field]):
            raise ValueError(f"Invalid {field}")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ValueError("Character name is required")
    if manifest.get("renderer") not in ("static", "layered"):
        raise ValueError("This release supports static and layered preview renderers; Cubism is not yet integrated")
    pack = CharacterPack(directory, manifest)
    pack.portrait
    pack.persona
    physics=manifest.get('interaction_physics')
    if physics is not None:
        bounds={'drag_still_damping':(.05,2),'drag_still_delay':(.03,1)}
        if not isinstance(physics,dict) or not set(physics)<=set(bounds):
            raise ValueError('Invalid interaction physics')
        for key,value in physics.items():
            low,high=bounds[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
                raise ValueError('Invalid interaction physics value')
    hit_regions=manifest.get('interaction_regions')
    if hit_regions is not None:
        # pet.py 会直接对 region[0]..region[3] 做下标比较，写错就在运行时崩；这里先卡住。
        if not isinstance(hit_regions,dict) or not hit_regions:
            raise ValueError('Invalid interaction regions')
        for name,box in hit_regions.items():
            if not isinstance(name,str) or not IDENTIFIER.fullmatch(name):
                raise ValueError('Invalid interaction region name')
            if (not isinstance(box,list) or len(box)!=4
                    or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>8192 for n in box)
                    or box[0]>=box[2] or box[1]>=box[3]):
                raise ValueError('Interaction region must be [left, top, right, bottom]')
    sleep_anchor=manifest.get('sleep_effect_anchor')
    if sleep_anchor is not None and (not isinstance(sleep_anchor,list) or len(sleep_anchor)!=2
            or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>8192 for n in sleep_anchor)):
        raise ValueError('Invalid sleep effect anchor')
    if pack.renderer == "layered":
        size = manifest.get("canvas_size", [])
        if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or not 1 <= n <= 4096 for n in size):
            raise ValueError("Invalid canvas size")
        frames=manifest.get("expression_frames")
        if frames is not None:
            allowed={"neutral","blink","speak","gentle","lifted","falling","content","content_speak"}
            if not isinstance(frames,dict) or "neutral" not in frames or not set(frames)<=allowed:
                raise ValueError("Invalid expression frame map")
            for relative in frames.values():pack.asset(relative)
        bodies=manifest.get("body_frames")
        if bodies is not None:
            if not isinstance(bodies,dict) or set(bodies)!={"dragging","falling","landing","recover"}:
                raise ValueError("Body frames need all four interaction states")
            for relative in bodies.values():pack.asset(relative)
        activities=manifest.get('activity_frames')
        if activities is not None:
            if not isinstance(activities,dict) or not {'working','reminder','exit'}<=set(activities) or not set(activities)<={'working','reminder','exit','awaiting_answer'}:
                raise ValueError('Activity frames need working, reminder and exit')
            for relative in activities.values():pack.asset(relative)
        question=manifest.get('question_effect')
        if question is not None:
            if not isinstance(question,dict) or set(question)!={'body','icon','xy'} or 'awaiting_answer' not in (activities or {}):
                raise ValueError('Question effect needs an authored awaiting-answer frame')
            pack.asset(question['body']);pack.asset(question['icon'])
            xy=question['xy']
            if not isinstance(xy,list) or len(xy)!=2 or any(type(n) is not int or n<0 or n>=size[i] for i,n in enumerate(xy)):
                raise ValueError('Invalid question effect position')
        recovery=manifest.get('recover_frames')
        if recovery is not None:
            if bodies is None or not isinstance(recovery,list) or not 1<=len(recovery)<=64:
                raise ValueError('Recovery sequence needs body frames and 1-64 entries')
            for frame in recovery:
                if not isinstance(frame,dict) or set(frame)!={'id','path','duration'}:
                    raise ValueError('Invalid recovery frame fields')
                if not isinstance(frame['id'],str) or not IDENTIFIER.fullmatch(frame['id']):
                    raise ValueError('Invalid recovery frame ID')
                duration=frame['duration']
                if type(duration) not in (int,float) or not math.isfinite(duration) or not 1/60<=duration<=2:
                    raise ValueError('Invalid recovery frame duration')
                pack.asset(frame['path'])
            if sum(frame['duration'] for frame in recovery)>12:
                raise ValueError('Recovery sequence is too long')
        profile=manifest.get("motion_profile")
        if profile is not None:
            fields={"angle_scale","angle_limit","head_angle_scale","head_dx_scale","head_dy_scale",
                    "dy_scale","body_stretch_scale","hair_sway_scale","breath_scale"}
            if not isinstance(profile,dict) or not set(profile)<={"default","idle","pat","happy","sleep","dragging","falling","landing","recover"}:
                raise ValueError("Invalid motion profile")
            for settings in profile.values():
                if not isinstance(settings,dict) or not set(settings)<=fields:
                    raise ValueError("Invalid motion profile fields")
                for key,value in settings.items():
                    maximum=45 if key=="angle_limit" else 2
                    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=maximum:
                        raise ValueError("Invalid motion profile value")
        layers = manifest.get("layers", [])
        hinge = manifest.get("body_hinge",0.5)
        if type(hinge) not in (int,float) or not math.isfinite(hinge) or not 0.1 <= hinge <= 0.9:
            raise ValueError("Invalid body hinge")
        rig = manifest.get("rig")
        if rig is not None:
            if not isinstance(rig,dict) or rig.get("type") != "local_mesh_v1":
                raise ValueError("Unsupported local rig")
            def numbers(value,count):
                return isinstance(value,list) and len(value)==count and all(
                    type(n) in (int,float) and math.isfinite(n) and abs(n)<=8192 for n in value)
            if not numbers(rig.get("head_pivot"),2) or not numbers(rig.get("head_band"),2):
                raise ValueError("Invalid head rig")
            if not 0<=rig["head_band"][0]<rig["head_band"][1]<=size[1]:
                raise ValueError("Invalid neck transition")
            if not numbers(rig.get("chest_region"),4) or min(rig["chest_region"][2:])<=0:
                raise ValueError("Invalid chest rig")
            for name in ("hair_regions","leg_regions"):
                regions=rig.get(name)
                if not isinstance(regions,list) or not 0<=len(regions)<=8 or any(not numbers(r,5) for r in regions):
                    raise ValueError("Invalid local regions")
            if any(r[2]<=r[0] or r[3]-r[1]<25 for r in rig["hair_regions"]):
                raise ValueError("Invalid hair region bounds")
            if any(r[2]<=0 or r[3]<=0 for r in rig["leg_regions"]):
                raise ValueError("Invalid leg region bounds")
        if not isinstance(layers, list) or not 1 <= len(layers) <= 100:
            raise ValueError("Layered pack needs 1-100 layers")
        ids = set()
        for layer in layers:
            if not isinstance(layer, dict):
                raise ValueError("Layer must be an object")
            name = layer.get("id", "")
            if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or name in ids:
                raise ValueError("Layer IDs must be unique")
            ids.add(name)
            pack.asset(layer["image"])
            box = layer.get("box", [])
            if not isinstance(box, list) or len(box) != 4 or any(type(n) not in (int, float) or not math.isfinite(n) or abs(n)>8192 for n in box) or box[2] <= 0 or box[3] <= 0:
                raise ValueError("Layer box must be [left, top, width, height]")
            crop = layer.get("source_box")
            if crop is not None and (not isinstance(crop, list) or len(crop) != 4 or
                                    any(type(n) is not int or not 0 <= n <= 8192 for n in crop) or
                                    crop[2] <= crop[0] or crop[3] <= crop[1]):
                raise ValueError("Invalid layer source box")
            polygon = layer.get("mask_polygon")
            if polygon is not None and (not isinstance(polygon,list) or not 3 <= len(polygon) <= 100 or
                any(not isinstance(point,list) or len(point)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>8192 for n in point) for point in polygon)):
                raise ValueError("Invalid layer mask polygon")
            feather = layer.get("mask_feather",0)
            if type(feather) not in (int,float) or not math.isfinite(feather) or not 0 <= feather <= 32:
                raise ValueError("Invalid mask feather")
        # 有画布尺寸时才做范围校验：static 包没有 canvas_size，只能校验形状。
        for name,box in (hit_regions or {}).items():
            if not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
                raise ValueError('Interaction region is outside the canvas: '+name)
        if sleep_anchor is not None and not (0 <= sleep_anchor[0] <= size[0]
                                             and 0 <= sleep_anchor[1] <= size[1]):
            raise ValueError('Sleep effect anchor is outside the canvas')
    return pack


def discover_packs(root,include_archived=False):
    packs, errors = [], []
    for directory in sorted(Path(root).glob("*")):
        if not directory.is_dir() or not (directory / "character.json").is_file():
            continue
        try:
            pack = load_pack(directory)
            if pack.manifest.get("status")=="archived" and not include_archived:
                continue
            if any(p.id == pack.id for p in packs):
                raise ValueError("Duplicate character pack ID")
            packs.append(pack)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{directory.name}: {exc}")
    return packs, errors


def selected_pack(root, settings_path):
    packs, errors = discover_packs(root)
    try:
        chosen = json.loads(Path(settings_path).read_text(encoding="utf-8-sig")).get("character_pack")
    except (OSError, ValueError, AttributeError):
        chosen = None
    # settings.json 指定的包存在就用它（内置包都共用同一个 character_id，
    # 换包不会换数据目录）；指定的包不在磁盘上才退回固定身份。
    if isinstance(chosen, str):
        match = next((p for p in packs if p.id == chosen), None)
        if match is not None:
            return match, errors
    fallback = next((p for p in packs if p.id == "shizuka-side-motion"), None)
    return fallback, errors
