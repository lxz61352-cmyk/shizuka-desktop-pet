"""原作行为案例检索：按（behavior, topic）取少量案例。

案例只用于「参考反应方式」，检索结果交给 shizuka_inject 拼装；
不调模型、不用 embedding，内存索引一次加载。
"""
import json
import os
import random

_CACHE = None
_CACHE_PATH = None


def load_examples(path):
    global _CACHE, _CACHE_PATH
    if _CACHE is None or _CACHE_PATH != path:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        index = {}
        for entry in data.get("entries") or []:
            behavior = entry.get("behavior")
            if not behavior:
                continue
            index.setdefault((behavior, entry.get("topic")), []).append(entry)
            index.setdefault((behavior, None), []).append(entry)
        _CACHE = index
        _CACHE_PATH = path
    return _CACHE


def retrieve(behavior, topic, n=2, rng=None, path=None):
    if not path:
        path = _default_path()
    index = load_examples(path)
    pool = index.get((behavior, topic)) or index.get((behavior, None)) or []
    if not pool:
        return []
    picker = rng or random
    return picker.sample(pool, min(n, len(pool)))


def retrieve_by_topic(topic, n=2, rng=None, path=None):
    """按话题取案例（不看行为标签）——行为方向由模型自己定，系统只给情境参考。"""
    if not path:
        path = _default_path()
    index = load_examples(path)
    pool = [entry for (behavior, entry_topic), entries in index.items()
            for entry in entries if entry_topic == topic]
    if not pool:
        pool = [entry for (behavior, entry_topic), entries in index.items()
                for entry in entries if entry_topic == "日常"]
    if not pool:
        return []
    picker = rng or random
    return picker.sample(pool, min(n, len(pool)))


def _default_path():
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                         "characters", "shizuka-side-motion",
                                         "behavior-examples.json"))
