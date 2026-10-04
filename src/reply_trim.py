"""对话输出的窄剪除钩子：只删两类已证实的越界内容，不重写、不生成。

为什么单独写这一层
------------------
`daily-examples-v1` 这条线上，所有挂在 `not arch_v2` 分支上的语义护栏都不执行
（`enhanced_dialogue_v2=True` 令 `arch_v2=True`），于是输出侧只剩格式清理。两轮提示词
实验（`测试记录/原作语料对齐与少叮嘱-2026-09-30/`、`.../原作语料对齐第二轮-因子分离-.../`）
显示：示例与措辞都压不住「告别后追加叮嘱」和「无来源的共同前文」，所以需要一道程序闸门。

与既有模块的关系
----------------
- `shizuka_admission.MGMT_STRONG_RE` 含 `快|到底` 等过宽词，且需要 planner 的 authority；
- `shizuka_admission.UNSUPPORTED_PRIOR_RE` 只覆盖「助手自己说过什么」，抓不到
  「是之前你念叨的那组吗」这类关于**用户**的无据前文；
- `reply_evidence_prune` 自述「never a production reply hook」，且按句删依据。
本模块因此只做两件事，且两条规则都要求**明确的触发条件**，宁可漏删不可误删：

1. `trim_farewell_addon`：用户这轮是在告别/离开，回复在告别语之后又追加了叮嘱、邀约或新话题。
2. `trim_unsupported_history`：回复声称双方有过某段前文，而可见上下文里找不到任何对应内容。

两条规则都：
- 只删整句，不改写、不生成、不调用模型；
- 永不动第一句；
- 删空则原样返回；
- 返回被删内容，便于离线复核与日志。
"""
import re

SENT_SPLIT_RE = re.compile(r"[^。！？!?…\n]+[。！？!?…]*")

# 短回复的界限：去掉末尾句号只在"整条就一个句子且不超过这么多字"时做。
# 原作静香短的单个句子里 37% 带句号，线上 67%——用户反馈「都是短句回复却每句都加句号」。
SHORT_REPLY_CHARS = 20

# 用户这轮在告别/离开。要求「离开动词 + 语气收尾」或明确的告别套语，
# 不能只凭「去了」这类过宽词触发。
# 用户这轮在告别/离开。必须由「第一人称 + 打算」引出离开动作，不能只出现离开动词：
# 真实聊天里「上下文太短了」「把他们赶走了」「走一会儿回图书馆了」都曾被误判成告别。
# 另收一组明确的告别套语（收在句尾才算）。
FAREWELL_RE = re.compile(
    r'(?:我|咱)(?:先|要|得|该|就|也|还得|打算)?\s*'
    r'(?:去|走|睡|撤|闪|下线|忙|开会|上课|上班)[^，。！？!?]{0,8}[了啦咯嘞]'
    r'|(?:先这样|先不聊|回头聊|待会儿聊|晚点聊|有空聊|之后再聊|下次聊|拜拜|再见|晚安|不聊了)'
    r'[。！？!?…～~\s]*$')

# 保留的纯告别套语：本身就是告别语的一部分，不算「加话」。
KEEP_FORMULA_RE = re.compile(
    r'^(?:嗯|哦|好|行|那|先|诶|去|晚安|早|「|」|，|,|\s)*'
    r'(?:晚安|好梦|做个好梦|回头聊|回头见|明天见|再见|拜拜|慢走|路上小心|路上慢点|注意安全|'
    r'好好吃|早点休息|醒了再聊|醒了聊|睡醒聊|去吧|睡吧|嗯|好|行)'
    r'(?:[。！？!?…～~，,、\s「」]*)$')

# 一句里若开头就是告别应答，整句保留：
# 「去睡吧，别撑着。」删掉就会让回复不再回应告别；「回来要是想聊，接着…」则照删。
ACK_TOKEN_RE = re.compile(
    r'去吧|去睡吧|睡吧|晚安|好梦|回头聊|回头见|明天见|再见|拜拜|慢走|'
    r'路上小心|路上慢点|注意安全|好好吃|早点休息|醒了再聊|醒了聊|慢慢吃')

