import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from pet_triggers import ActionTriggers


class TriggersTest(unittest.TestCase):
    def test_held_head_stroke_needs_only_a_short_sweep(self):
        t=ActionTriggers(0)
        self.assertFalse(t.stroke(.4,0,True,pressed=True))
        self.assertFalse(t.stroke(.403,.1,True,pressed=True))
        self.assertTrue(t.stroke(.47,.2,True,pressed=True))
        self.assertFalse(t.stroke(.55,.3,False,pressed=True))
        self.assertFalse(t.stroke(.4,1,True,pressed=True))
        self.assertFalse(t.stroke(.47,2,True,pressed=True))

    def test_head_strokes_need_reversals_and_reject_jitter_or_gaps(self):
        t=ActionTriggers(0)
        for i,x in enumerate((.4,.401,.399,.401,.4)):
            self.assertFalse(t.stroke(x,i*.1,True))
        t.clear_stroke()
        for i,x in enumerate((.4,.47,.54,.61)):
            self.assertFalse(t.stroke(x,1+i*.1,True))
        t.clear_stroke()
        result=[t.stroke(x,2+i*.15,True) for i,x in enumerate((.4,.48,.4,.48))]
        self.assertEqual(result,[False,False,False,True])
        self.assertFalse(t.stroke(.4,3,False))
        self.assertFalse(t.stroke(.48,4,True))
        self.assertFalse(t.stroke(.4,5,True))
        self.assertFalse(t.stroke(.48,6,True))

    def test_cooldowns_block_repetition_and_busy_does_not_consume_trigger(self):
        t=ActionTriggers(0)
        self.assertFalse(t.allow("pat",0,blocked=True))
        self.assertFalse(t.allow("pat",0,active=True))
        self.assertTrue(t.allow("pat",0))
        self.assertFalse(t.allow("pat",7.9))
        self.assertTrue(t.allow("pat",8))
        self.assertFalse(t.allow("sleep",9))
        self.assertTrue(t.allow("sleep",11))
        self.assertFalse(t.allow("sleep",310))
        self.assertTrue(t.allow("sleep",311))
        self.assertTrue(t.allow("happy",315))
        self.assertFalse(t.allow("happy",374))
        self.assertTrue(t.allow("happy",375))
        self.assertFalse(t.allow("happy",376,manual=True))
        self.assertTrue(t.allow("happy",377,manual=True))

    def test_sleep_needs_local_and_system_idle_and_disabled_clears_pending(self):
        t=ActionTriggers(0)
        for idle in (None,0,59):
            self.assertIsNone(t.candidate(61,idle))
        self.assertIsNone(t.candidate(59,61))
        self.assertEqual(t.candidate(60,60),"sleep")
        t.interact(181)
        self.assertIsNone(t.candidate(200,200))
        self.assertIsNone(t.candidate(400,400,blocked=True))
        self.assertIsNone(t.candidate(401,401))
        self.assertEqual(t.candidate(580,580),"sleep")
        t.hide(600);t.restore(631)
        self.assertIsNone(t.candidate(632,0,enabled=False))
        self.assertIsNone(t.candidate(633,0))

    def test_deliberate_gestures_have_their_own_cooldowns(self):
        t=ActionTriggers(0)
        self.assertTrue(t.allow("happy",0,gesture=True))
        self.assertEqual(t.source,"gesture")
        self.assertFalse(t.allow("happy",4.9,gesture=True))
        self.assertTrue(t.allow("happy",5,gesture=True))
        self.assertFalse(t.allow("happy",64))
        self.assertTrue(t.allow("happy",65))
        self.assertTrue(t.allow("pat",70,gesture=True))
        self.assertFalse(t.allow("pat",77,gesture=True))
        self.assertTrue(t.allow("pat",78,gesture=True))

    def test_restore_only_once_after_long_hide_and_pending_expires(self):
        t=ActionTriggers(0)
        t.restore(10)
        self.assertIsNone(t.candidate(11,0))
        t.hide(20);t.restore(49)
        self.assertIsNone(t.candidate(50,0))
        t.hide(60);t.hide(61);t.restore(90)
        self.assertIsNone(t.candidate(90.2,0))
        self.assertEqual(t.candidate(90.5,0),"happy")
        t.restore(91)
        self.assertIsNone(t.candidate(92,0))
        t.hide(100);t.restore(150)
        self.assertIsNone(t.candidate(151,0,blocked=True))
        self.assertEqual(t.candidate(152,0),"happy")
        t.hide(200);t.restore(240)
        self.assertIsNone(t.candidate(251,0,blocked=True))
        self.assertIsNone(t.candidate(252,0))


if __name__=="__main__":unittest.main()
