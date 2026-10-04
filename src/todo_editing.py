"""Shared todo editor service; neither Qt nor Tk owns reminder persistence."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib,json,time
from todo_model import CATEGORIES
from todo_schedule import occurrence,rule_label

REPEATS=('不重复','每天','每周','每月','工作日','每天直到完成')
MODES=('未安排时间','指定时间','下次启动')

def repeat_label(rule):
    return ('不重复' if not rule else '每天直到完成' if rule.get('until_done') else
            '工作日' if rule.get('weekdays')==list(range(5)) else
            {'daily':'每天','weekly':'每周','monthly':'每月'}[rule['frequency']])

def edit_token(item,options):
    value=[item,{k:options.get(k) for k in ('category','manual_note','desktop','weixin','schedule')}]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def editor_values(item,options,now=None):
    schedule=options.get('schedule',{});rule=schedule.get('rule')
    event=schedule.get('event_at') or (item or {}).get('due')
    dt=datetime.fromtimestamp(event) if event else datetime.fromtimestamp(time.time() if now is None else now)+timedelta(hours=1)
    return dict(title=(item or {}).get('text',''),note=options.get('manual_note',''),
        category=options.get('category','生活'),repeat=repeat_label(rule),
        mode='下次启动' if item and item.get('on_boot') else '指定时间' if item and item.get('due') else '未安排时间',
        date=dt.strftime('%Y-%m-%d'),hour=dt.strftime('%H'),minute=dt.strftime('%M'),
        lead=str(schedule.get('lead_minutes',0)),interval=str((rule or {}).get('interval',1)),
        desktop=options.get('desktop',True),weixin=options.get('weixin',True))

def save_editor(app,values,ident='',initial=None,now=None):
    """Reuse original editor rules, including note-only edits of past schedules."""
    app._todo_init();now=time.time() if now is None else now
    item=next((row for row in app.todos if row['id']==ident),None) if ident else None
    if ident and item is None:raise ValueError('这件事已被删除')
    title=values.get('title','');note=values.get('note','')
    if not isinstance(title,str) or not isinstance(note,str):raise ValueError('标题和备注必须是文字')
    title=title.strip();note=note.strip()
    if not title or len(title)>1000 or len(note)>4000:raise ValueError('请填写标题；标题最多1000字，备注最多4000字。')
    group=values.get('category');repeat=values.get('repeat');mode=values.get('mode')
    if group not in CATEGORIES or repeat not in REPEATS or mode not in MODES:raise ValueError('用途、重复或时间模式无效')
    if any(type(values.get(k)) is not bool for k in ('desktop','weixin')):raise ValueError('请选择提醒方式')
    options=deepcopy(app._todo_options(item)) if item else {}
    schedule=options.get('schedule',{});rule=schedule.get('rule')
    initial=initial or editor_values(item,options,now)
    initial_time=tuple(str(initial[k]) for k in ('date','hour','minute'))
    current_time=tuple(str(values[k]) for k in ('date','hour','minute'))
    initial_event=schedule.get('event_at') or (item or {}).get('due')
    due=event=new_rule=None;boot=mode=='下次启动'
    advance=int(values['lead']) if mode=='指定时间' else 0
    if not 0<=advance<=43200:raise ValueError('提前量应在0至43200分钟之间')
    if mode=='指定时间':
        event=datetime.strptime(f"{values['date']} {int(values['hour']):02d}:{int(values['minute']):02d}",'%Y-%m-%d %H:%M')
        if item and initial_event and initial_time==current_time:event=datetime.fromtimestamp(initial_event)
        if repeat!='不重复':
            every=int(values['interval']) if repeat in ('每天','每周','每月') else 1
            if not 1<=every<=366:raise ValueError('周期间隔应在1至366之间')
            new_rule=dict(frequency={'每天':'daily','每周':'weekly','每月':'monthly','工作日':'weekly','每天直到完成':'daily'}[repeat],
                interval=every,weekdays=list(range(5)) if repeat=='工作日' else [event.weekday()],
                month_day=event.day,hour=event.hour,minute=event.minute,anchor_date=event.date().isoformat(),until_done=repeat=='每天直到完成')
            if rule and repeat==repeat_label(rule) and initial_time==current_time:new_rule={**deepcopy(rule),'interval':every}
        due=event.timestamp()-advance*60
        unchanged=item and initial_event==event.timestamp() and advance==schedule.get('lead_minutes',0)
        if event.timestamp()<=now and not unchanged:
            if new_rule:
                event=occurrence(new_rule,datetime.fromtimestamp(now+advance*60));due=event.timestamp()-advance*60
            else:raise ValueError('请选择未来的事项时间')
        if not unchanged:due=max(now,due)
        elif item:due=item.get('due')
    elif repeat!='不重复':raise ValueError('周期事项需要指定时间')
    new_schedule=dict(version=1,event_at=event.timestamp() if event else None,lead_minutes=advance,
                      lead_reason='editor',rule=new_rule,reminder_at=due)
    if item:
        record=item;old_options=deepcopy(options);old_title=record['text']
        rescheduled=(record.get('due'),record.get('on_boot'),old_options.get('schedule',{}).get('rule'))!=(due,boot,new_rule)
        record.update(text=title,due=due,on_boot=boot);app._save_todos()
    else:
        record=app.add_todo(title,due_ts=due,on_boot=boot);rescheduled=True;old_options={};old_title=''
    opts=app._todo_options(record)
    if old_options.get('schedule',{}).get('rule') and not new_rule:app._todo_queue_routine(record,'停止重复')
    opts.update(category=group,manual_note=note,desktop=values['desktop'],weixin=values['weixin'],time_hint='')
    app._todo_install_schedule(record,opts,new_schedule)
    if rescheduled or old_title!=title or old_options.get('manual_note','')!=note:
        opts['source_text']=title+('；'+note if note else '')+('；'+rule_label(new_rule) if new_rule else '')
        opts['source_id']='editor-'+record['id']+'-'+str(int(now*1000))
        app._todo_queue_routine(record,'调整' if item else '建立')
    if rescheduled:opts.pop('notice',None)
    app._save_todo_details();app._refresh_todo_view();app._todo_start_memory_review()
    app._activity_saved_until=time.monotonic()+3
    return record
