"""Shared plain-text presentation and character-owned service wording."""
from pathlib import Path
import json,re

PLAIN_STYLE=('用自然段表达，篇幅服从问题需要。日常话语简短，科研分析和深入讨论可以充分展开。'
             '不用 Markdown 标题、粗体星号、分割线或装饰性符号来包装普通回复。'
             '必要时可以分点、列步骤，保留公式、代码、数值、单位、文件路径和来源链接的准确性。'
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
    except (KeyError,ValueError):return DEFAULT_LINES.get(scene,'').format(**values)

def file_result(result,style=None,limit=6000):
    status=result.get('status','failed')
    key='file_'+status if 'file_'+status in DEFAULT_LINES else 'file_failed'
    output=(result.get('output') or '').strip()
    if status=='completed' and not output:key='file_empty'
    detail=output if status=='completed' else (result.get('error') or result.get('stderr') or output or '').strip()
    text=scene_line(key,style)
    if detail:text+='\n\n'+detail[:limit]+ ('\n完整结果已保留在电脑助手的任务记录中。' if len(detail)>limit else '')
    return LiteralReply(text)
