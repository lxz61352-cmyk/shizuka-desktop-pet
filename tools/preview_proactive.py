# -*- coding: utf-8 -*-
"""离线预演主动发言：把各种触发场景跑一遍，每句间隔 2 秒，用来看综合对话质量。

用法：
    python tools/preview_proactive.py            # 每个场景跑一遍
    python tools/preview_proactive.py 2          # 跑两遍（看不同方向的差异）

不启动桌宠、不开窗口，只调用模型（会消耗少量 token）。
会走正式程序同一套逻辑：方向池随机、本地空话闸门、内容去重，
所以被丢掉的那几次会显示「没说」——这就是实际运行时的行为。
"""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet
from dialogue_features import DialogueFeaturesMixin


class Bot(DialogueFeaturesMixin):
    def _todo_state_context(self):
        return []


GREETING_WEATHER = "成都，多云，17℃"

SCENARIOS = [
    ("前台程序变化", {"窗口标题": "build_windows.py — Shizuka — Visual Studio Code",
                 "程序": "VS Code", "进程名": "code.exe", "当前时间": "21:10", "上一个程序": "浏览器 Edge"}, None),
    ("前台程序变化", {"窗口标题": "哔哩哔哩 (゜-゜)つロ 干杯~-bilibili",
                 "程序": "浏览器 Edge", "进程名": "msedge.exe", "当前时间": "21:14", "上一个程序": "VS Code"}, None),
    ("前台程序变化", {"窗口标题": "Windows PowerShell",
                 "程序": "PowerShell", "进程名": "powershell.exe", "当前时间": "21:20", "上一个程序": "浏览器 Edge"}, None),
    ("前台程序变化", {"窗口标题": "QQ",
                 "程序": "QQ", "进程名": "qq.exe", "当前时间": "21:26", "上一个程序": "PowerShell"}, None),
    ("前台程序变化", {"窗口标题": "网易云音乐",
                 "程序": "网易云音乐", "进程名": "cloudmusic.exe", "当前时间": "21:31", "上一个程序": "QQ"}, None),
    ("前台程序变化", {"窗口标题": "静香桌宠 · 交接（2026-09-16 凌晨） - 记事本",
                 "程序": "记事本", "进程名": "notepad.exe", "当前时间": "21:38", "上一个程序": "网易云音乐"}, None),
    ("前台程序变化", {"窗口标题": "守望先锋",
                 "程序": "Overwatch", "进程名": "overwatch.exe", "当前时间": "22:05", "上一个程序": "记事本"}, None),
    ("前台程序变化", {"窗口标题": "Steam 商店",
                 "程序": "Steam", "进程名": "steam.exe", "当前时间": "22:40", "上一个程序": "Overwatch"}, None),
    ("前台程序变化", {"窗口标题": "Windows 终端",
                 "程序": "终端", "进程名": "windowsterminal.exe", "当前时间": "23:02", "上一个程序": "Steam"}, None),
    ("空闲搭话", {"无键鼠操作分钟": 5, "当前时间": "14:20"}, None),
    ("空闲搭话", {"无键鼠操作分钟": 10, "当前时间": "14:25"}, None),
    ("空闲搭话", {"无键鼠操作分钟": 5, "当前时间": "23:40"}, None),
    ("启动问候", None, None),
    ("启动问候", None, GREETING_WEATHER),
    ("启动问候", None, None),
]


def ask(bot, client, kind, facts, weather):
    direction = bot._pick_proactive_direction()
    prompt = (bot._greeting_prompt(direction, weather) if kind == "启动问候"
              else bot._proactive_prompt(kind, facts, direction))
    try:
        response = client.chat.completions.create(
            model=pet.api_model(),
            messages=[{"role": "system", "content": pet.load_persona()},
                      {"role": "user", "content": prompt}],
            temperature=1.0, max_tokens=80, wait_seconds=30)
        text = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        return direction, "", "调用失败：" + str(exc)[:120]
    if not text:
        return direction, "", "模型返回空"
    if not bot._proactive_text_ok(text, direction):
        return direction, text, "丢掉（没有具体内容，只是陪伴套话）"
    if not bot._proactive_recent_ok(text):
        return direction, text, "丢掉（和刚说过的话太像）"
    bot._proactive_remember(text)
    return direction, text, ""


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if not pet.has_api_key():
        print("没有读到 API Key，先启动一次桌宠填好 Key 再跑。")
        return
    client = pet.get_client()
    bot = Bot()
    print("模型：%s" % pet.api_model())
    print("场景 %d 个 × %d 轮，每句间隔 2 秒。\n" % (len(SCENARIOS), rounds))
    index = 0
    said = 0
    total = 0
    for _ in range(rounds):
        for kind, facts, weather in SCENARIOS:
            index += 1
            total += 1
            direction, text, why = ask(bot, client, kind, facts, weather)
            head = "[%02d] %s · 方向=%s" % (index, kind, direction.get("label", "?"))
            if text and not why:
                said += 1
                print(head)
                print("      → %s" % text.replace("\n", " / "))
            elif text:
                print(head)
                print("      → %s（%s）" % (text.replace("\n", " / "), why))
            else:
                print(head)
                print("      → （%s，这次不说话）" % (why or "空"))
            time.sleep(2)
    print("\n合计：%d 次触发，实际开口 %d 次。" % (total, said))


if __name__ == "__main__":
    main()
