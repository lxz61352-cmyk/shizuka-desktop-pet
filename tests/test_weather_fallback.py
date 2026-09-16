"""天气取不到时的行为：不猜同名城市、按原因直说；IP 定位全部走 HTTPS 免费源。
"""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import weather  # noqa: E402
import weather_features  # noqa: E402


def autocomplete(items):
    return json.dumps({"data": items})


class StationMatchTests(unittest.TestCase):
    def test_exact_match_returns_station(self):
        with patch.object(weather, "http_get", return_value=autocomplete(["54511|北京", "54512|昌平"])):
            self.assertEqual(weather._cma_station("北京"), "54511")

    def test_suffix_is_stripped_before_retrying(self):
        def get(url, timeout=10):
            return autocomplete(["56294|成都"] if url.endswith("%E6%88%90%E9%83%BD") else autocomplete([]))
        with patch.object(weather, "http_get", side_effect=get):
            self.assertEqual(weather._cma_station("成都市"), "56294")

    def test_no_exact_match_returns_none_instead_of_guessing(self):
        # 「朝阳」在候选里只有「朝阳市 / 朝阳区」两个带后缀的地名，没有精确匹配的那一个：
        # 以前会静默取第一个候选（把辽宁朝阳市的天气当成用户的），现在必须放弃。
        with patch.object(weather, "http_get", return_value=autocomplete(["54321|朝阳市", "54322|朝阳区"])):
            self.assertIsNone(weather._cma_station("朝阳"))

    def test_district_suffix_is_not_stripped(self):
        # 「朝阳区」不能剥成「朝阳」去撞辽宁朝阳市——区/县后缀一律不剥。
        with patch.object(weather, "http_get", return_value=autocomplete(["54324|朝阳"])):
            self.assertIsNone(weather._cma_station("朝阳区"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(weather._cma_station(""))


class GeoProviderTests(unittest.TestCase):
    def test_all_geo_sources_are_https(self):
        seen = []

        def get(url, timeout=12, encoding="utf-8", ua="Mozilla/5.0"):
            seen.append(url)
            raise OSError("offline")

        with patch.object(weather, "http_get", side_effect=get):
            self.assertEqual(weather._geo_ip(), ("", ""))
        self.assertTrue(seen)
        for url in seen:
            self.assertTrue(url.startswith("https://"), url)

    def test_chinese_provider_is_used_for_province_and_city(self):
        payload = json.dumps({"code": 200, "ipdata": {"info1": "四川省", "info2": "成都市"},
                              "adcode": {"p": "四川", "c": "成都"}})

        def get(url, timeout=12, encoding="utf-8", ua="Mozilla/5.0"):
            return "" if "pconline" in url else payload

        with patch.object(weather, "http_get", side_effect=get):
            self.assertEqual(weather._geo_ip(), ("四川", "成都"))

    def test_plaintext_provider_is_gone(self):
        source = (ROOT / "src" / "weather.py").read_text(encoding="utf-8")
        self.assertNotIn("ip-api.com", source)


class WeatherReportTests(unittest.TestCase):
    def report(self, geo, station, net="direct", texts=()):
        """texts = (open_meteo 结果, cma 结果)。"""
        open_meteo, cma = texts if texts else ("", "")
        with patch.object(weather, "_geo_ip", return_value=geo), \
             patch.object(weather, "_cma_station", return_value=station), \
             patch.object(weather, "_net_mode", return_value=net), \
             patch.object(weather, "_weather_openmeteo_detail", return_value=open_meteo), \
             patch.object(weather, "_weather_cma", return_value=cma):
            return weather.weather_report(detail=True)

    def test_no_location(self):
        self.assertEqual(self.report(("", ""), None)["reason"], "no-location")

    def test_no_station_match_is_reported_as_no_match(self):
        result = self.report(("四川", "朝阳区"), None)
        self.assertEqual(result["reason"], "no-match")
        self.assertEqual(result["city"], "四川朝阳区")

    def test_network_failure_is_reported_as_no_network(self):
        self.assertEqual(self.report(("四川", "成都"), "56294")["reason"], "no-network")

    def test_domestic_network_prefers_cma(self):
        result = self.report(("四川", "成都"), "56294", net="direct", texts=("外网天气", "气象局天气"))
        self.assertEqual(result["source"], "cma")
        self.assertEqual(result["text"], "气象局天气")
        self.assertEqual(result["reason"], "")

    def test_foreign_network_prefers_open_meteo(self):
        result = self.report(("", "Chengdu"), None, net="proxy", texts=("外网天气", ""))
        self.assertEqual(result["source"], "open-meteo")
        self.assertEqual(result["text"], "外网天气")

    def test_domestic_falls_back_to_open_meteo_when_network_is_reachable(self):
        result = self.report(("四川", "成都"), None, net="direct", texts=("外网天气", ""))
        self.assertEqual(result["source"], "open-meteo")


class GreetingFallbackTests(unittest.TestCase):
    def device(self, prefetch):
        holder = weather_features.WeatherNewsMixin()
        holder._geo_prefetch = prefetch
        holder._geo_thread = None
        return holder

    def test_greeting_drops_weather_when_lookup_failed(self):
        # 定位成功但天气为空（例如气象局没有这个地名的站点）→ 不做带天气的问候。
        holder = self.device(("四川成都", ""))
        with patch.object(weather_features.random, "random", return_value=0.0):
            self.assertEqual(holder._greeting_weather(), "")

    def test_greeting_keeps_weather_when_available(self):
        holder = self.device(("成都", "多云 17°C"))
        with patch.object(weather_features.random, "random", return_value=0.0):
            self.assertEqual(holder._greeting_weather(), "成都：多云 17°C")

    def test_greeting_skips_weather_when_prefetch_missing_entirely(self):
        holder = self.device(None)
        with patch.object(weather_features.random, "random", return_value=0.0):
            self.assertEqual(holder._greeting_weather(), "")


class FailSceneTests(unittest.TestCase):
    def test_every_reason_has_its_own_line(self):
        import dialogue_style
        for reason, scene in weather_features.WEATHER_FAIL_SCENES.items():
            self.assertIn(scene, dialogue_style.DEFAULT_LINES, reason)
            self.assertTrue(dialogue_style.DEFAULT_LINES[scene].strip())

    def test_unknown_reason_falls_back_to_network_line(self):
        self.assertNotIn("something-new", weather_features.WEATHER_FAIL_SCENES)
        self.assertEqual(weather_features.WEATHER_FAIL_SCENES.get("something-new", "weather_no_network"),
                         "weather_no_network")


if __name__ == "__main__":
    unittest.main()