# 追加内容的标记：把责任推给用户去执行，或另起一个话题。
# 未来指代一律要求 {1,10}（至少夹一个字），否则「回头聊。」这类纯告别套语会被吃掉。
ADDON_RE = re.compile(
    r'记得|别忘了|别忘|说一声|说给我|跟我说|告诉我|讲给我|跟我讲|和我说|跟我说说|'
    r'要是[^，。！？!?]{0,14}(?:就|再|记得|跟|说|聊|讲|吐槽|找|喊|叫)|'
    r'回来[^，。！？!?]{1,10}(?:说|聊|讲|告诉)|回头[^，。！？!?]{1,10}(?:说|聊|讲|告诉)|'
    r'开完[^，。！？!?]{1,10}(?:说|聊|讲|告诉|吐槽)|醒了[^，。！？!?]{1,10}(?:说|聊|讲|告诉)|'
    r'别[^，。！？!?]{0,6}(?:撑着|硬撑|熬夜|糊弄|光顾|磨蹭|忘)|'
    r'别[^，。！？!?]{1,7}了[。！]?|'
    r'[？?]')

# 声称双方有过前文。只认这些标记，不靠「那个/这个」这类泛指。
# `(?<!晚)上回`：「晚上回来要是淋湿了」里的「上回」不是标记，真实回放里误删过一次。
HISTORY_MARK_RE = re.compile(
    r'上次|(?<!晚)上回|之前|那次|那天|你说过|你以前|还记得|昨天|刚刚说|刚才说|先前')

# 用户这轮是在提问/求助，而不是随口分享。这时结尾的追问通常有用（「你是想按肩颈还是全身？」
# 不问就答不对），所以填充式追问规则在这类回合上不启用。
# 判据故意放宽——多认成「求助」只会少删，少认才会误删（真实回放里实测误删过
# 「再给我讲一下」「会不会效率高一些」「有什么区别」这几种说法）。
REQUEST_RE = re.compile(
    r'[？?]|怎么|如何|为什么|为啥|帮我|帮忙|教我|告诉我|给我|推荐|建议|该不该|要不要'
    r'|能不能|可以吗|好不好|行不行|值不值|选哪|哪家|哪个好|怎么办'
    r'|是谁|什么是|是什么|意思|区别|差别|一样吗|对不对|会不会'
    r'|讲一下|说一下|看看|看一下|查一下|查查|搜一下|找一下|求|麻烦'
    r'|不会|不懂|没看懂|不明白|看不懂|卡住|学不会|搞不懂|弄不明白')

# 「先在心里编一个具体画面，再要对方确认」的追问。不索取任何未知信息，
# 对方答不答都不影响回复成立——这正是用户嫌的那种「无意义追问」。
GUESS_PROBE_RE = re.compile(
    r'是不是|是那种|那种[^，。！？!?]{0,10}[吗呢]|对吧|是吧|该不会|难道|会不会'
    r'|还是[^，。！？!?]{0,12}[吗呢？?]')

_STOP = set('的了是在有和与就都也还很才又把这个那个什么怎么为所以以及对从到给被让向'
            '一二三四五六七八九十不没你我他她它们之其而且但如果因为这样那样一样')

_HISTORY_WORDS = set('上次 上回 之前 那次 那天 昨天 之前 以前 说过 说过 还记得 刚才 刚刚 先前'.split())

# 「我之前做过 X」是角色讲自己的经历（心菜的绘本、静香的排练），不是「双方共同前文」。
# 换角色复核时误删过「我之前在绘本里看到过…」。只有标记后面紧跟言语动词（我跟你说过）
# 才算共同前文。
_SELF_MARK_RE = re.compile(r'我(?:也|就|还|又)?(?:之前|上次|上回|那次|那天|以前)')
_SPEECH_RE = re.compile(r'说|讲|聊|提|问|念叨|告诉|发给|给我看|给你看')

