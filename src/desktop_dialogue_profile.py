"""Explicit desktop/Weixin trial selection, separate from personal settings."""
import json
import os
from pathlib import Path

PROFILE = 's31r-o1b'
LABEL = 'S3.1-R / O1-B · 关闭思考'
FILE_NAME = 'desktop-dialogue.json'


def load(root):
    value = os.environ.get('SHIZUKA_DIALOGUE_PROFILE')
    if value is None:
        path = Path(root) / FILE_NAME
        value = json.loads(path.read_text(encoding='utf-8')).get('profile', '') if path.exists() else ''
    if value not in ('', 'legacy', PROFILE):
        raise ValueError('未知的桌面对话版本：' + str(value))
    return PROFILE if value == PROFILE else ''


def switch_overrides(profile):
    if profile != PROFILE:
        return {}
    return dict(enhanced_dialogue_v2=True, dialogue_architecture_v2=False,
                tone_priority_v1=False, tone_priority_v2=False, tone_local_guard_v1=False)


def metadata(profile):
    if profile != PROFILE:
        return {}
    from dialogue_context import REVISION
    return dict(dialogue_profile=PROFILE, persona_revision='s31-r', outer_variant='no_frame',
                natural_chat=True, reasoning_effort='none', context_revision=REVISION)


def persona_core(profile, pack=None):
    from enhanced_dialogue import ROOT, persona_core as original
    if profile != PROFILE:
        return original(pack)
    from dialogue_architecture_v2 import persona_core as compile_card
    return compile_card(ROOT / 'characters/shizuka-side-motion/persona.s31-r.candidate.json', pack)


def output_blocks(profile, text, history):
    from enhanced_dialogue import output_blocks as original
    return original(text, history, natural_chat=True, outer_variant='no_frame') if profile == PROFILE else original(text, history)
