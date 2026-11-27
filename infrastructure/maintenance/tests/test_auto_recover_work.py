import time, unittest
from maintenance.auto_recover_work import _age

class AutoRecoverTests(unittest.TestCase):
    def test_age_accepts_epoch_and_iso(self):
        self.assertGreaterEqual(_age(time.time()-60),59)
        self.assertGreaterEqual(_age('2026-10-19T09:00:00+00:00'),0)
    def test_age_rejects_bad_value(self):
        self.assertEqual(_age('not-a-time'),0)

if __name__=='__main__':unittest.main()
