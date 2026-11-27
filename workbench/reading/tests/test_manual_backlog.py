import unittest
from browser.tests import test_shared_page_backlog as fixtures

class ManualBacklogTests(unittest.TestCase):
    setUp=fixtures.SharedPageBacklogTests.setUp
    paper=fixtures.SharedPageBacklogTests.paper
    card=fixtures.SharedPageBacklogTests.card
    maintain=fixtures.SharedPageBacklogTests.maintain
    raw_bindings=fixtures.SharedPageBacklogTests.raw_bindings

    def test_manual_head_reflows_full_inventory_without_rewriting_arrival(self):
        self.config['manual_literature']={'enabled':True}
        for i in range(100):self.card()
        self.maintain()
        self.assertFalse(self.maintain()['triggered'])
        _,pid,_=self.card('manual-late')
        paper=self.catalog.get(pid)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO manual_card_priority VALUES(?,?,?)',(pid,paper['asset_hash'],1))
            arrival=tuple(db.execute('SELECT * FROM shared_workflow_arrivals WHERE job_id=?',(pid,)).fetchone())
        result=self.maintain()
        self.assertTrue(result['triggered'])
        self.assertTrue(any(row['paper_id']==pid for row in self.raw_bindings()))
        with self.catalog.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM shared_workflow_arrivals WHERE job_id=?',(pid,)).fetchone()),arrival)