# 纯指代/叙述用语。一个句子如果只由这些字组成（「这个你之前跟我讲过的，我记着呢。」），
# 就没有任何具体内容可以核对，永远对不上出处——真实回放里这类句子被误删过一次。
# 因此要求待删句至少含两个「具体内容」二元组，否则跳过不删。
_META_CHARS = set('这个那个你我他她它们之之前后上次回那说讲过告诉记着得呢吗啊了的跟和与是不有'
                  '事话情好么怎哪谁把被让给对于为其而且但因所以如果虽然可以要不要会能')


def _sentences(text):
    return [part.strip() for part in SENT_SPLIT_RE.findall(text or "") if part.strip()]


def _bigrams(text):
    """只取汉字二元组，滤掉虚词，避免用一个「的」字就判定有出处。"""
    chinese = re.sub(r'[^\u4e00-\u9fff]', '', text or '')
    out = set()
    for i in range(len(chinese) - 1):
        pair = chinese[i:i + 2]
        if pair[0] in _STOP and pair[1] in _STOP:
            continue
        if pair in _HISTORY_WORDS:
            continue
        out.add(pair)
    return out


def _content_bigrams(text):
    """只留「具体内容」的二元组，滤掉纯指代与虚词。"""
    return {bg for bg in _bigrams(text) if not (bg[0] in _META_CHARS and bg[1] in _META_CHARS)}


def is_farewell(user_text):
    """用户这轮是不是在告别/离开。"""
    text = (user_text or '').strip()
    if not text or len(text) > 80:
        return False
    return bool(FAREWELL_RE.search(text))


def _ack_split(part):
    """若一句以告别应答开头（前面只允许「嗯/哦/好/行/那/先/诶」这类语气垫词），
    返回 `(应答前缀, 其余部分)`；否则返回 None。

    「去睡吧，别撑着。」→（「去睡吧」, 「，别撑着。」）
    「嗯，去吧，别又光顾着刷手机。」→（「嗯，去吧」, 「，别又光顾着刷手机。」）
    「回来要是想聊，接着刚才的说就行。」→ None（开头不是应答）
    """
    match = ACK_TOKEN_RE.search(part)
    if not match:
        return None
    prefix = part[:match.start()]
    if not re.fullmatch(r'[\s，,、]*(?:嗯|哦|好|行|那|先|诶|啊|呀)?[\s，,、]*', prefix):
        return None
    head = part[:match.end()]
    if not head.endswith(('。', '！', '？', '…')):
        head += '。'
    return head, part[match.end():]


def trim_farewell_addon(reply, user_text, piece='whole'):
    """用户在告别时，删掉回复里告别语之后追加的叮嘱、邀约或新话题。

    `piece` 描述这段文本在微信分条里的位置：
    - `'whole'` 整条回复，或 `'first'` 分条的第一条：保护首句，永不返回空串；
    - `'tail'` 分条的后续条：不保护首句，允许返回空串（表示这一条不该发出去）。

    返回 `(新文本, 被删句列表)`。纯告别套语保留。
    """
    original = (reply or '').strip()
    parts = _sentences(original)
    if not parts:
        return original, []
    protect = piece != 'tail'
    kept, removed = [], []
    for index, part in enumerate(parts):
        ack = _ack_split(part)
        if ack and ack[1] and ADDON_RE.search(ack[1]):
            # 应答后面挂着叮嘱/邀约：只留应答。
            kept.append(ack[0])
            removed.append(ack[1].lstrip('，,、'))
            continue
        if index == 0 and protect:
            # 整条/首条的第一句只允许上面那种「只留应答」的裁剪，绝不整句删除。
            kept.append(part)
            continue
        if len(part) <= 10 and KEEP_FORMULA_RE.match(part):
            kept.append(part)
            continue
        if ADDON_RE.search(part):
            removed.append(part)
            continue
        kept.append(part)
    if not removed:
        return original, []
    text = ''.join(kept).strip()
    if text:
        return text, removed
    return ('', removed) if not protect else (original, [])


