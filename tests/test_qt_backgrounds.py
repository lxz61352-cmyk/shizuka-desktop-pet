import unittest
from qt_windows import Controller


class WindowBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.controller=Controller(None,lambda message:None)
        self.controller.receive(dict(type='style',background='',backgrounds=['C:/cards/one.webp','C:/cards/two.webp','C:/cards/three.webp']))

    def image(self,kind):return self.controller.background(kind).toLocalFile()

    def test_each_window_chooses_once_and_keeps_its_picture(self):
        first=self.image('history');second=self.image('todos')
        self.assertNotEqual(first,second)
        for _ in range(20):
            self.assertEqual(self.image('history'),first)
            self.assertEqual(self.image('todos'),second)

    def test_close_and_reopen_rerolls_without_changing_other_windows(self):
        self.controller.receive(dict(type='open',window='history'))
        first=self.image('history');other=self.image('todos')
        self.controller.close('history')
        self.controller.receive(dict(type='open',window='history'))
        self.assertNotEqual(self.image('history'),first)
        self.assertEqual(self.image('todos'),other)

    def test_raising_an_open_window_keeps_its_picture(self):
        self.controller.receive(dict(type='open',window='history'))
        first=self.image('history')
        self.controller.receive(dict(type='open',window='history'))
        self.assertEqual(self.image('history'),first)

    def test_brightness_and_blur_do_not_reroll(self):
        first=self.image('form-a');other=self.image('form-b')
        self.controller.receive(dict(type='style',darkness=.2,blur=16))
        self.assertEqual(self.image('form-a'),first)
        self.assertEqual(self.image('form-b'),other)

    def test_fixed_selection_applies_to_existing_and_new_windows(self):
        self.image('history');self.image('form-a')
        self.controller.receive(dict(type='style',background='C:/cards/fixed.webp',backgrounds=[]))
        for kind in ('history','form-a','form-new','editor'):
            self.assertEqual(self.image(kind),'C:/cards/fixed.webp')
            self.controller.open_background(kind)
            self.assertEqual(self.image(kind),'C:/cards/fixed.webp')

    def test_shuffling_only_changes_the_requested_window(self):
        first=self.image('history');other=self.image('todos')
        self.controller.receive(dict(type='shuffle_background',window='history'))
        self.assertNotEqual(self.image('history'),first)
        self.assertEqual(self.image('todos'),other)

    def test_destroyed_forms_release_background_entries(self):
        self.image('form-a');self.controller.forget_background('form-a')
        self.assertNotIn('form-a',self.controller.window_backgrounds)

    def test_missing_artwork_is_supported(self):
        self.controller.receive(dict(type='style',background='',backgrounds=[]))
        self.assertTrue(self.controller.background('history').isEmpty())


if __name__=='__main__':unittest.main()
