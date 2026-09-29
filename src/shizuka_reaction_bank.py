"""Reaction Bank 检索：从原作反应锚点里挑 0~1 条。

锚点只提供「她会从什么角度看这件事」，不提供 continuation、不指定行为、不要求复述。
选择策略：相关度优先（与用户句有 ≥2 个共同二字片段）；否则以低概率（0.35）从适配质地随机补一条；
最近用过的锚点会被跳过，避免连续复读。
"""
import json
import os
import random
import re

_CACHE = None
_CACHE_PATH = None
RECENT_LIMIT = 8
FALLBACK_PROB = 0.35
_recent = []

DEFAULT_TEXTURES = ("personal_observation", "self_expression", "immediate_reaction", "plain_minimal")


def _default_path():
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                         "characters", "shizuka-side-motion", "reaction_bank.json"))


def load_bank(path=None):
    global _CACHE, _CACHE_PATH
    path = path or _default_path()
    if _CACHE is None or _CACHE_PATH != path:
        with open(path, encoding="utf-8") as handle:
            _CACHE = json.load(handle)
        _CACHE_PATH = path
    return _CACHE


def reset_recent():
    _recent.clear()


def _bigrams(text):
    text = re.sub(r'\s+', '', text or "")
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _overlap(a, b):
    sa, sb = _bigrams(a), _bigrams(b)
    if len(sa) < 2 or len(sb) < 2:
        return 0
    return len(sa & sb)


def anchor_for(text, topic="", rng=None, path=None):
    """返回一条原作反应锚点文本；没有合适的返回 ''。"""
    bank = load_bank(path)
    entries = bank.get("entries") or []
    if not entries:
        return ""
    text = text or ""
    picker = rng or random

    best, best_score = None, 0
    for entry in entries:
        score = _overlap(text, entry.get("text", ""))
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= 3:
        pick = best
    else:
        if picker.random() >= FALLBACK_PROB:
            return ""
        pool = [entry for entry in entries
                if entry.get("reaction_texture") in DEFAULT_TEXTURES
                and entry.get("text") not in _recent]
        if topic == "心菜":
            affection = [entry for entry in entries
                         if entry.get("reaction_texture") == "affection_relational"
                         and entry.get("text") not in _recent]
            if affection:
                pool = affection
        if not pool:
            return ""
        pick = picker.choice(pool)
    if pick.get("text") in _recent:
        return ""
    _recent.append(pick.get("text"))
    while len(_recent) > RECENT_LIMIT:
        _recent.pop(0)
    return pick.get("text") or ""
