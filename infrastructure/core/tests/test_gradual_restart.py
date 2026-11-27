import unittest
from core.gradual_restart import _busy, _remaining

class GradualRestartTest(unittest.TestCase):
    def test_active_work_blocks_restart(self):
        self.assertTrue(_busy({'workers':1},{'pages':[]}))
        self.assertTrue(_busy({'uploading_pages':1},{'pages':[]}))
        self.assertTrue(_busy({}, {'pages':[{'state':'generating'}]}))

    def test_idle_owner_is_restartable(self):
        self.assertFalse(_busy({'workers':0,'review_workers':0,'correction_workers':0,'uploading_pages':0},
                               {'pages':[{'state':'idle'},{'state':'complete'}]}))
        self.assertEqual(_remaining({'workers':1,'review_workers':2,'correction_workers':0,'uploading_pages':1},{}),4)
        self.assertEqual(_remaining({}, {'pages':[{'state':'generating'},{'state':'idle'}]}),1)

if __name__=='__main__':unittest.main()
