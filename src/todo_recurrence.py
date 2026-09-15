"""Durable occurrence transitions and source-linked long-term routine records."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib,json,time
from sync_bridge import atomic_json
from todo_schedule import next_schedule,latest_due_schedule,rule_label,schedule_facts

class TodoRecurrenceMixin:
    def _todo_install_schedule(self,item,options,schedule):
        options['schedule']=deepcopy(schedule)
        options['schedule']['reminder_at']=item.get('due')

    def _todo_prepare_occurrence(self,item,now):
        options=self._todo_options(item);schedule=options.get('schedule',{});rule=schedule.get('rule')
        if not rule or not item.get('due') or item['id'] in self._todo_sending:return
        # Respect an explicit time edit arriving through the old portable core schema.
        if schedule.get('reminder_at') is not None and item['due']!=schedule['reminder_at']:
            event=datetime.fromtimestamp(item['due']+schedule.get('lead_minutes',0)*60)
            schedule.update(event_at=event.timestamp(),reminder_at=item['due'])
            rule.update(hour=event.hour,minute=event.minute,anchor_date=event.date().isoformat())
            if rule['frequency']=='weekly':rule['weekdays']=[event.weekday()]
            if rule['frequency']=='monthly':rule['month_day']=event.day
            options.pop('notice',None);self._todo_queue_routine(item,'调整');self._save_todo_details()
        latest,due=latest_due_schedule(schedule,now)
        if due is not None and due>item['due']:
            self._todo_transition(item,latest,due,'到达下一周期',now)

    def _todo_transition(self,item,schedule,due,reason,now):
        options=self._todo_options(item);before_item=deepcopy(item);before_options=deepcopy(options)
        # Last state per occurrence is retained, including uncertain Weixin delivery.
        options.setdefault('occurrences',[]).append({'due':item.get('due'),'event_at':options.get('schedule',{}).get('event_at'),
            'notice':deepcopy(options.get('notice',{})),'closed_at':now,'reason':reason})
        item.update(due=due,on_boot=False,done=False)
        self._todo_install_schedule(item,options,schedule);options.pop('notice',None)
        try:self._save_todos();self._save_todo_details()
        except Exception:
            item.clear();item.update(before_item);options.clear();options.update(before_options);raise

    def _todo_complete_or_restore(self,item,done):
        options=self._todo_options(item);schedule=options.get('schedule',{});rule=schedule.get('rule');now=time.time()
        if done and rule and not rule.get('until_done'):
            updated,due=next_schedule(schedule,max(now,item.get('due') or now))
            self._todo_transition(item,updated,due,'完成本次',now)
        else:
            item['done']=done
            if not done and rule:
                updated,due=next_schedule(schedule,now)
                self._todo_install_schedule(item,options,updated);item['due']=due;options['schedule']['reminder_at']=due;options.pop('notice',None)
            self._save_todos();self._todo_queue_routine(item,'结束' if done else '恢复');self._save_todo_details()
        if done:self._todo_cancel_notices(item['id'])
        self._refresh_todo_view();self._todo_start_memory_review()

    def _todo_end_series(self,tid):
        item=next((it for it in self.todos if it['id']==tid),None)
        if not item:return
        item['done']=True;self._save_todos();self._todo_queue_routine(item,'结束');self._save_todo_details()
        self._refresh_todo_view();self._todo_start_memory_review()

    def _todo_queue_routine(self,item,action):
        options=self._todo_options(item);rule=options.get('schedule',{}).get('rule')
        if not rule or rule.get('until_done'):return
        source=options.get('source_text') or item['text']
        content=(f"用户于{datetime.now().strftime('%Y-%m-%d %H:%M')}通过待办{action}周期安排“{item['text']}”："
                 f"{rule_label(rule)}。原始依据：{source}。记录是该次操作的历史，当前是否继续以待办状态为准。")
        queue=options.setdefault('routine_memory',[])
        signature=hashlib.sha256(json.dumps([item['id'],action,rule,source,item.get('done')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if queue and queue[-1].get('signature')==signature:return
        identity=hashlib.sha256((signature+':'+str(len(queue))).encode()).hexdigest()
        queue.append({'id':identity,'signature':signature,'content':content,'source_id':options.get('source_id') or item['id'],'saved':False})

    def _todo_start_memory_review(self):
        callback=getattr(self,'_maybe_review_memory',None)
        if callback and any(not row.get('saved') for options in self._todo_details.values() for row in options.get('routine_memory',[])):callback(timed=True)

    def _collect_routine_memories(self):
        """Called under the memory worker lock; no model needed for explicit routine facts."""
        import pet as engine
        self._todo_init();memory=engine.get_memory();pending=[]
        for tid,options in list(self._todo_details.items()):
            for request in deepcopy(options.get('routine_memory',[])):
                if not request.get('saved'):pending.append((tid,request))
        if not pending:return
        for _,request in pending:memory.add(request['content'])
        memory.save()
        records={row['content']:row['id'] for row in memory.snapshot()}
        def finish():
            for tid,request in pending:
                for row in self._todo_details.get(tid,{}).get('routine_memory',[]):
                    if row['id']==request['id'] and request['content'] in records:
                        row.update(saved=True,memory_id=records[request['content']],saved_at=time.time())
            self._save_todo_details()
        self._ui(finish)

    def _todo_routine_context(self):
        self._todo_init();rows=[]
        for item in self.todos:
            options=self._todo_options(item)
            if options.get('schedule',{}).get('rule'):
                rows.append({'title':item['text'],'active':not item.get('done'),'schedule':schedule_facts(item,options),
                             'source':options.get('source_text',item['text'])})
        return ('当前周期待办状态（历史记忆中的创建记录不代表现在仍有效）：'+json.dumps(rows,ensure_ascii=False)) if rows else ''

    def _todo_apply_pending_upgrade(self):
        """Apply a user-requested existing-item correction once, only if its old values still match."""
        path=self._todo_details_path.with_name('todo-upgrades.json')
        if not path.exists():return
        data=json.loads(path.read_text('utf-8'))
        for change in data.get('changes',[]):
            if change.get('status'):continue
            item=next((it for it in self.todos if it['id']==change['id']),None)
            prior_options=self._todo_options(item) if item else {}
            if item and all(item.get(k)==v for k,v in change['expected'].items()) and all(prior_options.get(k)==v for k,v in change.get('expected_options',{}).items()):
                options=self._todo_options(item);options.update(change['options']);item.update(change['core'])
                self._save_todos();self._save_todo_details();change['status']='applied'
            else:change['status']='skipped_changed_record'
        atomic_json(path,data)
