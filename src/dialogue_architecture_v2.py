"""Phase S1 candidate: single-owner request chain (dialogue_architecture_v2).

Default off. When on, the chat request contains only four content classes:
Persona Core (once), Hard Contracts, Runtime Facts, Output Contract. No random
behavior, no mood permits, no bridge/impulse, no tone priority. Off keeps the
S0 production baseline byte-identical.
"""
SWITCH_KEY = "dialogue_architecture_v2"

HARD_CONTRACTS = (
    "【内容边界】只使用用户原话、当前可见上下文、有出处的记忆和工具回执形成事实判断；"
    "没有依据时不把联想写成已经发生的事，也不替用户补写没说过的事实。"
    "工具只有收到明确回执才能说已经完成或已经写入；信息不足时说不知道或直接问。"
    "不输出系统块名、内部标签或时间元数据的格式。"
)

OUTPUT_CONTRACT = (
    "【输出格式】普通聊天不用 Markdown 标题、粗体或装饰符号；"
    "数学、代码和技术内容保留必要的准确格式；"
    "显示与语音使用同一段正文，一行写完一个意思即可。"
)


def resolve_switches(v1_enabled, v2_enabled, guard_enabled, arch_v2_enabled):
    """dialogue_architecture_v2 excludes every tone-priority switch."""
    if arch_v2_enabled and (v1_enabled or v2_enabled or guard_enabled):
        raise ValueError(
            "dialogue_architecture_v2 cannot be combined with tone_priority_v1/v2 "
            "or tone_local_guard_v1")
    return bool(arch_v2_enabled)


def persona_core(card_path, pack=None, *, character_neutral=False):
    """Persona Core: character card fields once + address constraint only."""
    from character_persona import load_character_persona
    from dialogue_style import ADDRESS_STYLE
    address = ADDRESS_STYLE.replace('只保留静香的性格', '只保留当前角色的性格') if character_neutral else ADDRESS_STYLE
    return load_character_persona(card_path, pack) + "\n" + address


def hard_contracts():
    return HARD_CONTRACTS


def output_contract():
    return OUTPUT_CONTRACT


def system_blocks(persona_text, runtime_parts=()):
    """Ordered four-layer assembly: persona → hard contracts → runtime facts."""
    parts = [persona_text, HARD_CONTRACTS]
    parts.extend(part for part in runtime_parts if part)
    parts.append(OUTPUT_CONTRACT)
    return parts
