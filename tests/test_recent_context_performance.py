"""Compatibility against the pre-optimization context selector."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import random
import sys
import tracemalloc
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import conversation_memory as cm
from conversation_memory import CHAT_KINDS, SUMMARY_KIND, RECENT_MESSAGE_LIMIT, RECENT_CHARACTER_BUDGET, recent_turns

def reference_messages(rows, limit=RECENT_MESSAGE_LIMIT, budget=RECENT_CHARACTER_BUDGET, dated=False,current_user_id=None,time_precision='minutes'):
    """All real user/assistant dialogue, including assistant-led exchanges, in order.

    Proactive text is context only: eligible()/summary_batch() retain their existing
    user-grounded memory rules. Only the caller's current user message is excluded
    because it is appended once at the end of that request; source markers and
    memory summaries are not spoken messages.
    """
    if limit<=0:return []
    turns=recent_turns(rows,len(rows))
    completed={ident for turn in turns for ident in turn['ids']}
    partners={ident:turn['ids'][0] for turn in turns for ident in turn['ids'][1:]}
    candidates=[];source=''
    for row in rows:
        if row.get('role')=='source':
            source=row.get('text','').removeprefix('内容来自');continue
        standalone=row.get('role')=='assistant' and row.get('kind')!=SUMMARY_KIND
        proactive=standalone and (row.get('kind') not in CHAT_KINDS or row.get('id') not in completed)
        spoken=row.get('role') in ('user','assistant') and row.get('kind')!=SUMMARY_KIND
        if spoken and (current_user_id is None or row.get('id')!=current_user_id):
            value=row.get('text','')
            if not value.strip():continue
            if len(value)>8000:value=value[:6000]+'\n[中段省略，完整原文仍在记录中]\n'+value[-1800:]
            if dated:
                when=row.get('created')
                label=datetime.fromtimestamp(when,timezone.utc).astimezone().isoformat(timespec=time_precision) if when else '原时间未知'
                origin_source='微信' if row.get('kind','').startswith('weixin') else source
                origin=('；此前主动消息'+('，来源：'+origin_source if origin_source else '')) if proactive else ''
                value='[历史消息时间：'+label+'；相对日期以此为准'+origin+']\n'+value
            candidates.append((row,{'role':row['role'],'content':value}))
        if row.get('role')=='assistant':source=''
    selected=[];size=0
    for row,message in reversed(candidates):
        if len(selected)>=limit or selected and size+len(message['content'])>budget:break
        selected.insert(0,(row,message));size+=len(message['content'])
    # A budget boundary may keep an assistant answer but lose its paired user turn.
    ids={row.get('id') for row,_ in selected}
    return [message for row,message in selected if row.get('id') not in partners or partners[row['id']] in ids]


class RecentContextTests(unittest.TestCase):
    def test_mixed_archives_match_reference_without_mutation(self):
        rng=random.Random(715)
        for case in range(100):
            rows=[]
            for i in range(rng.randrange(20,200)):
                row=dict(id=str(i),role=rng.choice(['user','assistant','source']),
                         kind=rng.choice(['chat','weixin','weixin_proactive','memory_summary','greeting']),
                         text=rng.choice(['hello','内容来自天气',' ','long '*2000,'短回复']),
                         created=1700000000+rng.randrange(1000))
                if rng.random()<.5:row['turn_id']='wxreply:'+str(rng.randrange(3))
                if rng.random()<.1:row.pop('kind')
                rows.append(row)
            original=deepcopy(rows)
            options=dict(limit=rng.choice([0,1,2,10,100]),budget=rng.choice([0,80,1000,48000]),
                         dated=bool(case%2),current_user_id=rng.choice([None,str(len(rows)-1)]),
                         time_precision=rng.choice(['minutes','seconds']))
            with self.subTest(case=case,options=options):
                self.assertEqual(cm.recent_messages(rows,**options),reference_messages(rows,**options))
                self.assertEqual(rows,original)

    def test_user_outside_tail_and_segmented_weixin_reply(self):
        rows=[dict(id='u',role='user',kind='weixin',text='question')]
        rows += [dict(id=str(i),role='assistant',kind='weixin',text='segment',turn_id='wxreply:one')
                 for i in range(200)]
        for limit in (1,100,201):
            self.assertEqual(cm.recent_messages(rows,limit=limit,dated=True),
                             reference_messages(rows,limit=limit,dated=True))
        self.assertEqual(cm.recent_messages(rows,limit=100),[])

    def test_source_outside_tail_retains_proactive_label(self):
        rows=[dict(id='s',role='source',text='内容来自天气')]
        rows += [dict(id=str(i),role='user',text='old',kind='greeting') for i in range(200)]
        rows.append(dict(id='a',role='assistant',text='forecast',kind='weather'))
        result=cm.recent_messages(rows,limit=1,dated=True)
        self.assertEqual(result,reference_messages(rows,limit=1,dated=True))
        self.assertIn('来源：天气',result[0]['content'])

    def test_long_archive_formats_only_tail_with_bounded_temporary_memory(self):
        rows=[dict(id=str(i),role='user' if i%2==0 else 'assistant',kind='chat',
                   text='fixture',created=1700000000+i) for i in range(20000)]
        tracemalloc.start()
        try:
            result=cm.recent_messages(rows,dated=True)
            peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertEqual(len(result),100)
        self.assertLess(peak,1024*1024)
        with patch.object(cm,'datetime',wraps=datetime) as dates:
            cm.recent_messages(rows,dated=True)
        self.assertLessEqual(dates.fromtimestamp.call_count,101)


if __name__=='__main__':unittest.main()
