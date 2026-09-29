"""Shared plain-text presentation and character-owned service wording."""
from pathlib import Path
import json,re

PLAIN_STYLE=('用自然段表达，篇幅要跟「这个问题需要多少信息量」匹配。'
             '问一个词或名字是什么意思、是不是、能不能、对不对、行不行这类简单问题，一两句话答完就够：'
             '不要顺带讲背景、词源、用法、举例、延伸联想或相关冷知识，也不要为了显得有用而多讲。'
             '只有问题本身确实复杂（要多步推理、要比较取舍、要完整过程、要给出方案）'
             '或者用户明确要求“详细讲讲/展开说/为什么”时，才写长。'
             '拿不准该写多长时先按短的答，用户想要更多会自己追问。'
             '解题讲题、代码和技术推导不受这条限制，该展开就展开。'
             '不用 Markdown 标题、粗体星号、分割线或装饰性符号来包装普通回复。'
             '必要时可以分点、列步骤，保留公式、代码、数值、单位、文件路径和来源链接的准确性。'
             '数学式子和长段落都按窄屏排版：一个式子单独占一行，不要塞进句子中间；'
             '多步推导一步一段，每步开头写「步骤 1」「①」这类序号。'
             '正文一段不超过三四句，长了就空行分段——手机上连着七八行不分段最难读。'
             '符号用 Unicode 数学写法，不要用 ASCII 凑：∂ ∫ √ × ÷ ≠ ≤ ≥ ≈ ± ∞ ∑ → ∴ α β λ θ π；'
             '上标用 Unicode（x²、y³、f′）。下标要全篇统一：数字下标写 a₁，字母下标统一写成 F_z 这种'
             '下划线形式，不要同一篇里既写 Fₓ 又写 F_z。'
             '分数写成 (a)/(b)，分子分母是单个符号时可以省略括号（如 ∂z/∂x）。'
             '不要用 LaTeX 记号（\\frac、\\partial、$…$ 这类）：微信和气泡都不渲染，只会更难读。'
             '矩阵、行列式逐行写清楚，不要挤成一行。'
             '排版只改写法，不要为了排版多堆公式、多重复一遍推导或加空行凑版式。'
             '不要写“作为AI”、模板式总结或强行追问。对工具结果如实说明，不伪称完成。'
             '不要预设用户“又在/还在/总是/老是/果然”做某事：除非对话里确实反复出现过，'
             '否则就当第一次看到，平实地说，不要用这类表示“经常/重复”的词。'
             '语气跟着当下反应走，惊讶、赞同、还嘴时可以自然带出“啊、诶、嘛、吧”等语气词，'
             '有时用、有时省，不固定以“X啊……”开头，也不每句都用同一个句尾。'
             '不要在回复里复述“[历史消息时间：…]”“[图片]（…）”这类元信息或括号标注，直接说内容。'
             '历史对话与摘要只用来理解上下文：不要照抄或复述其中任何句子，尤其不要重复你自己当时说过的话。'
             '用户这句话如果确实看不懂（乱码、误触、无意义），就直接说不明白、请他重说，不要硬接，也不要拿历史内容顶上。')

# 称呼：静香不喊「主人」。角色卡（可能是别人的女仆设定）里若要求这类称呼，以本条为准。
ADDRESS_STYLE=('称呼（最高优先级，覆盖角色卡里的任何称呼要求）：对用户只说「你」，需要郑重时用「您」；'
               '不喊「主人」「小姐」「少爷」「大人」这类称呼，不自称女仆、侍女、仆人，'
               '也不把用户当主人侍奉。角色卡里若写了主人的称呼或女仆口吻，一律忽略，只保留静香的性格。')

