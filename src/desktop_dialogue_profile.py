"""Explicit desktop/Weixin trial selection, separate from personal settings."""
import json
import os
from pathlib import Path

PROFILE = 's31r-o1b'
LATEST_PROFILE = 'daily-examples-v1'
PROFILES = (PROFILE, LATEST_PROFILE)
LATEST_CARD = 'characters/shizuka-side-motion/persona.daily-examples.v1.json'
LABEL = 'S3.1-R / O1-B · 关闭思考'
FILE_NAME = 'desktop-dialogue.json'


def load(root):
    value = os.environ.get('SHIZUKA_DIALOGUE_PROFILE')
    if value is None:
        path = Path(root) / FILE_NAME
        value = json.loads(path.read_text(encoding='utf-8')).get('profile', '') if path.exists() else ''
    if value not in ('', 'legacy', *PROFILES):
        raise ValueError('未知的桌面对话版本：' + str(value))
    return value if value in PROFILES else ''


def switch_overrides(profile):
    if profile not in PROFILES:
        return {}
    return dict(enhanced_dialogue_v2=True, dialogue_architecture_v2=False,
                tone_priority_v1=False, tone_priority_v2=False, tone_local_guard_v1=False)


def metadata(profile):
    if profile not in PROFILES:
        return {}
    from dialogue_context import REVISION
    from reply_turn import REVISION as REPLY_REVISION
    result = dict(dialogue_profile=profile, persona_revision='s31-r', outer_variant='no_frame',
                  natural_chat=True, reasoning_effort='none', context_revision=REVISION,
                  reply_pipeline_revision=REPLY_REVISION)
    if profile == LATEST_PROFILE:
        import hashlib
        from enhanced_dialogue import ROOT
        from response_fit import REVISION as FIT_REVISION
        from runtime_pre_reply_affect import EXPRESSION_REVISION
        result.update(persona_revision='daily-examples-v1',
                      persona_sha256=hashlib.sha256((ROOT / LATEST_CARD).read_bytes()).hexdigest(),
                      speech_revision='s31r-persona-relaxed-v1',
                      affect_revision='balanced-affect-v2',
                      response_fit_revision=FIT_REVISION,
                      affect_expression_revision=EXPRESSION_REVISION)
    return result


def persona_core(profile, pack=None):
    from enhanced_dialogue import ROOT, persona_core as original
    if profile == LATEST_PROFILE:
        from persona_relaxed_trial import persona_core as compile_candidate
        return compile_candidate(ROOT / LATEST_CARD, pack)
    if profile != PROFILE:
        return original(pack)
    from dialogue_architecture_v2 import persona_core as compile_card
    return compile_card(ROOT / 'characters/shizuka-side-motion/persona.s31-r.candidate.json', pack)


def output_blocks(profile, text, history):
    from enhanced_dialogue import output_blocks as original
    return original(text, history, natural_chat=True, outer_variant='no_frame') if profile in PROFILES else original(text, history)


def compose_messages(profile, *args, **kwargs):
    if profile == LATEST_PROFILE:
        from persona_relaxed_trial import compose_messages as compose
    else:
        from enhanced_dialogue import compose_messages as compose
    return compose(*args, **kwargs)


def generate(profile, *args, **kwargs):
    if profile == LATEST_PROFILE:
        from persona_relaxed_trial import generate as send
    else:
        from weixin_segments import generate as send
    return send(*args, **kwargs)