def trim_unsupported_history(reply, history_text, user_text='', piece='whole'):
    """删掉声称双方有过某段前文、但可见资料里找不到任何对应内容的句子。

    `history_text` 必须是模型当时真正能看到的**全部事实资料**：可见对话历史、长期记忆块、
    待办备注、摘要等。只传对话历史会误删——真实聊天里「你之前跟我讲过蜂蜜特饮」这类引用
    是对的，只是超出最近若干条消息。**特别注意：不要把关卡卡里的口吻示例算进出处**，
    示例本身声明「不是用户的真实记忆」。调用方若无法提供完整资料，就不要启用这条规则。

    判定用汉字二元组重合：一个都不重合才算无据。宁可漏删——能对上任何一小段就保留。
    `piece` 语义同 `trim_farewell_addon`。返回 `(新文本, 被删句列表)`。
    """
    original = (reply or '').strip()
    parts = _sentences(original)
    if not parts:
        return original, []
    protect = piece != 'tail'
    visible = _bigrams(history_text or '') | _bigrams(user_text or '')
    kept, removed = [], []
    for index, part in enumerate(parts):
        self_experience = ('我' in part) and not re.search(r'你|咱|我们', part)
        mark = _SELF_MARK_RE.search(part)
        if mark and not _SPEECH_RE.search(part[mark.end():mark.end() + 12]):
            self_experience = True
        # 「之前」也常用于一般时间指代（「绕回之前的状态」「恢复到之前的版本」）。
        # 只有当这句话是在讲**双方的**交流或用户本人时，才算「共同前文」声称。
        # 真实微信里误删过一次数学讲解：用户问单纯形法退化，回答里的
        # 「理论上可能绕回之前的状态」被当成了无据前文。
        about_shared = bool(re.search(r'你|咱|我们', part)) or bool(_SPEECH_RE.search(part))
        if self_experience or not about_shared:
            kept.append(part)
        elif index == 0 and protect:
            # 第一句不整句删除，避免删空；只可能在下面被别的规则裁尾。
            kept.append(part)
        elif len(_content_bigrams(part)) < 2:
            # 没有具体内容可核对（纯指代句），一律不删。
            kept.append(part)
        elif HISTORY_MARK_RE.search(part) and len(_bigrams(part) & visible) < 2:
            # 要两个以上二元组重合才算「有出处」。一个通用二字组（「拍的」「照片」）不算证据——
            # 心菜实聊里「之前你说去拍的那组吗」就是被一个「拍的」放过去的。
            removed.append(part)
        else:
            kept.append(part)
    if not removed:
        return original, []
    text = ''.join(kept).strip()
    if text:
        return text, removed
    return ('', removed) if not protect else (original, [])


def is_request(user_text):
    """用户这轮在提问/求助（而不是随口分享）。"""
    text = (user_text or '').strip()
    if not text or len(text) > 120:
        return False
    return bool(REQUEST_RE.search(text))


def _is_question(sentence):
    return bool(re.search(r'[？?]\s*$', sentence) or re.search(r'[吗呢][，,。！!…\s]|[吗呢][。！!]?\s*$', sentence))


