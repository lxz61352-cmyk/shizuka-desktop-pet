"""Explicit completion replies belong to a delivered reminder, not an arbitrary task."""
import re,threading,time

def completion_ack(text):
    return bool(re.fullmatch(r'(?:已完成|已经完成|完成了|做完了|已经做完了|已做完|完成)[。！!\s]*',text.strip()))

class TodoReplyMixin:
    def _todo_bind_reply(self,items,channel='desktop'):
        if not hasattr(self,'_todo_reply_targets'):self._todo_reply_targets={}
        self._todo_reply_targets[channel]={'at':time.monotonic(),'items':[
            {'id':r['id'],'title':r['text'],'signature':self._todo_notice_signature(r)} for r in items]}

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
            finally:ready.set()
        self._ui(apply)
        if not ready.wait(8):
            cancel.set();return '完成状态还没确认，您先在电脑待办里核对一下。'
        return result[0]