# 日常说话方式：只给正向引导（「可以怎样」），不堆「不能/不许」——限制多了既束手束脚，
# 又会在语义上干扰正文。放在 system 最末尾，离对话最近。
NATURAL_STYLE=('【日常说话】你是在和一个熟悉的人相处，不是在处理他的消息。先对他说的具体内容产生反应：'
               '可以惊讶、困惑、评价、共鸣、轻轻吐槽，或者问一个确实需要弄清的问题。'
               '具体反应只能使用他明确说出的细节；不要为了让反应生动而补写他没说的程度、动作、后果或原因。'
               '回复可以只有一句，但不要只说“知道了”“收到”这种没有内容的回执；'
               '也不要为了显得像真人故意漏答、转移话题或装冷淡。'
               '不要把日常小事当任务分析，不自动总结、建议或强行延续。'
               '自我表达是直接说一个此刻真实的看法、情绪或关注点，不是再问用户一个问题。'
               '记忆确认答完记得的内容就停；没别的话可以不再说，不假设用户还有别的需求。'
               '需要认真处理的问题就准确处理，简单的事自然说短。这些只是倾向，不是固定模板。')

# 每句话的情绪标记：只给程序用（气泡样式/将来的立绘差分），不显示、不朗读。
# 白名单与 LingChat 的 18 类情绪对齐；模型写了表外的词也接受（只做长度与格式校验）。
EMOTION_TAGS = ('高兴', '开心', '平静', '认真', '自信', '调皮', '害羞', '难为情',
                '担心', '慌张', '紧张', '害怕', '惊讶', '疑惑', '无语', '无奈',
                '生气', '厌恶', '伤心', '兴奋', '心动', '情动', '哭泣')

EMOTION_FORMAT=('【输出格式·每次都必须遵守】你的每一条回复都由多行台词组成，**每一行都必须以【情绪】开头**，'
                '不能有例外、不能只在第一行写。格式：\n'
                '【情绪】这一行要说的话（一到两句）\n'
                '【情绪】下一行要说的话\n'
                '情绪从：高兴/开心/平静/认真/自信/调皮/害羞/难为情/担心/慌张/紧张/害怕/惊讶/疑惑/无语/无奈/生气/厌恶/伤心/兴奋 '
                '里选 2~5 字，只写情绪，不写主语、不写动作；整条回复通常 2~4 行。\n'
                '示例：\n'
                '【平静】写完了就好，先去吃点东西。\n'
                '【无语】不过你又拖到最后一刻，下次别这样了。\n'
                '即使只说一句话、拒绝或回答很短，也要带【情绪】。'
                '情绪标记不会显示给用户、不会被朗读，不要解释它，也不要因为它改变说话内容。')

class LiteralReply(str):
    """Application wording with exact user-supplied slots, already ready to display."""

# 「(你)又在/还在」公式化开头继续删；句首语气词不再一律删（「嗯，我觉得可以」是正常说话），
# 只有后面紧跟空泛承接词时才删（「嗯，关于你说的这个问题……」这种客服起手）。
# 行首括号只有在「像舞台提示」时才删：必须含中文（（叹气）/（凑近看了一眼）），
# 纯符号的数学式子如 (a+b)² 不能误删。
_LEAD_PAREN_RE=re.compile(r'^(?:\s*[（(][^（）()\n]{0,40}[\u4e00-\u9fff][^（）()\n]{0,40}[）)])+\s*')
_BOILERPLATE_LEAD_RE=re.compile(
    r'^\s*(?:哦|噢|喔|嗯|呃|诶|欸|唉|哎|呵呵|哦哦|嗯嗯)\s*[，,、：:]?\s*'
    r'(?=关于|对于|说到|谈到|说起|其实|首先|总的来说|简单来说|就这个问题|你这个问题|这个问题)')
