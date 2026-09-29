"""Reaction Pattern 检索（P2c-8.1 原型，仅离线单测；未接 runtime）。

流程：用户输入 → 情境 slots（target / scene_type / expressions）→ Pattern Bank 匹配。
核心约束：没有合适条目时返回 None——绝不退化为随机日常台词（P2c-8 的教训）。
"""
import json
import os
import random
import re

_CACHE = None
_CACHE_PATH = None

SPECIAL_SCENES = ('compliment_reaction', 'recollection', 'stage_talk', 'repeated_topic')

MEMORY_RE = re.compile(r'以前|小时候|当时|曾经|回忆|那时|过去|之前')
EMOTION_RE = re.compile(r'累|烦|难受|开心|高兴|不安|担心|害怕|难过|生气|紧张|后悔|空落|提不起劲|没精神|没力气|疲惫')
ENV_RE = re.compile(r'天气|下雨|雨声|云|阳光|外面|季节|空气|风(?=好大|大)')
COMPLIMENT_RE = re.compile(r'夸我|被夸|表扬|夸了')
ACHIEVE_RE = re.compile(r'终于|做到了|搞定了|做完了|写完了|完成了')
STAGE_RE = re.compile(r'演出|舞台|演技|排练|剧本|角色|演员|试镜|台词|公演|剧团|表演')
KOKONA_RE = re.compile(r'心菜')
OTHER_RE = re.compile(r'有人|老板|同事|朋友|老师|陌生人')
FOOD_RE = re.compile(r'拉面|吃|菜|饭|面|咖啡|茶|甜|外卖|食堂')


def _default_path():
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                         "characters", "shizuka-side-motion", "reaction_patterns.json"))


def load_bank(path=None):
    global _CACHE, _CACHE_PATH
    path = path or _default_path()
    if _CACHE is None or _CACHE_PATH != path:
        with open(path, encoding="utf-8") as handle:
            _CACHE = json.load(handle)
        _CACHE_PATH = path
    return _CACHE


def scene_slots(text):
    """用户输入 → 期望的 (target, scene_type, expressions)；判不出返回 None（不 grounding）。"""
    text = (text or "").strip()
    if not text:
        return None
    if MEMORY_RE.search(text):
        return {"target": "memory", "scene_type": "recollection",
                "expressions": ["self_expression", "observation", "minimal"]}
    if KOKONA_RE.search(text):
        return {"target": "other_person", "scene_type": "warm_moment",
                "expressions": ["warm_response", "observation"]}
    if STAGE_RE.search(text):
        return {"target": "task", "scene_type": "stage_talk",
                "expressions": ["self_expression", "observation"]}
    if COMPLIMENT_RE.search(text):
        return {"target": "self", "scene_type": "compliment_reaction",
                "expressions": ["observation", "light_tease", "warm_response"]}
    if EMOTION_RE.search(text):
        return {"target": "emotion", "scene_type": "emotional_moment",
                "expressions": ["warm_response", "minimal", "observation"]}
    if ENV_RE.search(text):
        return {"target": "environment", "scene_type": "observation_scene",
                "expressions": ["observation", "self_expression", "immediate_reaction"]}
    if ACHIEVE_RE.search(text):
        return {"target": "self", "scene_type": "achievement",
                "expressions": ["observation", "light_tease", "self_expression"]}
    if FOOD_RE.search(text):
        return {"target": "object", "scene_type": "everyday_event",
                "expressions": ["observation", "light_tease", "self_expression"]}
    if OTHER_RE.search(text):
        return {"target": "other_person", "scene_type": "everyday_event",
                "expressions": ["observation", "light_tease", "immediate_reaction"]}
    return None


def _eligible(entry, slots):
    if slots["scene_type"] in SPECIAL_SCENES and entry.get("scene_type") == slots["scene_type"]:
        return True
    return (entry.get("target") == slots["target"]
            and entry.get("expression") in slots["expressions"])


def retrieve_pattern(text, rng=None, path=None):
    """返回一条匹配的 Pattern 条目；没有合适的返回 None。"""
    slots = scene_slots(text)
    if not slots:
        return None
    entries = load_bank(path).get("entries") or []
    candidates = [entry for entry in entries
                  if _eligible(entry, slots) and entry.get("continuation_risk", 0) <= 1]
    if not candidates:
        return None

    def score(entry):
        value = 0.0
        if entry.get("scene_type") == slots["scene_type"]:
            value += 2
        if entry.get("target") == slots["target"]:
            value += 1
        if entry.get("expression") in slots["expressions"]:
            value += 1
        if entry.get("scene_dependency") == "low":
            value += 0.5
        return value

    best = max(score(entry) for entry in candidates)
    top = [entry for entry in candidates if score(entry) == best]
    return (rng or random).choice(top)
