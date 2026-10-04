"""Behavioral regressions from the private audit, using synthetic records only."""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from memory_review_policy import claim_issue, accepted_facts, known_for_batch, reviewed_ids
from memory_maintenance import pending_rows

class ReviewPolicyTests(unittest.TestCase):
    def test_more_than_800_rows_are_reviewed_once(self):
        rows=[dict(id=str(i),role='user' if i%2==0 else 'assistant',text='消息',kind='chat',created=i+1) for i in range(1200)]
        processed=[];visited=[]
        for _ in range(80):
            batch=pending_rows(rows,processed)
            if not batch:break
            visited.extend(r['id'] for r in batch)
            processed=reviewed_ids(processed,batch)
        self.assertEqual(len(visited),1200)
        self.assertEqual(len(set(visited)),1200)
        self.assertEqual(pending_rows(rows,processed),[])
        self.assertEqual(reviewed_ids(processed,rows[:2]),processed)

    def test_do_not_infer_dog_ownership(self):
        self.assertEqual(claim_issue('用户养狗','我帮姐姐遛狗'),'ownership_inferred')
        self.assertIsNone(claim_issue('用户养狗','我养了一只狗'))

    def test_relative_time_and_conditions(self):
        self.assertEqual(claim_issue('用户还有90天考试','还有90天考试'),'relative_countdown')
        self.assertEqual(claim_issue('用户想转专业','如果考得上，我想转专业'),'qualifier_lost')
        self.assertIsNone(claim_issue('用户如果考得上想转专业','如果考得上，我想转专业'))

    def test_challenging_evidence_does_not_deny_the_claim(self):
        self.assertEqual(claim_issue('用户否认住在北京','这你猜的吧，我没告诉过你住哪'),'denial_inferred')
        self.assertIsNone(claim_issue('用户否认住在北京','我不住北京，没告诉过你吗'))

    def test_ordinary_repeated_fact_not_readded_or_refreshed(self):
        old=[dict(id='m',content='用户喜欢无糖咖啡',source_quote='咖啡我只喝无糖的',status='archived',source_time=1)]
        f=dict(content='用户喝咖啡只喝无糖的',quote='咖啡我只喝无糖的',source_id='new',replaces=[])
        self.assertEqual(accepted_facts([f],old),[])
        self.assertEqual(old[0]['source_time'],1)

    def test_replacement_ids_must_have_been_presented(self):
        f=dict(content='用户换到乙城市工作',quote='我换到乙城市工作了',source_id='new',replaces=['old','imaginary'])
        self.assertEqual(accepted_facts([f],[],['old'])[0]['replaces'],['old'])

    def test_known_memories_past_40_and_archived_still_visible(self):
        items=[dict(id=str(i),content='用户的长期项目'+str(i),created=i) for i in range(70)]
        items[60].update(content='用户喜欢无糖咖啡',status='archived')
        known=known_for_batch(items,[dict(id='q',role='user',text='我喜欢无糖咖啡')])
        self.assertEqual(len(known),70)
        self.assertEqual(known[0]['id'],'60')

    def test_distinct_preferences_not_merged(self):
        facts=[dict(content='用户喜欢'+x,quote='我喜欢'+x,source_id=x,replaces=[]) for x in ('猫','狗')]
        self.assertEqual(len(accepted_facts(facts,[])),2)

if __name__=='__main__':unittest.main()
