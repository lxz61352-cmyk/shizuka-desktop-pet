# -*- coding: utf-8 -*-
"""对话质量预演：30 条「用户可能说的话 / 粘贴的内容 / 会触发的事件」跑一遍，
把输入、走到的方向、以及实际回复整理成一份 txt，用来通读整体效果。

用法：
    python tools/preview_dialogue.py [输出路径]
默认写到 data/preview_dialogue.txt（data 不随包发布）。

说明：
- 走正式程序同一套提示词与判定（人设 + 聊天风格 + 意图路由 + 主动发言方向池 + 空话闸门 + 去重）。
- 不启动桌宠、不开窗口；只调用模型，会消耗少量 token。
- 聊天预演**不含**历史记忆注入（那部分依赖本机真实聊天记录），所以看到的是「干净上下文」下的回复质量。
- 识图不做（依赖图片质量，稳定性本身不高）。
"""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pet
from dialogue_features import DialogueFeaturesMixin
from intent_routing import local_intent, router_prompt

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "preview_dialogue.txt"

DIRECTION_LABELS = {
    "chat": "chat 普通聊天",
    "add_todo": "add_todo 新建待办（走待办流程）",
    "query_todo": "query_todo 查看待办（走待办流程）",
    "delete_todo": "delete_todo 删除待办（走待办流程）",
    "complete_todo": "complete_todo 完成待办（走待办流程）",
    "usage_report": "usage_report 使用时长（读本机统计后汇报）",
    "weather": "weather 天气（取实时天气后回答）",
    "news": "news 新闻（取当日新闻后回答）",
    "research": "research 研究进展（当前整体禁用）",
    "computer_task": "computer_task 电脑助手（交给 DSH 跑文件任务）",
}
NOT_GENERATED = "（该方向由专门流程处理，这里不生成回复）"

CHAT_CASES = [
    "什么是新质生产力？",
    "帮我解释一下 Johnson 法则，我明天要讲",
    "我今天有点累，不想动了",
    "在吗",
    "你觉得我是个什么样的人",
    "室友半夜还在打游戏，吵得我睡不着",
    "推荐几本讲运筹学的书吧",
    "为什么我的 Python 脚本总是报缩进错误",
    "帮我给一个女生挑个生日礼物",
    "我在纠结要不要退掉这门选修课",
    "我今天终于把论文初稿写完了",
    "晚安，我去睡了",
]

CLIP_CASES = [
    ("粘贴板·中文", "这个破系统又崩了，一下午的活全白干，真想砸键盘。"),
    ("粘贴板·英文", "The unreasonable effectiveness of data suggests that simple models with enough data often beat clever models with less."),
    ("粘贴板·古诗", "行到水穷处，坐看云起时。"),
    ("粘贴板·代码", "for i in range(10):\n    print(i)"),
    ("粘贴板·报错", "ModuleNotFoundError: No module named 'requests'"),
    ("粘贴板·日文", "今日はいい天気ですね。散歩でも行きましょうか。"),
]

OP_CASES = [
    "提醒我明天9点开会",
    "我有哪些待办",
    "今天天气怎么样",
    "讲个新闻听听",
    "我今天用了多久电脑",
    "/电脑 列出工作文件夹里的文件",
]

PROACTIVE_CASES = [
    ("前台程序变化", {"窗口标题": "build_windows.py — Shizuka — Visual Studio Code", "程序": "VS Code",
                 "进程名": "code.exe", "当前时间": "21:10", "上一个程序": "浏览器 Edge"}, None),
    ("前台程序变化", {"窗口标题": "哔哩哔哩 (゜-゜)つロ 干杯~-bilibili", "程序": "浏览器 Edge",
                 "进程名": "msedge.exe", "当前时间": "21:14", "上一个程序": "VS Code"}, None),
    ("前台程序变化", {"窗口标题": "守望先锋", "程序": "Overwatch", "进程名": "overwatch.exe",
                 "当前时间": "22:05", "上一个程序": "记事本"}, None),
    ("前台程序变化", {"窗口标题": "Windows 终端", "程序": "终端", "进程名": "windowsterminal.exe",
                 "当前时间": "23:02", "当前时间": "23:02", "上一个程序": "Steam"}, None),
    ("空闲搭话", {"无键鼠操作分钟": 5, "当前时间": "14:20"}, None),
    ("启动问候", None, "成都，多云，17℃"),
]


class Bot(DialogueFeaturesMixin):
    def _todo_state_context(self):
        return []


def route(client, text):
    """和正式程序一致：先本地快速通道，没命中再让模型路由器判。"""
    local = local_intent(text)
    if local is not None:
        return local.get("action", "chat"), "本地"
    try:
        response = client.chat.completions.create(
            model=pet.api_model(), messages=[{"role": "user", "content": router_prompt(text)}],
            temperature=0, max_tokens=160, response_format={"type": "json_object"}, wait_seconds=20)
        result = json.loads(response.choices[0].message.content or "null")
        if isinstance(result, dict) and isinstance(result.get("action"), str):
            return result["action"], "模型路由器"
    except Exception:
        pass
    return "chat", "兜底"


