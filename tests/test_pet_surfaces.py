import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from pet_surfaces import WindowSurface,choose_support,exposed_support


class SurfaceTest(unittest.TestCase):
    def test_nearest_visible_top_and_taskbar_fallback(self):
        surfaces=[WindowSurface(1,(400,300,900,700)),WindowSurface(2,(300,650,1000,1000))]
        self.assertEqual(choose_support(surfaces,600,200,1040).handle,1)
        # The rear top at 650 is covered by the foreground window at this x.
        self.assertIsNone(choose_support(surfaces,600,350,1040))
        self.assertEqual(choose_support(surfaces,350,350,1040).handle,2)
        self.assertIsNone(choose_support(surfaces,100,200,1040))
        self.assertIsNone(choose_support(surfaces,600,900,1040))

    def test_negative_monitor_and_moved_or_closed_support(self):
        surface=WindowSurface(4,(-1800,500,-1000,950))
        self.assertEqual(choose_support([surface],-1400,200,1040),surface)
        self.assertEqual(exposed_support([surface],4,-1400),surface)
        self.assertIsNone(exposed_support([],4,-1400))
        moved=WindowSurface(4,(-900,550,-100,950))
        self.assertIsNone(exposed_support([moved],4,-1400))
        self.assertEqual(exposed_support([moved],4,-500),moved)
        self.assertIsNone(choose_support([WindowSurface(5,(0,0,1600,1040))],500,300,1040))


if __name__=="__main__":unittest.main()
