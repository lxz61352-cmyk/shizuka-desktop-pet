"""S2 影子候选：从对话片段里提取"值得成为共同经历"的候选，只写日志，不进 SH 库。

纪律（方案 P2c-9.2 §3）：
- 影子模式：候选只进候选日志；S2 阶段不写 SharedHistoryStore、不读；
- 调度器参数化：「每 N 轮 / 足量片段」只是调度参数、可替换（due_fn 可注入）；
  事件是否成立由提取器判定，不由轮次决定；
- 提取判据与人工标注口径一致：三类 + 信息门槛 + 聚合 + recurring 需累积 + 情感本身不记。
"""
import json
import os
import time
import uuid

EXTRACT_MAX_TOKENS = 400
EXTRACT_TEMPERATURE = 0.0   # 提取/分类任务：压到 0 降低跑批间抖动（v3 校准时实测 0.2 有 F07/F09 摆动）

EXTRACT_SYSTEM_PROMPT = """你是角色「静香」的共同经历（Shared History）提取器。任务：从【最近的对话片段】里判断有没有值得记入"共同经历"的内容。宁缺勿滥；只看当前片段，不做跨片段推测；按整个片段合起来读，跨轮的指代与信息合并后再判断。

只记三类（同一潜在事件只保留一条；多类别命中时选一个【主类别】，优先保留更能表达关系 / 认知变化的类别）：
A 事件：有明确主体、以后可能继续推进或被再次提起的事，包括进行中的持续事件（例：准备重要考试、写报告、纠结要不要换工作、学做某个菜谱）。
B recurring：已经形成"反复模式"的共同背景——同一片段里已能看到重复模式（例："我又开始熬夜了"＋"这句我今天听你说过一遍"＋"又做不到"→ B）。单个"又"字、或当前事件恰好发生第二次，不自动等于 B；跨片段累积由后续处理。
C 认知：明确发生了关系或认知变化——判断标准是"转变本身重要"，而不是"用户照做了"（例：用户接受并认真反思了静香对他习惯 / 性格的判断、并开始改变做法 → C；"静香提醒、用户顺手照做"的小事，如收拾桌面，不算 C）。

不记：日常琐事与状态（吃面包 / 天气 / 困了 / 食堂不错）；纯情绪（没有具体对象的抱怨、心情——有具体对象的纠结 / 犹豫不在此列）；对象不明的事（"那件事""那个东西"）——宁缺勿滥，不留下"待补全"的悬念；一次性的无后果小事。

判断规则：
1. 信息门槛：主体明确（考试 / 报告 / 换工作 / 菜谱…）才算够；连"是什么事"都指不出来 → 不记，等以后说清楚再记；
2. 聚合：同一潜在事件只输出一条；同一片段里的多条候选必须互不相关（仅当涉及两件毫无关联的事时才输出多条）——例：同一片段同时像 C 和 B → 只留主类别 C，作为 C 转变基础的反复模式不再单列 B；
3. recurring 的"跨片段 / 跨会话累积"由后续聚合处理，本提取器不替它判断——本片段证据不足就输出空；
4. 置信不足 → 不输出。

输出 JSON 数组（没有值得记的就输出 []），每条格式：
{"summary": "<一句话，用户视角、事实性>", "category": "A 或 B 或 C", "confidence": 0.0-1.0, "reason": "<为什么值得记，20 字内>"}
不要输出别的任何内容。

示例输入：
用户：我今天终于把那个报告交了
静香：总算。
用户：前后拖了快两个星期
示例输出：
[{"summary": "用户拖着写了两周的实习报告终于提交", "category": "A", "confidence": 0.9, "reason": "持续事件完成，后续可能被提起"}]

示例 2（进行中的持续事件）：
输入：用户：我最近在准备一个很重要的考试
输出：[{"summary": "用户在准备一个很重要的考试", "category": "A", "confidence": 0.8, "reason": "进行中的持续事件"}]"""

CATEGORIES = ("A", "B", "C")


def build_extract_input(transcript, known=""):
    return "【已有记录】%s\n\n【最近的对话片段】\n%s" % ((known or "（暂无）"), (transcript or "").strip())


def _clean(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_candidates(raw):
    """从模型输出里取 JSON 数组；容忍围栏与前后噪声；失败返回 []。"""
    text = _clean(raw)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        category = str(item.get("category") or "").strip().upper()[:1]
        if not summary or category not in CATEGORIES:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence"))))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({"summary": summary, "category": category,
                    "confidence": confidence, "reason": str(item.get("reason") or "").strip()})
    return out


def extract_candidates(transcript, call, known=""):
    """调用提取器；失败 / 空片段 → []（调用方跳过）。"""
    transcript = (transcript or "").strip()
    if not transcript or call is None:
        return []
    try:
        raw = call(EXTRACT_SYSTEM_PROMPT, build_extract_input(transcript, known),
                   max_tokens=EXTRACT_MAX_TOKENS, temperature=EXTRACT_TEMPERATURE)
    except Exception:
        return []
    return parse_candidates(raw)


def log_candidates(path, candidates, meta=None):
    """候选追加进 JSONL 日志（一条一行）；返回写入条数。不触碰 SharedHistoryStore。"""
    if not candidates:
        return 0
    meta = meta or {}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            for item in candidates:
                row = {"ts": time.time(), **meta, **item}
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return len(candidates)


