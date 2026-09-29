# -*- coding: utf-8 -*-
"""Provider profiles for the enhanced_v2 candidate (P4.1).

A profile describes only protocol, parameter mapping, capabilities, rate limit
and verification status. It contains no persona or tone text. Profiles are
selected explicitly by the `provider_profile` setting; unknown names fail and
no model string is ever auto-detected.
"""
import json
import os
from pathlib import Path

DEFAULT_PROFILE = "custom"
SETTING_KEY = "provider_profile"
ALIASES = {
    "kimi-k2.6": "kimi",
    "deepseek-flash": "deepseek",
}

PROFILES = {
    "deepseek": {
        "key": "deepseek",
        "provider": "DeepSeek",
        "base": "https://api.deepseek.com",
        "model": "deepseek-v4-flash-vision-exp",
        "mode": "responses",
        "temperature": 0.7,
        "max_key": "max_tokens",
        "max_value": 6000,
        "rpm": None,
        "min_interval": 0.0,
        "reasoning_isolation": True,
        "status": "basic_compatible",
    },
    "kimi": {
        "key": "kimi",
        "provider": "Kimi / Moonshot OpenAI Compatible",
        "base": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.6",
        "mode": "chat",
        "temperature": 1,
        "max_key": "max_completion_tokens",
        "max_value": 6000,
        "rpm": 3,
        "min_interval": 25.0,
        "reasoning_isolation": True,
        "status": "recommended_candidate",
    },
    "custom": {
        "key": "custom",
        "provider": "custom",
        "base": None,
        "model": None,
        "mode": None,
        "temperature": None,
        "max_key": None,
        "max_value": None,
        "rpm": None,
        "min_interval": 0.0,
        "reasoning_isolation": False,
        "status": "unverified",
    },
}


class ProfileError(ValueError):
    """Unknown or invalid provider profile. Raised before any request."""


def resolve(name):
    """Resolve an explicit profile name; unknown names raise (no fallback)."""
    key = str(name or "").strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROFILES:
        raise ProfileError("unknown provider profile: %r" % name)
    return dict(PROFILES[key])


def from_settings(settings):
    return resolve((settings or {}).get(SETTING_KEY, DEFAULT_PROFILE))


def apply_overrides(kwargs, profile):
    """Return kwargs with the profile's legal parameters applied.

    Only temperature and the max-token field are touched; exactly one token
    field is sent. Custom profiles change nothing.
    """
    result = dict(kwargs)
    if not profile or profile.get("key") == "custom":
        return result
    model = profile.get("model")
    if model:
        result["model"] = model
    temperature = profile.get("temperature")
    if temperature is not None:
        result["temperature"] = temperature
    max_key = profile.get("max_key")
    if max_key:
        result.pop("max_tokens", None)
        result.pop("max_completion_tokens", None)
        result[max_key] = profile.get("max_value")
    return result


def _log_path():
    data_dir = os.environ.get("SHIZUKA_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "provider.log"
    return Path(__file__).resolve().parents[1] / "data" / "provider.log"


def log_request(profile, kwargs, path=None):
    """Append a non-sensitive request line (no key, no messages)."""
    try:
        record = {
            "profile": profile.get("key"),
            "provider": profile.get("provider"),
            "model": kwargs.get("model"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "max_completion_tokens": kwargs.get("max_completion_tokens"),
            "stream": bool(kwargs.get("stream")),
        }
        target = Path(path) if path else _log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except Exception:
        return False


def reasoning_text_of(delta):
    """Extract reasoning text from dict / pydantic / attribute shapes.

    Returns "" when absent; never raises. Callers must not store the text.
    """
    if delta is None:
        return ""
    for name in ("reasoning_content", "reasoning"):
        if isinstance(delta, dict):
            value = delta.get(name)
        else:
            value = getattr(delta, name, None)
        if isinstance(value, str) and value:
            return value
    dump = getattr(delta, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
        except Exception:
            data = None
        if isinstance(data, dict):
            for name in ("reasoning_content", "reasoning"):
                value = data.get(name)
                if isinstance(value, str) and value:
                    return value
    return ""


def reasoning_stats(delta):
    text = reasoning_text_of(delta)
    return {"present": bool(text), "chars": len(text)}


_RECORDS = []


def note_reasoning(case_id, delta):
    stats = reasoning_stats(delta)
    if stats["present"]:
        _RECORDS.append({"case_id": case_id, **stats})
    return stats


def reasoning_records():
    return list(_RECORDS)


class ReasoningCountedStream:
    """Counts reasoning fields while yielding chunks byte-for-byte unchanged."""

    def __init__(self, stream, case_id=""):
        self._stream = stream
        self._case_id = case_id

    def __enter__(self):
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, *exc):
        exit_fn = getattr(self._stream, "__exit__", None)
        if exit_fn is not None:
            return exit_fn(*exc)
        self.close()
        return False

    def __iter__(self):
        for chunk in self._stream:
            for choice in getattr(chunk, "choices", None) or []:
                note_reasoning(self._case_id, getattr(choice, "delta", None))
            yield chunk

    def close(self):
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


def wrap_reasoning(stream, case_id=""):
    return ReasoningCountedStream(stream, case_id)
