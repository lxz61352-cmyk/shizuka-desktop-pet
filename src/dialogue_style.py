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
             '不要用“X啊……”“X呢……”这种拖长音的公式化开头，也不要句句以“啊/呀/呢/哦/啦”收尾，'
             '语气词能省就省，别每句都一样。'
             '不要在回复里复述“[历史消息时间：…]”“[图片]（…）”这类元信息或括号标注，直接说内容。'
             '历史对话与摘要只用来理解上下文：不要照抄或复述其中任何句子，尤其不要重复你自己当时说过的话。'
             '用户这句话如果确实看不懂（乱码、误触、无意义），就直接说不明白、请他重说，不要硬接，也不要拿历史内容顶上。')

class LiteralReply(str):
    """Application wording with exact user-supplied slots, already ready to display."""

# 起手语气词 / 「(你)又在/还在」公式化开头 / 第一小句结尾的拖长音语气词——确定性去掉，
# 光靠提示词压不住（模型爱用「哦，……」起手，或把普通的事说成「又在……」）。
_LEAD_PAREN_RE=re.compile(r'^(?:\s*[（(][^（）()\n]{1,40}[）)])+\s*')
_ACK_LEAD_RE=re.compile(r'^\s*(?:哦|噢|喔|嗯|呃|诶|欸|唉|哎|呵呵|哦哦|嗯嗯)(?![呀哟呦豁哈嘿哼嘛])\s*[，,、：:]?\s*')
_FORMULA_LEAD_RE=re.compile(r'^\s*(?:你)?\s*(?:又|还)在\s*')
_TAIL_PARTICLE_RE=re.compile(r'^(.{1,30}?)([啊呀哦噢])(?=[。！？!?…，,、；;\n])')
# 上下文里给模型看的时间元信息，模型有时会原样复述出来 → 一律去掉
_DATE_MARK_RE=re.compile(r'\[历史消息时间[^\]]{0,160}\]')

# 起手语气词与「(你)又在/还在」公式化开头的正则只在这一处定义：
# pet.clean_reply_style 复用这两个名字，避免两套规则对同一句话给出不同结果。
ACK_LEAD_RE=_ACK_LEAD_RE
FORMULA_LEAD_RE=_FORMULA_LEAD_RE


def _trim_leads(text):
    out=_DATE_MARK_RE.sub('',text)               # 「[历史消息时间：…；相对日期以此为准]」
    out=_LEAD_PAREN_RE.sub('',out,count=1)       # 开头的「（叹气）」这类舞台提示
    out=_ACK_LEAD_RE.sub('',out,count=1)         # 起手语气词
    out=_FORMULA_LEAD_RE.sub('',out,count=1)     # 紧跟其后的「(你)又在/还在」
    m=_TAIL_PARTICLE_RE.match(out)               # 第一小句结尾的拖长音语气词
    if m:out=m.group(1)+out[m.end():]
    return out.lstrip()


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
    return _trim_leads(re.sub(r'\n{3,}','\n\n',''.join(chunks)).lstrip())

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
FILLER_TAIL_RE = re.compile(
    r'(?:我陪着你|我陪你(?:一起|一块|一块儿)?(?:重新|再)?(?:弄|做|来|试|看看|等|待)?|'
    r'陪着你(?:就好)?|需要帮忙(?:尽管说|随时说|就说)|'
    r'(?:有(?:什么)?(?:事|需要))?(?:尽管|随时)(?:说|喊我|找我)|'
    r'有事(?:就)?喊我(?:一声)?|喊我一声(?:就)?(?:好|行)?|'
    r'我就在(?:这儿|旁边|这里)|我在呢)[。！？!?…]?$')


def clean_filler_tail(text):
    """去掉结尾的空话尾巴（「…我陪你一块重新弄」「需要帮忙尽管说」）。
    整段都是这类话就返回空串，调用方据此直接不说。"""
    text = (text or '').strip()
    if not text:
        return text
    parts = [part for part in re.split(r'(?<=[。！？!?…])|(?<=——)', text) if part.strip()]
    while len(parts) > 1:
        tail = parts[-1].strip().strip('—-、，,。！？!?… ').strip()
        if tail and len(tail) <= 26 and FILLER_TAIL_RE.search(tail):
            parts.pop()
        else:
            break
    cleaned = ''.join(parts).strip().rstrip('—-、，, ').strip()
    if cleaned and len(cleaned) <= 26 and FILLER_TAIL_RE.search(cleaned):
        return ''
    return cleaned or text
