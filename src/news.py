"""当日新闻标题（60s 读报接口），供 news 意图播报用。"""
import json

from weather import http_get


def get_news(limit=15):
    """取当日新闻标题列表（60s 读报，viki.moe）。失败返回 []。"""
    try:
        txt = http_get("https://60s.viki.moe/v2/60s", 10)
        d = json.loads(txt)
        news = (d.get("data") or {}).get("news") or []
        return [str(x).strip() for x in news if str(x).strip()][:limit]
    except Exception:
        return []
