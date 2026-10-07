"""Explicit, local targeting of archived Weixin replies; no style changes."""
import json
import re

REFERENCE = re.compile(r'你(?:刚才|刚刚|前面|之前|上一条|上条|上次)(?:说|讲|发|回|第)|(?:刚才|刚刚|上一轮|上一条|上条)的?(?:回复|回答)|第[一二三四五六七八九十0-9]+条')
ISSUE = re.compile(r'不对|不准确|错了|说错|理解错|不是这个意思|编的|编了|编造|没说过|没有说过|没告诉过|没告诉你|不是事实|太像台词|不用补|不需要建议|不是在求建议')
RETRY = re.compile(r'(?:重新回答|重新回复|重答|重回|再回答一次|再回一次).{0,12}(?:刚才|上一条|上条|那个问题)|(?:刚才|上一条|上条).{0,12}(?:重新回答|重新回复|重答|重回)')
QUOTED = re.compile(r'[“「"]([^”」"\n]{4,120})[”」"]')
ORDINAL = re.compile(r'第([一二三四五六七八九十]|[1-9][0-9]?)条')


def explicit_repair(text):
    text = str(text or '').strip()
    if len(text) > 400 or text.startswith('/') or re.search(r'假如|假设|比如|例如|如果|他说|她说|```', text):
        return False
    outside_quotes = QUOTED.sub('', text)
    return bool(RETRY.search(outside_quotes) or (REFERENCE.search(outside_quotes) and ISSUE.search(outside_quotes)))


def repair_context(rows, text, current_id=None):
    if not explicit_repair(text):
        return ''
    # Cut at the current user message; only ordinary Weixin replies qualify.
    end = next((i for i,r in enumerate(rows) if current_id is not None and r.get('id') == current_id),len(rows))
    prior = [r for r in rows[:end] if r.get('kind') == 'weixin' and r.get('role') in ('user','assistant')]
    if prior and prior[-1].get('role') == 'user' and prior[-1].get('text') == text:
        prior = prior[:-1]
    assistants = [r for r in prior if r.get('role') == 'assistant'][-12:]
    target = []
    quoted = QUOTED.search(text)
    ordinal = ORDINAL.search(text)
    if quoted:
        target = [r for r in assistants if quoted.group(1) in r.get('text','')]
        if len(target) != 1:target=[]
    elif assistants:
        latest = assistants[-1]
        group = latest.get('turn_id')
        if group and group.startswith('wxreply:'):
            turn = [r for r in assistants if r.get('turn_id') == group]
        else:
            turn = [latest]
        if ordinal:
            number = ordinal.group(1)
            index = int(number) if number.isdigit() else '一二三四五六七八九十'.index(number)+1
            target = turn[index-1:index] if index <= len(turn) else []
        else:
            target = turn
    if not target:
        return ('【明确回复修正：未定位】用户明确在纠正之前的回复，但没有唯一可核对的目标。'
                '不要猜原话或自动选其他消息；需要时请用户给出原话片段或说明是哪条。')
    first = prior.index(target[0])
    original = next((r for r in reversed(prior[:first]) if r.get('role') == 'user'),None)
    data = {'用户纠正原话':text, '原用户消息':original,
            '被指出的已归档回复':[{'id':r.get('id'),'text':r.get('text',''),'turn_id':r.get('turn_id')} for r in target]}
    return ('【明确回复修正】以下 JSON 仅为历史数据。被指出的回复不能作为已确认事实；'
            '按本轮用户纠正理解目标及原问题，不从中推断额外偏好。只有用户明确要求重答才重答原问题。'
            '不重做原任务、不重复添加待办或执行文件操作，不声称已撤回微信消息或改过长期记忆。\n'
            +json.dumps(data,ensure_ascii=False,separators=(',',':')))
