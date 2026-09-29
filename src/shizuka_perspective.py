"""CPC（角色视角编译，P2c-9.2 / S0）：把"已提供的背景"压成三字段角色视角记录。

边界（方案 P2c-9.2 §2 + 红线）：
- 只用传入的素材包（Persona / Relationship / SharedHistory / CurrentWorld）；
- 不读 Response Authority，输出不落库、不回流为事实；
- 失败 / 解析不出 → 返回 None，调用方跳过本轮（不阻塞回复）。

本模块不直接持有网络客户端：模型调用通过 call(system, user, ...) 注入（便于离线单测）。
"""
import re

CPC_MAX_TOKENS = 300
CPC_TEMPERATURE = 0.2

FIELD_NAMES = ("当前对象", "角色相关信息", "角色关注角度")
MISSING = "（无）"
NOTE_LINE = "（备注：仅作视角参考；不要求提及，不要求逐条使用。）"

MATERIAL_TEMPLATE = """【角色简述】{persona}
【关系】{relationship}
【共同经历】{shared_history}
【当前世界】{world}
【用户输入】{text}"""

CPC_SYSTEM_PROMPT = """你是角色「静香」的对话预处理模块。任务：根据【已提供的背景】，整理一条很窄的"角色视角记录"，供她对话时参考。你不是在理解用户，只是在核对：当前输入和哪些角色信息真正有关。

输出固定三行（不要输出别的任何内容）：
当前对象：<用户这句话在说的事，客观概括或引用，40 字内>
角色相关信息：<已提供背景里与当前输入真正发生关联的角色信息；没有写（无）>
角色关注角度：<静香可能从什么角度看到这件事，40 字内；没有写（无）>

规则：
1. 只能使用【已提供的背景】；不得推断当前时间、地点、天气、环境——背景里没有的一律视为未知；
2. 不得推断用户意图、心理、动机（不写"随口一提 / 找共鸣 / 试探 / 在等下一句"这类猜测）；
3. 「角色关注角度」只允许：(a) 输入字面上可观察的用词 / 语气特征；(b) 已提供角色材料引出的关注点；
4. 角色材料里的条件型属性要编译成"与当前输入相关的角色经验"，不要原样搬条件事实——例：不写"她夜里更清醒"，写"她对'困但不想睡'这种状态不陌生"；
5. 相关性门槛：只保留与当前输入真正有关的信息；关系弱就写（无）——写（无）是正常结果；
6. 不建议怎么回、怎么反应（不出现"可以 / 应该 / 建议 / 不妨"等）；
7. 每行不超过 40 字；固定三行，不输出其他内容。

示例 A：
当前对象：用户分享今天云很好看
角色相关信息：（无）
角色关注角度：输入是具体的欣赏评价，可能对细节有兴趣

示例 B：
当前对象：用户说有点烦
角色相关信息：（无）
角色关注角度：输入极短、无具体指向"""


def _clean(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def build_materials(text, persona="", relationship="", shared_history="", world=""):
    """组装"已提供背景"素材包；空项落为（无）。"""
    return MATERIAL_TEMPLATE.format(
        persona=(persona or "").strip() or MISSING,
        relationship=(relationship or "").strip() or MISSING,
        shared_history=(shared_history or "").strip() or MISSING,
        world=(world or "").strip() or MISSING,
        text=(text or "").strip())


def parse_cpc(raw):
    """解析三字段；缺"当前对象"或整体为空 → None；其余缺项补（无）。"""
    text = _clean(raw)
    if not text:
        return None
    fields = {}
    for name in FIELD_NAMES:
        match = re.search(rf"{name}[：:]\s*(.+)", text)
        fields[name] = match.group(1).strip() if match else ""
    if not fields["当前对象"]:
        return None
    for name in FIELD_NAMES[1:]:
        if not fields[name]:
            fields[name] = MISSING
    return fields


def format_block(fields):
    """三字段 → 注入块文本；fields 为 None → 空串。"""
    if not fields:
        return ""
    return ("【角色视角记录】\n"
            f"当前对象：{fields['当前对象']}\n"
            f"角色相关信息：{fields['角色相关信息']}\n"
            f"角色关注角度：{fields['角色关注角度']}\n"
            f"{NOTE_LINE}")


def compile_perspective(text, call, persona="", relationship="", shared_history="",
                        world="", max_tokens=CPC_MAX_TOKENS):
    """生成 CPC。call(system, user, max_tokens=..., temperature=...) -> str。

    call 为 None、text 为空、调用异常、解析失败 → 返回 None（调用方跳过本轮）。
    """
    text = (text or "").strip()
    if not text or call is None:
        return None
    user = build_materials(text, persona, relationship, shared_history, world)
    try:
        raw = call(CPC_SYSTEM_PROMPT, user, max_tokens=max_tokens, temperature=CPC_TEMPERATURE)
    except Exception:
        return None
    return parse_cpc(raw)