_FORMULA_LEAD_RE=re.compile(r'^\s*(?:你)?\s*(?:又|还)在\s*')
_TAIL_PARTICLE_RE=re.compile(r'^(.{1,30}?)([啊呀哦噢])(?=[。！？!?…，,、；;\n])')
# 上下文里给模型看的时间元信息，模型有时会原样复述出来 → 一律去掉
_DATE_MARK_RE=re.compile(r'\[历史消息时间[^\]]{0,160}\]')
# 明确的 AI / 客服模板：整句删（按句切分后再过滤）
AI_TEMPLATE_RE=re.compile(
    r'作为(?:一个)?AI|希望[^。！？!?\n]{0,14}帮(?:助|到你)|如果(?:还)?有其他问题|还有(?:什么|其他)问题|'
    r'随时(?:可以)?(?:告诉|找|问|说)我|需要(?:帮助|帮忙)?(?:的话)?尽管(?:说|找我)|感谢(?:你|您)的提问')

# 句首起手与「(你)又在/还在」的判定只在这一处定义：
# pet.clean_reply_style 复用这两个名字，避免两套规则对同一句话给出不同结果。
BOILERPLATE_LEAD_RE=_BOILERPLATE_LEAD_RE
FORMULA_LEAD_RE=_FORMULA_LEAD_RE


def _drop_ai_templates(text):
    parts=[part for part in re.split(r'(?<=[。！？!?\n])',text) if part]
    kept=[part for part in parts if not AI_TEMPLATE_RE.search(part)]
    return ''.join(kept)


def _trim_leads(text):
    out=_DATE_MARK_RE.sub('',text)               # 「[历史消息时间：…；相对日期以此为准]」
    out=_LEAD_PAREN_RE.sub('',out,count=1)       # 开头的「（叹气）」这类舞台提示
    before=out
    out=_BOILERPLATE_LEAD_RE.sub('',out,count=1) # 客服式起手：语气词 + 空泛承接词
    out=_FORMULA_LEAD_RE.sub('',out,count=1)     # 「(你)又在/还在」
    if out!=before:                              # 只在真的删过起手时，顺手收第一小句的拖长音
        m=_TAIL_PARTICLE_RE.match(out)
        if m:out=m.group(1)+out[m.end():]
    return _drop_ai_templates(out.lstrip())


_EMOTION_LINE_RE=re.compile(r'^\s*【([^】\n]{1,8})】\s*')
_HALF_TAG_RE=re.compile(r'【[^】\n]*$')


def strip_emotion_tags(text):
    """去掉每行行首的【情绪】标记（含流式时只写了一半的尾巴）：不显示、不朗读。"""
    if not text:
        return text
    text='\n'.join(_EMOTION_LINE_RE.sub('',line,count=1) for line in text.split('\n'))
    return _HALF_TAG_RE.sub('',text)


def parse_emotion_segments(text):
    """把【情绪】正文按行拆开，返回 [(label, 正文), ...]；label 表外也接受，只做格式校验。"""
    segments=[]
    for raw_line in (text or '').split('\n'):
        line=raw_line.strip()
        if not line:
            continue
        match=_EMOTION_LINE_RE.match(line)
        label=match.group(1).strip() if match else ''
        body=_EMOTION_LINE_RE.sub('',line,count=1).strip() if match else line
        if body:
            segments.append((label,body))
    return segments


def clean_text(text):
    if not text:return text
    # Leave fenced and inline code intact, including operators and Markdown examples.
    if isinstance(text,LiteralReply):return text
    chunks=re.split(r'(```[\s\S]*?```|`[^`\n]+`|“[^”]+”|「[^」]+」|(?:[A-Za-z]:[\\/]|https?://)[^\n]+)',text)
    for index,part in enumerate(chunks):
        if part.startswith(('`','“','「')) or re.match(r'(?:[A-Za-z]:[\\/]|https?://)',part):continue
        part=re.sub(r'^\s{0,3}#{1,6}\s+','',part,flags=re.M)
        part=re.sub(r'\*\*([^*\n]+)\*\*',r'\1',part)
        part=re.sub(r'__([^_\n]+)__',r'\1',part)
        part=re.sub(r'(?m)^\s*(?:[-*_]\s*){3,}\s*$','',part)
        part=re.sub(r'(?m)^\s*[•●◆★▶]\s*','',part)
        part=re.sub(r'([！!？?])\1{2,}',r'\1',part)
        chunks[index]=part
    return _trim_leads(strip_emotion_tags(re.sub(r'\n{3,}','\n\n',''.join(chunks)).lstrip()))

