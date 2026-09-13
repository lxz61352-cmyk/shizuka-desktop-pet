"""Preserve expression provenance and export a representative review frame."""
import json
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
pack=ROOT/"characters/shizuka-side-motion"
out=pack/"review/v053"
with Image.open(out/"sleep.gif") as frames:
    frames.seek(34)
    frames.convert("RGB").save(out/"sleep-check.png")
log=dict(
    reused_tool="built-in image_gen",
    reference="assets/pet.png",
    source="fall-local-edit.png",
    original_output="exec-b87f0bab-f181-4e87-a694-7ea7968392fa.png",
    purpose="Reuse the small surprised mouth from an earlier side-pose expression trial.",
    source_size=[1292,1217],actual_used_region=[576,519,642,559],target_box=[451,399,51,31],
    original_artwork_preserved=True,
    note="No new image generation in 0.5.3. Only the mouth patch is used; the generated face and eyes are not substituted. Existing original wink is retained. See character.json for the feathered mask."
)
(pack/"source/fall-provenance.json").write_text(json.dumps(log,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(out/"sleep-check.png")
