"""本机定位与天气查询：外网可达走 Open-Meteo，仅国内走中国气象局，互为兜底。"""
import gzip as _gzip
import json
import time
import urllib.parse
import urllib.request
import zlib


def http_get(url, timeout=12, encoding="utf-8", ua="Mozilla/5.0"):
    """只放行 http/https 的简单 GET；带 gzip/deflate 解压，失败一律返回 ''。"""
    try:
        if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
            return ""   # 挡住 file://（读本地文件）、data: 等 scheme
        req = urllib.request.Request(url, headers={
            "User-Agent": ua,
            "Accept-Encoding": "gzip, deflate",   # 只声明 gzip/deflate（brotli 标准库解不了）
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
        if "br" in enc:
            return ""   # brotli 解不了，别返回乱码
        if raw[:2] == b"\x1f\x8b" or "gzip" in enc:
            raw = _gzip.decompress(raw)
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw.decode(encoding, "ignore")
    except Exception:
        return ""


# WMO 天气码 → 中文（Open-Meteo 用）
_WMO_ZH = {
    0: "晴", 1: "少云", 2: "多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨",
    56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}


def _wmo_zh(code):
    try:
        return _WMO_ZH.get(int(code), "未知")
    except Exception:
        return "未知"


def _num(v):
    try:
        return round(float(v))
    except Exception:
        return "?"


def _name_variants(loc):
    """地名尝试顺序：原样，再试去掉「市/省」后缀（成都市→成都）。

    刻意**不剥「区/县」**：那会把北京的「朝阳区」变成「朝阳」、正好撞上辽宁朝阳市，
    等于又回到「猜同名城市」。两个天气源共用这一份规则，行为才一致。
    """
    loc = (loc or "").strip()
    if not loc:
        return []
    stripped = loc[:-1] if loc.endswith(("市", "省")) else ""
    return [loc, stripped] if stripped else [loc]


def _geo_openmeteo(loc):
    """Open-Meteo 地理编码：城市名 → (lat, lon)；失败返回 None。"""
    names = _name_variants(loc)
    if not names:
        return None
    try:
        for name in names:
            url = ("https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&language=zh&format=json"
                   % urllib.parse.quote(name))
            d = json.loads(http_get(url, 12))
            r = (d.get("results") or [None])[0]
            if r:
                return r.get("latitude"), r.get("longitude")
    except Exception:
        pass
    return None


# ---------------- 网络状态 → 天气源选择 ----------------
_NET_MODE = None   # None=未探测；"proxy"=外网可达；"direct"=仅国内
_NET_MODE_AT = 0.0
_NET_MODE_TTL = 1800   # 秒。过期后重新探测：中途开关梯子/换网络不必重启程序


def _foreign_net_ok(timeout=6):
    """探测外网（需代理）是否可达：能取到 Open-Meteo 地理编码结果即算可达。"""
    try:
        d = json.loads(http_get(
            "https://geocoding-api.open-meteo.com/v1/search?name=beijing&count=1&format=json",
            timeout))
        return bool(d.get("results"))
    except Exception:
        return False


def _net_mode():
    """返回 'proxy'（外网可达）或 'direct'（仅国内）；结果缓存 _NET_MODE_TTL 秒。"""
    global _NET_MODE, _NET_MODE_AT
    now = time.time()
    if _NET_MODE is None or now - _NET_MODE_AT > _NET_MODE_TTL:
        _NET_MODE = "proxy" if _foreign_net_ok() else "direct"
        _NET_MODE_AT = now
    return _NET_MODE


def _weather_openmeteo_simple(loc):
    """Open-Meteo 天气简述；失败返回 ''。"""
    geo = _geo_openmeteo(loc)
    if not geo:
        return ""
    lat, lon = geo
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,weather_code&timezone=Asia%%2FShanghai" % (lat, lon))
        d = json.loads(http_get(url, 12))
        cur = d.get("current") or {}
        t = cur.get("temperature_2m")
        if t is not None:
            return "%s %s°C" % (_wmo_zh(cur.get("weather_code")), _num(t))
    except Exception:
        pass
    return ""


def _weather_openmeteo_detail(loc):
    """Open-Meteo 详细天气文本；失败返回 ''。"""
    geo = _geo_openmeteo(loc)
    if not geo:
        return ""
    lat, lon = geo
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min"
               "&timezone=Asia%%2FShanghai&forecast_days=3" % (lat, lon))
        d = json.loads(http_get(url, 12))
        cur = d.get("current") or {}
        daily = d.get("daily") or {}
        parts = ["当前%s，气温约%s°C" % (_wmo_zh(cur.get("weather_code")), _num(cur.get("temperature_2m")))]
        if cur.get("apparent_temperature") is not None:
            parts.append("体感约%s°C" % _num(cur.get("apparent_temperature")))
        if cur.get("relative_humidity_2m") is not None:
            parts.append("湿度%s%%" % _num(cur.get("relative_humidity_2m")))
        if cur.get("wind_speed_10m") is not None:
            parts.append("风速约%s km/h" % _num(cur.get("wind_speed_10m")))
        text = "，".join(parts)
        codes = daily.get("weather_code") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        labels = ["今天", "明天", "后天"]
        fc = []
        for i in range(min(3, len(codes))):
            fc.append("%s%s，%s~%s°C" % (labels[i], _wmo_zh(codes[i]),
                                         _num(tmin[i]) if i < len(tmin) else "?",
                                         _num(tmax[i]) if i < len(tmax) else "?"))
        if fc:
            text += "。未来几天：" + "；".join(fc)
        return text
    except Exception:
        return ""


# 国内天气源：中国气象局 weather.cma.cn（免费、无需 key，直连即可，不依赖代理）
def _cma_station(loc):
    """城市名 → 中国气象局站点号；**只接受精确匹配，否则返回 None**。

    以前找不到精确匹配时会退回「第一个有名字的候选」，那会把同名地名的天气静默安到
    用户头上（用户从回复里看不出城市不对）。现在宁可返回 None，交给上层说明情况：
    开机问候退化成不带天气的普通问候，主动提问就直说没能确认城市。
    """
    loc = (loc or "").strip()
    if not loc:
        return None
    names = _name_variants(loc)
    try:
        for name in names:
            url = "https://weather.cma.cn/api/autocomplete?q=" + urllib.parse.quote(name)
            d = json.loads(http_get(url, 10))
            items = [str(x).split("|") for x in (d.get("data") or [])]
            for parts in items:
                if len(parts) >= 2 and parts[1] == name:
                    return parts[0]
    except Exception:
        pass
    return None


def _weather_cma(loc, detail=False, station=None):
    """中国气象局天气文本；失败返回 ''。detail=False 时只回「天气 + 气温」简述。
    station 可由调用方预先解析好传入，避免同一次查询重复请求 autocomplete。"""
    st = station or _cma_station(loc)
    if not st:
        return ""
    try:
        d = json.loads(http_get("https://weather.cma.cn/api/weather/view?stationid=" + str(st), 10))
        data = d.get("data") or {}
        now = data.get("now") or {}
        daily = data.get("daily") or []
        if not (now or daily):
            return ""
        import time as _time
        hour = _time.localtime().tm_hour
        cond = ""
        if daily:
            d0 = daily[0]
            cond = (d0.get("dayText") if 6 <= hour < 18 else d0.get("nightText")) \
                or d0.get("dayText") or ""
        if not detail:
            t = now.get("temperature")
            if t is None and daily:
                t = daily[0].get("high")
            if t is not None:
                return ("%s %s°C" % (cond, _num(t))).strip()
            return cond
        parts = []
        if cond:
            parts.append("当前%s" % cond)
        if now.get("temperature") is not None:
            parts.append("气温约%s°C" % _num(now.get("temperature")))
        if now.get("feelst") is not None:
            parts.append("体感约%s°C" % _num(now.get("feelst")))
        if now.get("humidity") is not None:
            parts.append("湿度%s%%" % _num(now.get("humidity")))
        if now.get("windScale"):
            parts.append("%s%s" % (now.get("windDirection") or "", now.get("windScale")))
        text = "，".join(parts)
        labels = ["今天", "明天", "后天"]
        fc = []
        for i in range(min(3, len(daily))):
            di = daily[i]
            fc.append("%s%s，%s~%s°C" % (labels[i], di.get("dayText") or "",
                                         _num(di.get("low")), _num(di.get("high"))))
        if fc:
            text += "。未来几天：" + "；".join(fc)
        return text
    except Exception:
        return ""


# ---------------- IP 定位：全部走 HTTPS 免费源 ----------------
# 以前的兜底 ip-api 免费端点只提供明文 http（https 会返回 403 "SSL unavailable for
# this endpoint"），已换成 api.vore.top（HTTPS、中文省市）。顺序：国内源优先——
# 直连、不受梯子出口影响；最后一个是国外源，地名是英文，只有 Open-Meteo 认，
# 那也没关系：国内源因此查不到站点时会按「宁可不说」的原则放弃报天气。
def _geo_pconline():
    """太平洋电脑网 IP 库（国内、HTTPS、GBK）。"""
    txt = http_get("https://whois.pconline.com.cn/ipJson.jsp?json=true", 8, "gb18030")
    s, e = txt.find("{"), txt.rfind("}")
    if s < 0 or e <= s:
        return "", ""
    d = json.loads(txt[s:e + 1])
    return (d.get("pro") or "").strip(), (d.get("city") or "").strip()


def _geo_vore():
    """VORE-API IP 定位（国内、HTTPS、中文省市）。"""
    d = json.loads(http_get("https://api.vore.top/api/IPdata", 8))
    if int(d.get("code") or 0) != 200:
        return "", ""
    adcode = d.get("adcode") or {}
    info = d.get("ipdata") or {}
    pro = str(adcode.get("p") or info.get("info1") or "").strip()
    ct = str(adcode.get("c") or info.get("info2") or "").strip()
    return pro, ct


def _geo_ipwhois():
    """ipwho.is（国外、HTTPS）。地名是英文，只填城市。"""
    d = json.loads(http_get("https://ipwho.is/", 8))
    if d.get("success") is False:
        return "", ""
    return "", str(d.get("city") or "").strip()


_GEO_PROVIDERS = (_geo_pconline, _geo_vore, _geo_ipwhois)


def _geo_ip():
    """返回 (省份, 城市)：按顺序取第一个有结果的 HTTPS 源，全都失败返回 ('', '')。"""
    for provider in _GEO_PROVIDERS:
        try:
            pro, ct = provider()
        except Exception:
            continue
        if pro or ct:
            return pro, ct
    return "", ""


def weather_report(detail=True):
    """一次性给出天气查询的完整结果，供调用方按原因回话。

    返回 {"city", "text", "source", "reason"}：
      - reason == ""           取到了（source 为 'cma' 或 'open-meteo'）
      - reason == "no-location"  IP 定位没认出城市
      - reason == "no-match"     气象局没有这个地名的站点（不猜同名城市）
      - reason == "no-network"   两个源都没返回（网络不通或地名查不到）
    """
    pro, ct = _geo_ip()
    city = (pro + ct).strip()
    loc = ct or pro
    if not loc:
        return {"city": "", "text": "", "source": "", "reason": "no-location"}
    # 站点只解析一次：None 表示「这个地名在气象局站点里没有精确匹配」。
    station = _cma_station(loc)
    open_meteo = _weather_openmeteo_detail if detail else _weather_openmeteo_simple
    sources = (("open-meteo", lambda: open_meteo(loc)),
               ("cma", lambda: _weather_cma(loc, detail, station=station)))
    if _net_mode() != "proxy":
        sources = tuple(reversed(sources))
    for source, fetch in sources:
        try:
            text = fetch()
        except Exception:
            text = ""
        if text:
            return {"city": city, "text": text, "source": source, "reason": ""}
    reason = "no-match" if station is None else "no-network"
    return {"city": city, "text": "", "source": "", "reason": reason}


def get_location_and_weather():
    """返回 (城市, 天气简述)；失败返回 (城市, '')。外网可达走 Open-Meteo，仅国内走中国气象局，互相兜底。"""
    report = weather_report(detail=False)
    return report["city"], report["text"]


def get_detailed_weather():
    """返回 (城市, 详细天气文本)；失败返回 (城市, '')。"""
    report = weather_report(detail=True)
    return report["city"], report["text"]
