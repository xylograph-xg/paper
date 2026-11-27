import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

from core.catalog import Catalog
from review import card_review_queue as queue
from review.card_review_lane import ReviewLane


class ReviewLedgerReads(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite');queue.install(self.catalog)
        self.lane=ReviewLane.__new__(ReviewLane);self.lane.catalog=self.catalog
        for i in range(3):
            folder=self.root/str(i);folder.mkdir();a={'target_id':'wanted' if i==0 else 'other-'+str(i),'state':'submitted','review_id':str(i)}
            (folder/'attempt.json').write_text(json.dumps(a))
            with self.catalog.connect() as db:db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                (str(i),'paper-'+str(i),'card','source','title','submitted',str(folder),json.dumps({'history':'x'*10000}),'now'))

    def test_latest_never_reads_historical_report_bodies_or_runs_rows_installer(self):
        connect=self.catalog.connect
        @contextmanager
        def thin():
            with connect() as db:
                db.set_authorizer(lambda op,table,column,*args:sqlite3.SQLITE_DENY if op==sqlite3.SQLITE_READ and table=='card_review_jobs' and column=='result' else sqlite3.SQLITE_OK)
                yield db
        with patch.object(self.catalog,'connect',thin),patch.object(queue,'rows',side_effect=AssertionError('full report loader')):
            self.assertEqual(len(self.lane.latest()),3)

    def test_page_scoped_collection_reads_only_that_pages_job_and_keeps_raw_ledger(self):
        path=self.root/'0/attempt.json';raw=path.read_bytes()
        rows=list(self.lane.ledgers(targets={'wanted'}));self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][2]['id'],'0');self.assertNotIn('_ledger_sha256',rows[0][1]);self.assertEqual(path.read_bytes(),raw)
        path.write_text(json.dumps({'target_id':'wanted','state':'response_saved','review_id':'0'}))
        self.assertEqual(list(self.lane.ledgers(targets={'wanted'}))[0][1]['state'],'response_saved')

    def test_reconciliation_filter_does_not_load_unrelated_states(self):
        self.assertEqual(list(self.lane.ledgers(states={'submitting'})),[])