def chat_system():
    system = pet.load_persona() + pet.character_option("chat_style", pet.CHAT_STYLE_HINT)
    from conversation_memory import CONTINUATION_HINT
    return system + "\n" + CONTINUATION_HINT


def stream_reply(client, messages):
    out = []
    with client.chat.completions.create(model=pet.api_model(), messages=messages,
            temperature=.7, max_tokens=3200, stream=True, wait_seconds=40) as stream:
        for chunk in stream:
            if chunk.choices:
                out.append(chunk.choices[0].delta.content or "")
    return pet.clean_reply_style("".join(out)).strip()


def once(client, messages, max_tokens=120, temperature=1.0):
    response = client.chat.completions.create(model=pet.api_model(), messages=messages,
        temperature=temperature, max_tokens=max_tokens, wait_seconds=30)
    return (response.choices[0].message.content or "").strip()


def main():
    if not pet.has_api_key():
        print("没有读到 API Key，先启动一次桌宠填好 Key 再跑。")
        return
    client = pet.get_client()
    bot = Bot()
    persona = pet.load_persona()
    system = chat_system()
    lines = ["静香桌宠 · 对话质量预演",
             "模型：%s" % pet.api_model(),
             "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "共 30 条：普通聊天 12 / 粘贴板 6 / 操作类 6 / 主动发言 6",
             "说明：聊天预演不含历史记忆注入；识图不做。",
             ""]
    index = 0

    def emit(kind, source, direction, reply, extra=""):
        lines.append("─" * 72)
        lines.append("[%02d] %s ｜ 方向：%s%s" % (index, kind, direction, extra))
        lines.append("输入：" + source.replace("\n", " ⏎ "))
        lines.append("回复：" + (reply.replace("\n", "\n      ") if reply else "（无）"))
        lines.append("")

    for text in CHAT_CASES:
        index += 1
        action, how = route(client, text)
        if action != "chat":
            emit("提问/闲聊", text, DIRECTION_LABELS.get(action, action), NOT_GENERATED, "（%s判定）" % how)
            time.sleep(2)
            continue
        try:
            reply = stream_reply(client, [{"role": "system", "content": system},
                                          {"role": "user", "content": text}])
        except Exception as exc:
            reply = "调用失败：" + str(exc)[:150]
        emit("提问/闲聊", text, DIRECTION_LABELS["chat"], reply, "（%s判定）" % how)
        time.sleep(2)

    for kind, text in CLIP_CASES:
        index += 1
        snippet = text.strip().replace("\n", " ")[:120]
        foreign = kind.endswith("英文") or kind.endswith("日文")
        prompt = bot._clip_translate_prompt(snippet) if foreign else bot._clip_react_prompt(snippet)
        try:
            raw = once(client, [{"role": "system", "content": persona},
                                {"role": "user", "content": prompt}],
                       max_tokens=800 if foreign else 80, temperature=.5 if foreign else 1.0)
        except Exception as exc:
            raw = "调用失败：" + str(exc)[:150]
        if foreign and raw and not raw.startswith("调用失败"):
            translation = comment = ""
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = json.loads(raw[start:end + 1])
                    translation = (obj.get("translation") or "").strip().strip("“”\"'")
                    comment = (obj.get("comment") or "").strip()
                except Exception:
                    translation = ""
            if not translation:
                translation = raw.strip().strip("“”\"'")
            raw = "“%s”\n%s" % (translation, comment) if comment else "“%s”" % translation
        emit(kind, text, "粘贴板翻译（外语）" if foreign else "粘贴板普通反应", raw)
        time.sleep(2)

    for text in OP_CASES:
        index += 1
        action, how = route(client, text)
        emit("操作类", text, DIRECTION_LABELS.get(action, action), NOT_GENERATED, "（%s判定）" % how)
        time.sleep(2)

    for kind, facts, weather in PROACTIVE_CASES:
        index += 1
        direction = bot._pick_proactive_direction()
        prompt = (bot._greeting_prompt(direction, weather) if kind == "启动问候"
                  else bot._proactive_prompt(kind, facts, direction))
        source = ("启动问候（天气：" + weather + "）") if weather else (
            kind + "：" + (facts.get("窗口标题") or ("空闲 %d 分钟" % facts.get("无键鼠操作分钟", 0))))
        try:
            text = once(client, [{"role": "system", "content": persona},
                                 {"role": "user", "content": prompt}], max_tokens=120)
        except Exception as exc:
            text = "调用失败：" + str(exc)[:150]
        note = ""
        if text and not text.startswith("调用失败"):
            if not bot._proactive_text_ok(text, direction):
                note = " → 正式运行会被丢掉（没有具体内容）"
            elif not bot._proactive_recent_ok(text):
                note = " → 正式运行会被丢掉（与刚说过的话太像）"
            else:
                bot._proactive_remember(text)
        emit("主动发言", source, "方向=" + str(direction.get("label") or "?"), text, note)
        time.sleep(2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("已写入：%s" % OUT)
    print("共 %d 条。" % index)


if __name__ == "__main__":
    main()
