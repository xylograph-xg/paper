import unittest
from unittest.mock import Mock
from browser.shared_page_repair import bounded_recheck


class BoundedRecheckTests(unittest.TestCase):
    def health(self,kind='unknown'):
        return {'health':kind,'reason':'original evidence','evidence':{'fingerprint':'same'}}

    def test_only_one_additional_read_after_sixty_seconds(self):
        reread=Mock(side_effect=lambda:self.health())
        first=bounded_recheck(self.health(),None,{}, {},reread,at=100)
        early=bounded_recheck(self.health(),first,{}, {},reread,at=159)
        reread.assert_not_called()
        second=bounded_recheck(self.health(),early,{}, {},reread,at=160)
        self.assertEqual(second['bounded_recheck']['state'],'still_protected')
        later=bounded_recheck(self.health(),second,{}, {},reread,at=20000)
        self.assertEqual(reread.call_count,1);self.assertEqual(later['health'],'unknown')

    def test_matching_live_response_can_reconcile_without_overwriting_or_resending(self):
        reread=Mock(return_value=self.health('completed_saved'))
        first=bounded_recheck(self.health('saved_response_protected'),None,{}, {},reread,at=100)
        second=bounded_recheck(self.health('saved_response_protected'),first,{}, {},reread,at=160)
        self.assertEqual(second['health'],'completed_saved')
        self.assertEqual(second['bounded_recheck']['state'],'reconciled')

    def test_new_ledger_fingerprint_starts_a_separate_bounded_check(self):
        reread=Mock()
        first=bounded_recheck(self.health(),None,{'_ledger_sha256':'old'}, {},reread,at=100)
        second=bounded_recheck(self.health(),first,{'_ledger_sha256':'new'}, {},reread,at=1000)
        reread.assert_not_called();self.assertEqual(second['bounded_recheck']['first_seen'],1000)
