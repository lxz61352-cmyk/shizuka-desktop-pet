"""Explicit completion replies belong to a delivered reminder, not an arbitrary task.

另外一半：即使没在回某条提醒，用户在聊天里说「已完成 / 已经检查了 / 已经喝了水了」，
本地也要能认出对应待办并标记完成、停掉提醒（`_todo_done_from_chat`）。
"""
import re,threading,time

# 完成类说法：既认「已完成」这种标准回复，也认「已经检查了喵」「已经喝了水了」这类自然话
DONE_WORDS = ('已完成','已经完成','完成了','做完了','已经做完','已做完','做好了','搞定','弄完了','弄好了','搞完了',
              '看完了','读完了','写完了','背完了','复习完了','检查完了','检查过了','检查了','做过了',
              '交完了','交了','买好了','喝过了','喝完了','吃过了','弄过了','处理完了','处理了',
              '喝了','吃了','看了','读了','写了','背了','买了','做了','弄了','搞了')
# 中文会把宾语插在动词和「了」中间（「喝过水了」「看完那本书了」），所以还要认这种带宾语的写法
DONE_VERBS = ('喝','吃','看','读','写','背','检查','交','买','做','弄','搞','处理','复习','整理','提交','打卡','浇','洗','取','联系')
DONE_FORM_RE = re.compile(
    r'(?:' + '|'.join(DONE_VERBS) + r')(?:完|过|好|掉|罢)?了'                              # 喝了 / 喝过了 / 喝完了 / 交了
    r'|(?:' + '|'.join(DONE_VERBS) + r')(?:完|过|好|掉|罢)[^，。！？；、,.!?;\s]{0,6}了'      # 喝过水了 / 看完那本书了
    r'|已完成|已经完成|完成了|搞定|弄好了|弄完了|搞完了|做好了|处理完了')
# 「我要喝水了」「准备去交了」是打算做，不是做完了（允许中间夹几个字，但不跨句读）
WILL_DO_RE = re.compile(
    r'(?:要|去|该|得|准备|打算|马上|这就|回头|一会儿|待会儿)[^，。！？；,.!?;\s]{0,4}'
    r'(?:' + '|'.join(DONE_VERBS) + r')')
# 「确实做完了」的强说法：只有这类才允许「不提名事项也认」（待办只剩一条时）
STRONG_WORDS = ('已完成','已经完成','完成了','做完了','已经做完','已做完','做好了','搞定','弄完了','弄好了','搞完了',
                '看完了','读完了','写完了','背完了','复习完了','检查完了','检查过了','交完了','买好了','喝完了',
                '吃过了','处理完了')
# 否定/还没做/在问：这些不算完成声明（按「动词被否定」判断，别把「特别」「没问题」误伤）
NOT_DONE_RE = re.compile(r'(?:还没|未|没有|没|不)(?:有)?(?:做|弄|搞|看|读|写|背|检查|交|买|喝|吃|完成|处理|提交)'
                         r'|不用|不必|不要|取消|忘了|忘记|回头再|等会儿|要不要|能不能|是不是')
QUESTION_TAIL_RE = re.compile(r'[?？]\s*$')
# 待办标题里的虚词：比对时去掉，「喝水的」和「喝水」算同一件
STOP_CHARS = '的了呢吧啊呀哦噢喵一个来着这那点些再'


def completion_ack(text):
    """只回一个「已完成」这种标准答复（回提醒时用）。"""
    return bool(re.fullmatch(r'(?:已完成|已经完成|完成了|做完了|已经做完了|已做完|完成)[。！!\s]*',text.strip()))