def trim_filler_probe(reply, user_text, piece='whole'):
    """用户在随口分享时，删掉结尾那句「编个画面再要你确认」的追问。

    「哦，烤红薯！这个季节吃正合适。/ 是那种捧在手里烫得来回换手的吗，哈哈。」
    →「哦，烤红薯！这个季节吃正合适。」

    只在用户这轮**不是在提问/求助**、且该句确实是猜测式追问时才删；
    求助回合里的澄清问句（「你是想按肩颈还是全身？」）一律保留。
    返回 `(新文本, 被删句列表)`；`piece` 语义同 `trim_farewell_addon`。
    """
    original = (reply or '').strip()
    parts = _sentences(original)
    if not parts or is_request(user_text):
        return original, []
    protect = piece != 'tail'
    if protect and len(parts) < 2:
        # 整条只有这一句时不删，否则会把回复删空。
        return original, []
    kept, removed = list(parts), []
    while kept:
        if len(kept) == 1 and protect:
            break
        last = kept[-1]
        if _is_question(last) and GUESS_PROBE_RE.search(last):
            removed.insert(0, kept.pop())
        else:
            break
    if not removed:
        return original, []
    text = ''.join(kept).strip()
    if protect and len(re.sub(r'^[\s嗯哦好行诶啊呀那，,。！？!?…]*', '', text)) < 3:
        # 删完只剩「哦？」这种语气词，比留着追问更糟，索性不动。
        return original, []
    if text:
        return text, removed
    return ('', removed) if not protect else (original, [])


def visible_facts(history_messages=(), *blocks):
    """组装「可见事实资料」，供 `trim_unsupported_history` 判定出处。

    只放模型能看到、且**代表真实事实**的东西：对话历史、长期记忆块、待办备注、摘要等。
    不要把角色卡与口吻示例放进来——示例本身声明「不是用户的真实记忆」，
    算进去会让该删的无据前文删不掉（「接缝」就同时出现在示例里）。
    """
    parts = []
    for message in history_messages or ():
        if isinstance(message, dict):
            content = message.get('content')
            if isinstance(content, str):
                parts.append(content)
        elif isinstance(message, str):
            parts.append(message)
    for block in blocks:
        if isinstance(block, str) and block.strip():
            parts.append(block)
    return '\n'.join(parts)


def trim_trailing_period(text, piece='whole'):
    """短的单句回复去掉末尾句号。

    用户反馈「还是喜欢在每句话后面加句号，但是都是短句回复」。
    实测（2026-10-01）：

      原作静香：短的单个句子里 **37%** 带句号
      线上微信：**67%**（最近 120 条 56%）

    提示词里"标点跟着长短走"那条已经写了却压不住，所以这里用确定性的钩子做——
    **标点是机械的事，交给程序比交给模型可靠**。

    只动一种情况：**整条就一个句子、且短**，末尾是「。」就摘掉。
    长回复、多句回复、代码块、控制标记一律不碰。
    """
    original = text or ''
    stripped = original.strip()
    if not stripped.endswith('。'):
        return text, []
    if '`' in original or '[[WX_' in original:
        return text, []
    body = stripped[:-1]
    if len(re.sub(r'\s', '', body)) > SHORT_REPLY_CHARS:
        return text, []
    if len(_sentences(body)) != 1:
        return text, []
    # 返回的必须是**被删条目列表**，和别的规则一致——
    # 第一版返回了 [('trailing_period', [...])]，被 trim_reply 又包一层，
    # 结果 notes 变成嵌套元组，回放工具直接崩。
    return body, [stripped]


def trim_reply(reply, user_text='', history_text='', piece='whole'):
    """按顺序跑几条规则，返回 `(新文本, 说明)`；没有改动时说明为空。

    `piece`：`'whole'` 桌面端整条回复；`'first'` / `'tail'` 微信分条的第一条与后续条。
    只有 `'tail'` 可能返回空串，表示这一条不该发出去。
    """
    text = (reply or '').strip()
    notes = []
    if is_farewell(user_text):
        text, removed = trim_farewell_addon(text, user_text, piece)
        if removed:
            notes.append(('farewell_addon', removed))
    text, removed = trim_filler_probe(text, user_text, piece)
    if removed:
        notes.append(('filler_probe', removed))
    text, removed = trim_unsupported_history(text, history_text, user_text, piece)
    if removed:
        notes.append(('unsupported_history', removed))
    text, removed = trim_trailing_period(text, piece)
    if removed:
        notes.append(('trailing_period', removed))
    if not notes:
        return (reply or '').strip(), []
    return text, notes
