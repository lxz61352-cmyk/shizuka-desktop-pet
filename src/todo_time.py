"""Local reminder time parsing, independent of UI and model clients."""
import re
import time

# 判断文本里是否真的含"明确钟点/时长"。只有命中才允许把待办判为"时间明确"，
# 避免模型把"早点/晚点"这类模糊词自行脑补成一个具体时间（如 8 点）。
_EXPLICIT_TIME_RE = re.compile(
    r"\d{1,2}\s*[:：]\s*\d{1,2}"                          # 8:30
    r"|\d{1,2}\s*[点時时]\s*半"                            # 8点半
    r"|\d{1,2}\s*[点時时]"                                 # 8点 / 8时
    r"|[零一二三四五六七八九十两]+\s*[点時时]"                # 八点 / 两点
    r"|[点时]\s*半"                                        # 点半
    r"|\d+\s*个?\s*(秒|分钟|小时|钟头|天|日|周|星期)"          # 20秒 / 30分钟 / 2小时 / 3天 / 2周
    r"|[零一二三四五六七八九十两]+\s*个?\s*(秒|分钟|小时|钟头|天|日)"  # 两小时 / 三天
    r"|半\s*个?\s*(小时|钟头)"                              # 半小时
    r"|\d+\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|s|m|h)"  # 20s / 2h / 30min
)

# 相对时长：用于本地直接算出绝对时间（不依赖模型）
# 负向后顾 (?<![月年]) 避免把日期“3月5日/2025年3天”里的数字当成相对时长
_REL_TIME_RE = re.compile(
    r"(?<![月年])(\d+)\s*个?\s*(秒钟?|分钟?|小时|钟头|天|日|周|星期)"       # 中文：20秒 / 2小时 / 3天 / 1周
    r"|(?<![月年])(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|s|m|h)"  # 英文：20s / 2h / 30min
)


def has_explicit_time(text):
    return bool(_EXPLICIT_TIME_RE.search(text or ""))


def parse_relative_due(text, now=None):
    """本地把相对时长（“20秒后”“2小时后”“3天后”“20s”）解析成绝对时间戳；没有则 None。"""
    text = text or ""
    m = _REL_TIME_RE.search(text)
    if not m:
        return None
    if text[m.end():m.end() + 1] == "前":   # “3天前”是过去，不作为将来提醒
        return None
    now = time.time() if now is None else now
    if m.group(1):                       # 中文
        n = int(m.group(1))
        unit = m.group(2)
        if "秒" in unit:
            mult = 1
        elif "分" in unit:
            mult = 60
        elif ("小时" in unit) or ("钟头" in unit):
            mult = 3600
        elif ("周" in unit) or ("星期" in unit):
            mult = 604800
        else:                            # 天 / 日
            mult = 86400
    else:                                # 英文
        n = int(m.group(3))
        unit = m.group(4).lower()
        if unit.startswith("s"):
            mult = 1
        elif unit.startswith("m"):
            mult = 60
        else:
            mult = 3600
    return now + n * mult