class ShadowScheduler:
    """影子候选生成调度器：默认每 N 轮跑一次；due_fn(turn_count, last_run) 可替换。"""

    def __init__(self, every_turns=10, min_turns=4, due_fn=None):
        self.every_turns = max(1, int(every_turns))
        self.min_turns = max(1, int(min_turns))
        self._due_fn = due_fn
        self.last_run_turn = 0

    def due(self, turn_count):
        if self._due_fn is not None:
            return bool(self._due_fn(turn_count, self.last_run_turn))
        if turn_count < self.min_turns:
            return False
        if self.last_run_turn <= 0:
            return True
        return (turn_count - self.last_run_turn) >= self.every_turns

    def mark_run(self, turn_count):
        self.last_run_turn = int(turn_count)


def format_window(pairs):
    """[ (用户文本, 静香回复), ... ] → 提取器窗口文本。"""
    lines = []
    for user_text, reply in pairs or []:
        lines.append("- 用户：%s" % (user_text or "").strip())
        lines.append("- 静香：%s" % (reply or "").strip())
    return "\n".join(lines)


def log_pool_actions(path, actions, source=""):
    """池动作追加进 JSONL 日志；返回写入条数。"""
    if not actions:
        return 0
    try:
        with open(path, "a", encoding="utf-8") as handle:
            for item in actions:
                handle.write(json.dumps({"ts": time.time(), "source": source, **item},
                                        ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return len(actions)


def _tokens(text):
    try:
        import conversation_memory as cm
        return cm.tokens(text or "")
    except Exception:
        clean = "".join(ch for ch in (text or "") if ch.strip())
        return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def _similarity(a, b):
    sa, sb = _tokens(a), _tokens(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


CATEGORY_PRIORITY = ("C", "A", "B")   # 主类别仲裁：更能表达关系 / 认知变化的优先


class CandidatePool:
    """跨窗口候选池（影子）：合并 / 累积候选，只作观察，不写 SharedHistoryStore。

    - 相似候选合并：mentions+1、类别按 C > A > B 仲裁（C 不回退）、记录 categories_seen；
    - stable：mentions >= 2（同一事件被多次看见 → 稳定候选）；
    - note_window：聚合侧的"再次出现"证据（窗口文本与已有条目相似时计一次 window_hits）。
    """

    SIM_THRESHOLD = 0.5        # 候选与条目的合并阈值
    WINDOW_THRESHOLD = 0.34    # 窗口对条目摘要的覆盖率阈值（"再次出现"证据）
    WINDOW_STABLE_MIN = 2      # window_hits 到此值也算 stable

    def __init__(self, path=None):
        self._path = path
        self.entries = []
        self._load()

    def _load(self):
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.entries = [row for row in (data.get("entries") or []) if isinstance(row, dict)]
        except Exception:
            pass

    def save(self):
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "shadow": True, "entries": self.entries}, handle,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            pass

    def _best_match(self, summary):
        best, best_score = None, 0.0
        for entry in self.entries:
            score = _similarity(summary, entry.get("summary", ""))
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= self.SIM_THRESHOLD:
            return best, best_score
        return None, best_score

    def add(self, candidates, source="", now=None):
        """把一轮候选并入池；返回动作列表（new / merged）。"""
        now = time.time() if now is None else now
        actions = []
        for item in candidates or []:
            summary = str(item.get("summary") or "").strip()
            category = str(item.get("category") or "").strip().upper()[:1]
            if not summary or category not in CATEGORIES:
                continue
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence"))))
            except (TypeError, ValueError):
                confidence = 0.0
            match, _score = self._best_match(summary)
            if match is not None:
                match["mentions"] = int(match.get("mentions") or 0) + 1
                match["last_seen"] = now
                seen = match.setdefault("categories_seen", [])
                if category not in seen:
                    seen.append(category)
                match["category"] = next((c for c in CATEGORY_PRIORITY if c in seen), match.get("category"))
                match["confidence_max"] = max(float(match.get("confidence_max") or 0.0), confidence)
                match["stable"] = match["mentions"] >= 2 or int(match.get("window_hits") or 0) >= self.WINDOW_STABLE_MIN
                actions.append({"action": "merged", "id": match["id"], "mentions": match["mentions"],
                                "category": match["category"], "summary": match["summary"]})
            else:
                entry = {"id": "shp_" + uuid.uuid4().hex[:10], "summary": summary, "category": category,
                         "categories_seen": [category], "confidence_max": confidence,
                         "mentions": 1, "window_hits": 0, "stable": False,
                         "first_seen": now, "last_seen": now}
                self.entries.append(entry)
                actions.append({"action": "new", "id": entry["id"], "mentions": 1,
                                "category": category, "summary": summary})
        self.save()
        return actions

    def note_window(self, window_text, now=None):
        """聚合侧证据：窗口文本覆盖已有条目关键词 → 该条目 window_hits+1（不产生新候选）。

        口径：条目摘要 token 被窗口覆盖的比例（窗口对摘要的覆盖率），比候选间相似度宽松。
        """
        now = time.time() if now is None else now
        window_tokens = _tokens(window_text)
        hits = []
        for entry in self.entries:
            entry_tokens = _tokens(entry.get("summary", ""))
            if not entry_tokens or not window_tokens:
                continue
            score = len(entry_tokens & window_tokens) / max(1, len(entry_tokens))
            if score >= self.WINDOW_THRESHOLD:
                entry["window_hits"] = int(entry.get("window_hits") or 0) + 1
                entry["last_seen"] = now
                entry["stable"] = entry["mentions"] >= 2 or entry["window_hits"] >= self.WINDOW_STABLE_MIN
                hits.append({"action": "window_hit", "id": entry["id"], "window_hits": entry["window_hits"],
                             "summary": entry["summary"]})
        if hits:
            self.save()
        return hits