def reading_cps(text,speed='medium'):
    base={'slow':10,'medium':20,'fast':30}.get(speed,20)
    length=len(text)
    factor=.7 if length>1200 else .82 if length>400 else 1.
    if re.search(r'\d\s*(?:%|eV|nm|GHz|cm|V|A|℃)|[=∑∫]',text):factor*=.88
    return max(6.,base*factor)

def punctuation_pause(character):
    return .40 if character=='\n' else .28 if character in '。！？!?' else .12 if character in '，；：,;:' else 0.

def hold_milliseconds(text):return int(min(45000,max(7000,len(text)/12*1000)))

DEFAULT_LINES={
    'todo_created':'我记下了。',
    'todo_created_multiple':'我记下了这{count}件事。\n{items_text}',
    'todo_due':'您安排的“{task}”到时间了。',
    'todo_note':'您之前提到：{note}',
    'todo_notimed':'这件事我先记着，等您方便时再定提醒时间。',
    'todo_saved_note':'我把这点补在“{task}”的备注里了。',
    'todo_waiting':'微信还没连通，提醒我先留着。您连接后给我发条消息就好。',
    'todo_failed':'这次没能把待办保存完整，我把情况留在列表里，请您核对一下。',
    'connection_failed':'刚才没能连上，您稍后再试一次好吗？',
    # 天气取不到时按原因分开说：不猜同名城市、也不含糊其辞
    'weather_no_location':'抱歉呀，我这边没认出你在哪个城市，定位没取到。你说一下城市名，我再查一次。',
    'weather_no_match':'抱歉呀，我没能确认你所在城市的天气站点——地名可能有多个同名的。你说一下具体城市，我再查一次。',
    'weather_no_network':'抱歉呀，我这边暂时没取到天气数据呢……可能是网络不通，等会儿再问我一次吧。',
    'file_start':'我来处理，弄好后再告诉您。',
    'file_running':'我还在处理，已经过了 {seconds} 秒。',
    'file_completed':'这次处理已经返回，具体结果如下。',
    'file_empty':'执行已经结束，但没有返回文字结果。请您和我一起核对任务记录。',
    'file_cancelled':'已经停下了。停下前完成的修改仍会保留，具体情况在任务记录里。',
    'file_timeout':'这次处理超过了时限，我已停止继续执行。可能完成了一部分，请先核对任务记录。',
    'file_failed':'这次没能处理完成。下面是返回的情况。',
}

