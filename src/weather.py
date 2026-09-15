"""本机定位与天气查询：外网可达走 Open-Meteo，仅国内走中国气象局，互为兜底。"""
import gzip as _gzip
import json
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


def _geo_openmeteo(loc):
    """Open-Meteo 地理编码：城市名 → (lat, lon)；失败返回 None。会自动去掉「市/省/区/县」后缀再试。"""
    loc = (loc or "").strip()
    if not loc:
        return None
    names = [loc]
    stripped = loc.rstrip("市省区县")
    if stripped and stripped != loc:
        names.append(stripped)
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
    """返回 'proxy'（外网可达）或 'direct'（仅国内）。首次探测后缓存。"""
    global _NET_MODE
    if _NET_MODE is None:
        _NET_MODE = "proxy" if _foreign_net_ok() else "direct"
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
    """城市名 → 中国气象局站点号；失败返回 None。会自动去掉「市/省/区/县」后缀再试。"""
    loc = (loc or "").strip()
    if not loc:
        return None
    names = [loc]
    stripped = loc.rstrip("市省区县")
    if stripped and stripped != loc:
        names.append(stripped)
    try:
        for name in names:
            url = "https://weather.cma.cn/api/autocomplete?q=" + urllib.parse.quote(name)
            d = json.loads(http_get(url, 10))
            items = [str(x).split("|") for x in (d.get("data") or [])]
            for parts in items:
                if len(parts) >= 2 and parts[1] == name:
                    return parts[0]
            for parts in items:
                if len(parts) >= 2 and parts[1]:
                    return parts[0]
    except Exception:
        pass
    return None


def _weather_cma(loc, detail=False):
    """中国气象局天气文本；失败返回 ''。detail=False 时只回「天气 + 气温」简述。"""
    st = _cma_station(loc)
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


def _geo_ip():
    """返回 (省份, 城市)。优先国内 IP 库（走直连，不受梯子/代理出口影响），失败再回退 ip-api。"""
    # 1) 国内：太平洋电脑网 IP 库，返回 GBK
    try:
        txt = http_get("https://whois.pconline.com.cn/ipJson.jsp?json=true", 8, "gb18030")
        s, e = txt.find("{"), txt.rfind("}")
        if s >= 0 and e > s:
            d = json.loads(txt[s:e + 1])
            pro = (d.get("pro") or "").strip()
            ct = (d.get("city") or "").strip()
            if pro or ct:
                return pro, ct
    except Exception:
        pass
    # 2) 回退：ip-api（国外站，梯子开着时可能定位到出口）
    try:
        txt = http_get("http://ip-api.com/json/?lang=zh-CN", 12)
        if txt:
            d = json.loads(txt)
            if d.get("status") == "success":
                return (d.get("regionName", "") or "").strip(), (d.get("city", "") or "").strip()
    except Exception:
        pass
    return "", ""


def get_location_and_weather():
    """返回 (城市, 天气简述)；失败返回 ('', '')。外网可达走 Open-Meteo，仅国内走中国气象局，互相兜底。"""
    pro, ct = _geo_ip()
    city = (pro + ct).strip()
    loc = ct or pro
    if not loc:
        return city, ""
    if _net_mode() == "proxy":
        text = _weather_openmeteo_simple(loc) or _weather_cma(loc)
    else:
        text = _weather_cma(loc) or _weather_openmeteo_simple(loc)
    return city, text


def get_detailed_weather():
    """返回 (城市, 详细天气文本)；失败返回 ('', '')。外网可达走 Open-Meteo，仅国内走中国气象局，互相兜底。"""
    pro, ct = _geo_ip()
    city = (pro + ct).strip()
    loc = ct or pro
    if not loc:
        return city, ""
    if _net_mode() == "proxy":
        text = _weather_openmeteo_detail(loc) or _weather_cma(loc, detail=True)
    else:
        text = _weather_cma(loc, detail=True) or _weather_openmeteo_detail(loc)
    return city, text
