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
        # Preserve the original Shizuka files in place, including all existing memories.
        return Path(data_root) if self.character_id == "shizuka" else Path(data_root) / "characters" / self.character_id


def load_pack(directory):
    directory = Path(directory).resolve()
    path = directory / "character.json"
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Character manifest is too large")
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("Character manifest must be an object")
    if manifest.get("schema_version") != 1:
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
    if pack.renderer == "layered":
        size = manifest.get("canvas_size", [])
        if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or not 1 <= n <= 4096 for n in size):
            raise ValueError("Invalid canvas size")
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
                if not isinstance(regions,list) or not 1<=len(regions)<=8 or any(not numbers(r,5) for r in regions):
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
    fallback = next((p for p in packs if p.id == "shizuka-side-motion"),
                    next((p for p in packs if p.id == "shizuka-classic"),None))
    return next((p for p in packs if p.id == chosen), fallback), errors
