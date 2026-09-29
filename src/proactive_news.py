"""Low-frequency public RSS sharing: dated evidence and original links only."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import html
import re
import threading
import time
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

FEEDS = (('IT之家', 'https://www.ithome.com/rss/', 'www.ithome.com'),
         ('中国新闻网', 'https://www.chinanews.com.cn/rss/scroll-news.xml', 'www.chinanews.com.cn'))
# A light sharing pool, not a filter on what users may ask about in conversation.
LIGHT = re.compile(r'游戏|动画|动漫|电影|音乐|演唱会|展览|博物馆|考古|动物|植物|熊猫|航天|太空|天文|卫星|月球|科学|科技|机器人|数码|相机|耳机|手机|电脑|公园|文旅|美食|文化|旅游')
HEAVY = re.compile(r'死亡|遇难|暴力|杀|袭击|战争|军事|军队|性侵|色情|诈骗|灾情|爆炸|枪|毒品|选举|总统|主席|政治|股价|股票|投资|理财|彩票|广告|优惠|领券|补贴|售价|低至|促销|税收|产能|战略合作')
_cache = {}
_lock = threading.Lock()


def _text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def parse_feed(body, source, host, now):
    if not body or len(body) > 2_000_000 or '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper(): return []
    try: root = ET.fromstring(body)
    except ET.ParseError: return []
    result = []
    for item in root.findall('./channel/item')[:80]:
        title = _text(item.findtext('title'))
        url = (item.findtext('link') or '').strip()
        try:
            parsed = urlparse(url)
            port = parsed.port
            date = parsedate_to_datetime(item.findtext('pubDate') or '')
            if date.tzinfo is None: continue
            at = date.timestamp()
        except (ValueError, TypeError, OverflowError): continue
        if (parsed.scheme != 'https' or parsed.hostname != host or parsed.username or port not in (None, 443)
                or not 0 <= now-at <= 36*3600 or not LIGHT.search(title) or HEAVY.search(title)): continue
        description = _text(item.findtext('description'))[:400]
        if HEAVY.search(description): continue
        result.append(dict(topic='news:'+hashlib.sha256(url.encode()).hexdigest()[:20],
                           title=title[:180], text=description or title[:180], url=url, source=source,
                           published_at=at, published=datetime.fromtimestamp(at).astimezone().isoformat(timespec='minutes'),
                           evidence='公开RSS标题和摘要；未读取全文，不能补出摘要之外的细节'))
    return result


def fresh_items(now=None, cancelled=lambda: False):
    from weather import http_get
    now = time.time() if now is None else now
    result = []
    for source, url, host in FEEDS:
        if cancelled(): return []
        with _lock: cached = _cache.get(url)
        if cached and 0 <= now-cached[0] < 3600:
            body = cached[1]
        else:
            body = http_get(url, 5)
            with _lock: _cache[url] = (now, body)
        if cancelled(): return []
        result.extend(parse_feed(body, source, host, now))
    return result