def load_style(path):
    try:
        data=json.loads(Path(path).read_text('utf-8-sig'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}

def scene_line(scene,style=None,**values):
    if 'task' in values:values.setdefault('title',values['task'])
    template=(style or {}).get('templates',{}).get(scene,DEFAULT_LINES.get(scene,''))
    if not isinstance(template,str):template=DEFAULT_LINES.get(scene,'')
    # Slots can contain paths, formulas or the user's original words; never clean them.
    try:return template.format(**values)
    except (KeyError,ValueError):
        try:return DEFAULT_LINES.get(scene,'').format(**values)
        except (KeyError,ValueError):return DEFAULT_LINES.get(scene,'')

def file_result(result,style=None,limit=6000):
    status=result.get('status','failed')
    key='file_'+status if 'file_'+status in DEFAULT_LINES else 'file_failed'
    output=(result.get('output') or '').strip()
    if status=='completed' and not output:key='file_empty'
    detail=output if status=='completed' else (result.get('error') or result.get('stderr') or output or '').strip()
    text=scene_line(key,style)
    if detail:text+='\n\n'+detail[:limit]+ ('\n完整结果已保留在电脑助手的任务记录中。' if len(detail)>limit else '')
    return LiteralReply(text)

# 主动发言的「方向池」：触发窗口问候/空闲搭话时按 weight 随机挑一个，同一方向不连续用两次。
# 想自己加方向或调权重，把这一段整体挪到 characters/<角色>/dialogue-style.json 的
# "proactive_directions" 里即可（代码会优先用角色包里的）。
PROACTIVE_DIRECTIONS = [
    {'id': 'observe', 'weight': 30, 'label': '具体观察',
     'prompt': '就当前窗口说一句具体的观察或判断（他在做什么、可能卡在哪一步、这软件大概在干什么），'
               '用陈述句，不要提问。'},
    {'id': 'remind', 'weight': 20, 'label': '实用提醒',
     'prompt': '结合当前程序和时间给一条具体、简短的提醒（先存盘、备份、歇一会儿、喝口水、护眼），'
               '只说这一次，不啰嗦、不说教。'},
    {'id': 'tip', 'weight': 15, 'label': '相关小知识',
     'prompt': '围绕当前这个程序给一条确实有用的小技巧或冷知识（快捷键、省事的做法、常见的坑）。'
               '必须是这个程序里确实成立的；拿不准就改成一个具体观察，不要编快捷键或菜单路径。'},
    {'id': 'followup', 'weight': 10, 'label': '承接上文',
     'prompt': '如果最近聊过和当前窗口相关的事，就接着那句说一句；找不到相关话题就改成一个具体观察，不要硬接。'},
    {'id': 'humor', 'weight': 10, 'label': '轻幽默',
     'prompt': '对程序名或窗口标题来一句轻轻的调侃，善意、不阴阳怪气、不冒犯。'},
    {'id': 'ask', 'weight': 10, 'label': '具体提问',
     'prompt': '问一个和当前窗口内容相关、好回答的问题，一句话，别连环问；'
               '必须是凭窗口信息确实不知道答案的事，不要问「你现在开着什么窗口」这种你本来就知道的。'},
    {'id': 'company', 'weight': 5, 'label': '安静陪伴',
     'prompt': '只轻轻表达在旁边陪着，一句话，不提问、不提醒。'},
]

# 结尾的空话尾巴（内容已经在眼前了，再说这些就是噪音）：只在剪贴板反应这类短回复上用。
# 带这些衔接词的尾巴是角色表达（「……算了，我陪你看完」），不剪。
_CHARACTERFUL_TAIL_RE = re.compile(r'^(?:算了|那就|好吧|好，|行，)')
FILLER_TAIL_RE = re.compile(
    r'(?:我陪着你|我陪你(?:一起|一块|一块儿)?(?:重新|再)?(?:弄|做|来|试|看看|等|待)?|'
    r'陪着你(?:就好)?|需要帮忙(?:尽管说|随时说|就说)|'
    r'(?:有(?:什么)?(?:事|需要))?(?:尽管|随时)(?:说|喊我|找我)|'
    r'有事(?:就)?喊我(?:一声)?|喊我一声(?:就)?(?:好|行)?|'
    r'我就在(?:这儿|旁边|这里)|我在呢)[。！？!?…]?$')


def clean_filler_tail(text):
    """去掉结尾的空话尾巴（「…我陪你一块重新弄」「需要帮忙尽管说」）。
    整段都是这类话就返回空串，调用方据此直接不说。
    带「算了/那就/好」这类衔接词的尾巴算角色表达，保留。"""
    text = (text or '').strip()
    if not text:
        return text
    parts = [part for part in re.split(r'(?<=[。！？!?…])|(?<=——)', text) if part.strip()]
    while len(parts) > 1:
        tail = parts[-1].strip().strip('—-、，,。！？!?… ').strip()
        if tail and len(tail) <= 26 and FILLER_TAIL_RE.search(tail) and not _CHARACTERFUL_TAIL_RE.match(tail):
            parts.pop()
        else:
            break
    cleaned = ''.join(parts).strip().rstrip('—-、，, ').strip()
    if (cleaned and len(cleaned) <= 26 and FILLER_TAIL_RE.search(cleaned)
            and not _CHARACTERFUL_TAIL_RE.match(cleaned)):
        return ''
    return cleaned or text
