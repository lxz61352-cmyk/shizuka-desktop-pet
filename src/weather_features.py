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
        import pet as engine
        report = weather_report(detail=True)
        if my_conv is not None and my_conv != self._conv_id:
            return
        if not report["text"]:
            scene = WEATHER_FAIL_SCENES.get(report["reason"], 'weather_no_network')
            self._ui(lambda: self._say_after_think(self._scene(scene), my_conv))
            return
        city, detail = report["city"], report["text"]
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        prompt = (
            "现在时间 %s，用户所在地约 %s。真实天气数据：%s\n"
            "用户问：“%s”\n"
            "请以静香的口吻，结合上面的真实数据回答，可以顺带一句贴心提醒（带伞、穿衣、防晒、温差之类）。"
            "只准使用上面给出的天气信息，不要补充数据里没有的下雨、降温、风力、湿度；"
            "给出的是当下实况，不要改写成未来的预报。"
        ) % (now_str, city, detail, question)
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
        self._ui(lambda: self._say_after_think(
            text or ("%s现在%s，你参考一下哦。" % (city, detail)), my_conv))

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
