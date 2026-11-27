import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, now
from correction.card_correction_lane import CorrectionLane
from correction import card_correction_queue as queue
from cards import web_card_queue as cards
from core.services import atomic_json


class CorrectionLaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path), 'card_correction':{'enabled':True, 'parallel_jobs':4},
                       'web_cards':{'enabled':True}}
        cards.install(self.catalog); queue.install(self.catalog)

    def test_lane_creates_no_browser_connection_and_latest_preserves_receipt(self):
        selection = {'rework':{'kind':'source_review', 'correction_id':'independent-correction'}}
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)',
                       ('p', 'source', 'Synthetic', json.dumps(selection), 'submitted', now()))
        root = self.root/'web_cards'/'p'/'chatgpt'; root.mkdir(parents=True)
        attempt = {'target_id':'own-target', 'state':'needs_inspection', 'send_click_started':True,
                   'conversation_url':'https://chatgpt.com/c/original'}
        atomic_json(root/'attempt.json', attempt)
        lane = CorrectionLane(self.config, start_producer=False)
        self.assertIsNone(lane.producer)
        result = lane.latest()[0]
        self.assertEqual(result['kind'], 'correction'); self.assertIsNone(result['correction_id']); self.assertEqual(result['association'], 'unknown_legacy')
        self.assertEqual(result['state'], 'needs_inspection')
        self.assertEqual(json.loads((root/'attempt.json').read_text()), attempt)
        self.assertEqual(cards.jobs(self.catalog)[0]['state'], 'submitted')

    def test_pause_blocks_only_future_correction_requests(self):
        lane = CorrectionLane(self.config, start_producer=False)
        webjob = {'selection':json.dumps({'rework':{'correction_id':'c'}})}
        atomic_json(self.root/'web-card-control.json', {'paused_by_user':True})
        self.assertFalse(lane.allow(webjob))  # Nonexistent task is never dispatchable.
        atomic_json(self.root/'card-correction-control.json', {'paused_by_user':True})
        self.assertFalse(lane.allow(webjob)); self.assertFalse(lane.pending())
        self.assertEqual(lane.ready_requests(), [])

    def test_disabled_lane_does_not_start_or_resume_other_queues(self):
        self.config['card_correction']['enabled'] = False
        atomic_json(self.root/'card-review-control.json', {'paused_by_user':True})
        before = (self.root/'card-review-control.json').read_bytes()
        lane = CorrectionLane(self.config, start_producer=False)
        self.assertFalse(lane.allow({'selection':json.dumps({'rework':{'correction_id':'c'}})}))
        self.assertEqual(before, (self.root/'card-review-control.json').read_bytes())
        self.assertFalse(lane.pending()); lane.stop()


if __name__ == '__main__':
    unittest.main()