def done_claim(text):
    """这句话是不是在说「这件事我做完了」。不是就返回 None，是就返回原文（去掉首尾空白）。"""
    t = ' '.join((text or '').split())
    if not t or len(t) > 40:
        return None
    if NOT_DONE_RE.search(t) or QUESTION_TAIL_RE.search(t):
        return None
    if WILL_DO_RE.search(t):                 # 「我要喝水了」「准备去交了」是打算做
        return None
    if len(t) <= 10 and re.search(r'(?:吗|么|吧)$', t):   # 「完成了吗」「搞定了吧」是在问，不是在报
        return None
    if not (DONE_FORM_RE.search(t) or any(word in t for word in DONE_WORDS)):
        return None
    return t


def strong_claim(claim):
    """是不是「确实做完了」的说法（而不是「喝了」这种只说了动作）。"""
    return any(word in (claim or '') for word in STRONG_WORDS)


def todo_core(text):
    """待办标题的比对核心：去掉空白和虚词。"""
    return ''.join(ch for ch in (text or '') if ch not in STOP_CHARS and not ch.isspace())


def lcs_len(a, b):
    """最长公共子串长度（中文短句够用）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def subseq_cover(needle, hay):
    """needle 的字符按顺序出现在 hay 里占多少比例（「喝水」对「喝了水」= 1.0）。"""
    if not needle:
        return 0.0
    index = 0
    for ch in hay:
        if index < len(needle) and ch == needle[index]:
            index += 1
    return index / float(len(needle))


def match_score(core, text):
    """待办核心词与用户这句话的匹配分：0 表示对不上。

    完全包含 → 100；有 2 字以上的连续片段 → 片段长度；
    核心词按顺序基本都出现（≥60%）→ 按覆盖长度加分。
    """
    if not core:
        return 0
    if core in text:
        return 100
    best = lcs_len(core, text)
    if best < 2:
        best = 0
    cover = subseq_cover(core, text)
    if cover >= 0.6 and len(core) >= 2:
        best = max(best, int(cover * len(core) * 1.5))
    return best


class TodoReplyMixin:
    def _todo_bind_reply(self,items,channel='desktop'):
        if not hasattr(self,'_todo_reply_targets'):self._todo_reply_targets={}
        self._todo_reply_targets[channel]={'at':time.monotonic(),'items':[
            {'id':r['id'],'title':r['text'],'signature':self._todo_notice_signature(r)} for r in items]}

    # ---------- 聊天里说「我完成了」 → 找到对应待办并标记完成 ----------
    def _todo_done_from_chat(self,text,channel='desktop'):
        """聊天里说「已完成 / 已经检查了 / 已经喝了水了」：标记对应待办完成并停止提醒。

        返回要回的话；返回 None 表示这句不是完成声明（继续按普通聊天处理）。
        本地判断，不调模型；对不上具体事项时先问是哪一件，不乱划。
        """
        claim = done_claim(text)
        if claim is None:
            return None
        pending = [it for it in self.todos if not it.get('done')]
        if not pending:
            return None
        scored = []
        for item in pending:
            title = ' '.join((item.get('text') or '').split())
            # 去虚词的核心词和原样标题都试一遍：用户可能照抄标题，也可能说「喝了水」
            score = max(match_score(todo_core(title), claim), match_score(title, claim))
            if score >= 2:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored:
            top = scored[0][0]
            best = [item for score, item in scored if score == top]
            if len(best) > 1:
                return self._todo_done_ask(best, channel)
            return self._todo_done_apply(best[0])
        # 话里没提是哪件：优先认「刚提醒过的那几条」（用户在回提醒），只有一件待办时也认
        target = self._todo_done_recent(channel)
        if target is not None:
            return self._todo_done_apply(target)
        if len(pending) == 1 and len(claim) <= 14 and strong_claim(claim):
            return self._todo_done_apply(pending[0])
        if len(pending) > 1:
            return self._todo_done_ask(pending, channel)
        return None

    def _todo_done_recent(self,channel='desktop'):
        """最近提醒过、还没完成的待办（用户在回复那条提醒）。"""
        target = getattr(self, '_todo_reply_targets', {}).get(channel)
        if not target or time.monotonic() - target['at'] > 1800:
            return None
        alive = [it for it in self.todos
                 if not it.get('done') and any(spec['id'] == it['id'] for spec in target['items'])]
        return alive[0] if len(alive) == 1 else None

    def _todo_done_apply(self,item):
        try:
            self._todo_complete_or_restore(item, True)   # 连带取消未发出的提醒、刷新列表
        except Exception:
            item['done'] = True
            self._save_todos()
        for channel, target in list(getattr(self, '_todo_reply_targets', {}).items()):
            if any(spec['id'] == item['id'] for spec in target['items']):
                self._todo_reply_targets.pop(channel, None)
        return '好，这条就划掉了：%s' % (item.get('text') or '')

    def _todo_done_ask(self,candidates,channel='desktop'):
        """不确定是哪一件：列出来问一句，并把候选绑上（回「1」或标题都能选）。"""
        self._todo_bind_reply(candidates, channel)
        target = getattr(self, '_todo_reply_targets', {}).get(channel)
        if target:
            target['choosing'] = True
        lines = ['你说的是哪一件？'] + ['%d. %s' % (i, it.get('text') or '')
                                       for i, it in enumerate(candidates, 1)]
        return '\n'.join(lines)

    def _weixin_todo_done(self,text,cancel):
        """微信那条路：待办在主线程，交回主线程判断。"""
        ready=threading.Event();result=[]
        def apply():
            try:
                result.append(None if cancel.is_set() else self._todo_done_from_chat(text,'weixin'))
            finally:
                ready.set()
        self._ui(apply)
        if not ready.wait(8):
            return None
        return result[0]

    def _todo_complete_reply(self,text,channel='desktop'):
        target=getattr(self,'_todo_reply_targets',{}).get(channel)
        if not target:return None
        if time.monotonic()-target['at']>1800:
            self._todo_reply_targets.pop(channel,None);return None
        specs=target['items']
        if not completion_ack(text):
            if target.get('choosing'):
                choices=[s for i,s in enumerate(specs,1) if text.strip() in (s['title'],str(i))]
                if len(choices)!=1:
                    self._todo_reply_targets.pop(channel,None);return None
                specs=choices
            else:
                self._todo_reply_targets.pop(channel,None);return None
        if target.get('handled'):return '这次已经记为完成了。'
        if len(specs)!=1:
            target['choosing']=True
            return '您刚完成的是哪一件？\n'+'\n'.join(f"{i}. {s['title']}" for i,s in enumerate(specs,1))
        spec=specs[0];row=next((r for r in self.todos if r['id']==spec['id']),None)
        if row is None:
            target['handled']=True;return '这条待办已经不在列表里了。'
        if row.get('done'):target['handled']=True;return row['text']+'已经标记完成了。'
        if self._todo_notice_signature(row)!=spec['signature']:
            target['handled']=True
            return '这条提醒的时间已经变了，请在待办里核对一下要完成哪一次。'
        rule=self._todo_options(row).get('schedule',{}).get('rule')
        try:self._todo_complete_or_restore(row,True)
        except Exception:return '完成状态这次没有确认保存，您先在待办里核对一下。'
        target['handled']=True
        return (row['text']+'这次完成了，下次再提醒您。') if rule and not rule.get('until_done') else (row['text']+'完成了，我记好了。')

    def _weixin_complete_reply(self,text,cancel):
        target=getattr(self,'_todo_reply_targets',{}).get('weixin')
        if not target:return None
        if not completion_ack(text) and not target.get('choosing'):
            self._todo_reply_targets.pop('weixin',None);return None
        ready=threading.Event();result=[]
        def apply():
            try:
                result.append(None if cancel.is_set() else self._todo_complete_reply(text,'weixin'))
            finally:
                ready.set()
        self._ui(apply)
        if not ready.wait(8):
            cancel.set();return '完成状态还没确认，您先在电脑待办里核对一下。'
        return result[0]
