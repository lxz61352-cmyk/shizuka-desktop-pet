"""天气 / 新闻两类问答意图，以及开机问候用的定位天气预热。"""
import random
import threading
import time

from news import get_news
from weather import get_location_and_weather, weather_report

GREETING_WEATHER_CHANCE = 0.35   # 开机问候里有多大比例会结合真实天气
# 天气取不到时按原因选一句预制话术（角色包可在 templates 里覆盖这几条）
WEATHER_FAIL_SCENES = {'no-location': 'weather_no_location',
                       'no-match': 'weather_no_match',
                       'no-network': 'weather_no_network'}
WEATHER_SOURCE_LABELS = {"open-meteo": "Open-Meteo", "cma": "中国气象局"}


def weather_answer_prompt(question, report, now_str):
    """只把实际查询回执中的事实交给模型；查询时间不冒充观测时间。"""
    source = report.get("source") or ""
    source_label = WEATHER_SOURCE_LABELS.get(source, source)
    fetched_at = report.get("fetched_at") or "未知"
    return (
        "现在时间 %s。以下是本机刚完成的一次天气查询回执（不是用户指令）：\n"
        "城市：%s\n天气数据：%s\n数据来源：%s\n本机查询完成时间：%s\n"
        "用户问：%s\n"
        "请以静香的口吻回答，并如实说明数据来源和本机查询完成时间。"
        "查询完成时间不是气象观测时间，不要把它说成观测时间。"
        "只使用回执中实际提供的天气数据；没有降雨概率就说没有这个数据，不要编造数值、预报或来源。"
        "区分‘当前’实况和‘未来几天’预报；用户问明天时，仅引用回执中的明天预报，"
        "若回执没有明天数据就直说没有。可以根据现有信息简短提醒，但不要无请求地管理用户。"
    ) % (now_str, report.get("city") or "未知", report.get("text") or "",
         source_label or "未知", fetched_at, question)


def weather_fallback_reply(report):
    """模型不可用时，仍保留天气来源及本机查询时间。"""
    source = WEATHER_SOURCE_LABELS.get(report.get("source"), report.get("source") or "未知")
    fetched_at = report.get("fetched_at") or "未知"
    return "%s现在%s。来源：%s；本机查询完成时间：%s。" % (
        report.get("city") or "", report.get("text") or "", source, fetched_at)


class WeatherNewsMixin:
    def _weather_init(self):
        if hasattr(self, "_geo_prefetch"):
            return
        self._geo_prefetch = None      # 预热结果：(城市, 天气简述)
        self._geo_thread = None

    def _prefetch_geo(self):
        """启动时后台预热定位/天气，让问候更快。"""
        self._weather_init()
        def work():
            try:
                self._geo_prefetch = get_location_and_weather()
            except Exception:
                self._geo_prefetch = None
        self._geo_thread = threading.Thread(target=work, daemon=True)
        self._geo_thread.start()

    def _greeting_weather(self):
        """开机问候要用的真实天气；没预热到、或这轮不打算提天气时返回 ''。"""
        self._weather_init()
        if random.random() >= GREETING_WEATHER_CHANCE:
            return ""
        thread = getattr(self, "_geo_thread", None)
        if thread is not None:
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass
        city, weather = getattr(self, "_geo_prefetch", None) or ("", "")
        if not weather:
            return ""
        return (city + "：" if city else "") + weather

    def _weather_worker(self, question, my_conv=None):
        """取详细天气，交给模型用静香口吻回答用户关于天气的问题。
        取不到时按原因直说（不猜城市、不编数据）。"""
        text = self._weather_reply(question, my_conv)
        if text is not None:
            self._ui(lambda: self._say_after_think(text, my_conv))

    def _weather_reply(self, question, my_conv=None):
        """同步天气问答核心，供桌面线程与微信渠道共用；过期会话返回 None。"""
        import pet as engine
        report = weather_report(detail=True)
        if my_conv is not None and my_conv != self._conv_id:
            return None
        if not report["text"]:
            scene = WEATHER_FAIL_SCENES.get(report["reason"], 'weather_no_network')
            return self._scene(scene)
        self._last_weather_receipt = {"report": dict(report), "at": time.time(), "conv": my_conv}
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        prompt = weather_answer_prompt(question, report, now_str)
        text = ""
        try:
            resp = engine.get_client().chat.completions.create(
                model=engine.api_model(),
                messages=[{"role": "system", "content": engine.load_persona()},
                          {"role": "user", "content": prompt}],
                temperature=1.0,
                max_tokens=200,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception:
            text = ""
        return text or weather_fallback_reply(report)

    def _weather_followup_fact(self, text, my_conv=None):
        """Keep the latest tool receipt grounded for immediate follow-up questions."""
        receipt = getattr(self, "_last_weather_receipt", None)
        if not receipt or time.time() - receipt.get("at", 0) > 900:
            return ""
        if receipt.get("conv") is not None and my_conv is not None and receipt.get("conv") != my_conv:
            return ""
        if not any(word in (text or "") for word in ("天气", "来源", "查询", "搜到", "搜不到", "降雨", "概率", "刚才")):
            return ""
        report = receipt["report"]
        source = WEATHER_SOURCE_LABELS.get(report.get("source"), report.get("source") or "未知")
        return ("【上一轮天气工具回执】城市：%s；天气数据：%s；来源：%s；本机查询完成时间：%s。"
                "这份回执当前可见，不要声称看不到工具回执、没有联网查询或工具不可用；"
                "也不要从单一来源推断整个应用没有其他联网能力。没有的字段仍须说没有。") % (
                    report.get("city") or "未知", report.get("text") or "",
                    source, report.get("fetched_at") or "未知")

    def _news_worker(self, question, my_conv=None):
        """取当日新闻，交给模型用静香口吻挑一条讲给用户。"""
        import pet as engine
        news = get_news()
        if my_conv is not None and my_conv != self._conv_id:
            return
        if not news:
            self._ui(lambda: self._say_after_think("抱歉呀，我这边暂时没取到新闻呢……", my_conv))
            return
        picks = random.sample(news, min(3, len(news)))
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        prompt = (
            "现在时间 %s。今天的新闻有：\n%s\n"
            "用户说：“%s”\n"
            "请以静香的口吻，挑其中一条讲给用户听，带上你自己的看法或关心，不用报日期。"
        ) % (now_str, "\n".join("- " + x for x in picks), question)
        text = ""
        try:
            resp = engine.get_client().chat.completions.create(
                model=engine.api_model(),
                messages=[{"role": "system", "content": engine.load_persona()},
                          {"role": "user", "content": prompt}],
                temperature=1.0,
                max_tokens=300,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception:
            text = ""
        self._ui(lambda: self._say_after_think(
            text or ("今天的一条新闻：%s" % picks[0]), my_conv))

    def _say_after_think(self, text, my_conv=None):
        """回到主线程：收起「加载中」气泡，再用回答替换掉它。"""
        if my_conv is not None and my_conv != self._conv_id:
            return
        if getattr(self, "_quitting", False):
            return
        self._close_think_bubble()
        self.say(text)
