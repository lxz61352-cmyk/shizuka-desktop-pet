"""Weather / news intents must reach the model router instead of the chat fast path."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intent_routing import local_intent, router_prompt
from weather import _wmo_zh


class WebIntentRoutingTests(unittest.TestCase):
    def test_weather_questions_reach_the_router(self):
        for text in ("今天天气怎么样", "明天会下雨吗", "要不要带伞", "成都现在多少度", "冷不冷"):
            self.assertIsNone(local_intent(text), text)

    def test_news_requests_reach_the_router(self):
        for text in ("讲个新闻听听", "今天有什么新闻"):
            self.assertIsNone(local_intent(text), text)

    def test_plain_chat_short_circuits(self):
        self.assertEqual(local_intent("你好呀"), {"action": "chat"})

    def test_router_prompt_offers_weather_and_news(self):
        prompt = router_prompt("今天天气怎么样")
        self.assertIn("weather", prompt)
        self.assertIn("news", prompt)


class WeatherCodeTests(unittest.TestCase):
    def test_weather_codes_have_chinese_labels(self):
        self.assertEqual(_wmo_zh(0), "晴")
        self.assertEqual(_wmo_zh(95), "雷阵雨")
        self.assertEqual(_wmo_zh(999), "未知")


if __name__ == "__main__":
    unittest.main()
