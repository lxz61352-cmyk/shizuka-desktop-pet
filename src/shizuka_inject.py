"""P2b 注入：稀疏状态行 + 原作参考块。

原则（GPT 评审定死）：
- 行为名不写进提示词——系统选方向，模型定说法；
- 状态稀疏注入：正常/轻微偏离不说，明显偏离说一句，最多 3 条；
- 案例只参考反应方式/距离/情绪/信息量，不模仿措辞句式口头禅。
"""
CASUAL_KINDS = ("share_casual", "share_achievement", "share_negative", "praise",
                "tease", "challenge", "greeting", "general")

REFERENCE_RULE = "只参考她的反应方式、说话距离、情绪和信息量，不要模仿措辞、句式或口头禅。"


def relationship_line(relationship):
    rel = relationship.values
    lines = []
    if rel["familiarity"] < 0.40:
        lines.append("和用户还在熟悉，保留自己的分寸；不需要用冷淡、质疑或训斥刻意拉开距离")
    elif rel["familiarity"] >= 0.75:
        lines.append("和用户已经很熟，相处自然，不用客套")
    if rel["playfulness"] >= 0.60:
        lines.append("两人之间开玩笑已经很自然，可以互相逗")
    if rel["respect"] < 0.40:
        lines.append("最近被用户轻慢过，会有点不客气")
    if rel["comfort"] < 0.40:
        lines.append("最近相处有点别扭，话会少一些")
    return "；".join(lines) if lines else None


def state_lines(char_state, max_items=3):
    """只描述「心理/语气状态」，不描述「她想做什么」——状态不发送行为指令。"""
    cs = char_state.values
    candidates = []
    if cs["playfulness"] >= 0.60:
        candidates.append((cs["playfulness"] - 0.40, "她现在有一点玩心，语气可以松一点"))
    elif cs["playfulness"] <= 0.25:
        candidates.append((0.40 - cs["playfulness"], "她现在没什么玩心，语气比较平"))
    if cs["embarrassment"] >= 0.35:
        candidates.append((cs["embarrassment"] - 0.10, "她现在有点不好意思"))
    if cs["social_openness"] <= 0.40:
        candidates.append((0.60 - cs["social_openness"], "她现在比较安静，话不多"))
    if cs["seriousness"] >= 0.60:
        candidates.append((cs["seriousness"] - 0.35, "她现在比平时更较真"))
    if cs["curiosity"] >= 0.65:
        candidates.append((cs["curiosity"] - 0.45, "她现在更容易注意到细节"))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in candidates[:max_items]]


def reference_block(examples):
    if not examples:
        return ""
    lines = ["【参考】类似情境下她曾这样反应——" + REFERENCE_RULE]
    for entry in examples:
        lines.append("- 「%s」" % (entry.get("text") or "").strip())
    return "\n".join(lines)


def build_character_blocks(situation, char_state, relationship, examples):
    """返回 (rel_line, state_text, reference)。

    rel_line 需要调用方做「变化才注入」的缓存；state_text 每轮现算；
    任务/特殊路径返回 (None, "", "") 表示保持旧机制。
    """
    kind = situation.get("kind") or "general"
    if kind not in CASUAL_KINDS:
        return None, "", ""
    rel_line = relationship_line(relationship)
    states = state_lines(char_state)
    state_text = "【状态】" + "；".join(states) + "。" if states else ""
    return rel_line, state_text, reference_block(examples)
