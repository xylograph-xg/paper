"""Draft cleanup evidence and Cloudflare page-block detection."""
import sqlite3
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from browser.shared_page_health import _snapshot_result, SITE_BLOCK_ERROR
from browser.shared_page_repair import _draft_identity, stale_draft_eligible


class DraftCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = sqlite3.connect(self.root / 'catalog.sqlite3')
        self.db.execute('CREATE TABLE web_card_jobs(paper_id TEXT, state TEXT)')
        self.db.execute('CREATE TABLE card_review_jobs(id TEXT, state TEXT)')
        self.db.commit()

    def test_cloudflare_block_is_a_page_error_not_a_missing_composer(self):
        result = _snapshot_result('target', {
            'url': 'https://chatgpt.com/', 'body': 'Unable to load site\n\nPlease try again later.',
            'errors': []})
        self.assertTrue(result['site_blocked'])
        self.assertIn(SITE_BLOCK_ERROR, result['errors'])

    def test_identity_comes_from_the_frozen_material_marker(self):
        card = '材料标识 web-card-7fb6c82d-f97b-430d-9dcf-c4ce94b6ced5-9cdf5be0a310。'
        review = '材料标识 card-review-a62304baf3278b84d72188ea；待核对卡片指纹'
        self.assertEqual(_draft_identity(card)[0], 'card')
        self.assertEqual(_draft_identity(review), ('review', 'a62304baf3278b84d72188ea'))
        self.assertIsNone(_draft_identity('plain text'))

    def test_active_job_blocks_stale_clear_and_finished_job_allows_it(self):
        draft = '材料标识 web-card-7fb6c82d-f97b-430d-9dcf-c4ce94b6ced5-9cdf5be0a310。'
        self.db.execute("INSERT INTO web_card_jobs VALUES(?,?)",
                        ('7fb6c82d-f97b-430d-9dcf-c4ce94b6ced5', 'submitted'))
        self.db.commit()
        self.assertFalse(stale_draft_eligible(self.root, {'state': 'ready_blank'}, draft))
        self.db.execute("UPDATE web_card_jobs SET state='completed'")
        self.db.commit()
        self.assertTrue(stale_draft_eligible(self.root, {'state': 'ready_blank'}, draft))
        self.assertFalse(stale_draft_eligible(self.root, {'state': 'ready_blank',
                                                          'active_paper_id': 'x'}, draft))

    def test_slot_bound_to_another_job_never_clears(self):
        draft = '材料标识 card-review-a62304baf3278b84d72188ea'
        self.db.execute("INSERT INTO card_review_jobs VALUES(?,?)",
                        ('a62304baf3278b84d72188ea', 'ready'))
        self.db.commit()
        self.assertTrue(stale_draft_eligible(self.root, {'state': 'ready_blank'}, draft))
        self.assertFalse(stale_draft_eligible(self.root, {'state': 'ready_blank',
                                                          'job_id': 'other'}, draft))


if __name__ == '__main__':
    unittest.main()
