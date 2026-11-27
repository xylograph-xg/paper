import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from browser.restored_web_draft import evidence

class RestoredDraft(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.text='材料标识 web-card-12345678-1234-1234-1234-123456789abc-abcd。正文'
        self.folder=self.root/'web_cards/12345678-1234-1234-1234-123456789abc/history/old/chatgpt';self.folder.mkdir(parents=True)
        (self.folder/'prompt-actual.txt').write_text(self.text)
        self.attempt={'state':'not_sent','send_click_started':False,'actual_prompt_sha256':hashlib.sha256(self.text.encode()).hexdigest()}
        self.save()
    def save(self):(self.folder/'attempt.json').write_text(json.dumps(self.attempt))
    def test_exact_archived_unsent_prompt_is_identified(self):self.assertIsNotNone(evidence(self.root,self.text))
    def test_unknown_send_never_authorizes_cleanup(self):
        self.attempt.update(state='needs_inspection',send_click_started=True);self.save();self.assertIsNone(evidence(self.root,self.text))
    def test_user_changes_preserve_draft(self):self.assertIsNone(evidence(self.root,self.text+'个人文字'))
    def test_changed_saved_prompt_preserves_draft(self):
        (self.folder/'prompt-actual.txt').write_text(self.text+'修改');self.assertIsNone(evidence(self.root,self.text))
    def test_completed_saved_pipeline_draft_can_be_identified(self):
        raw=b'complete saved answer';(self.folder/'response-raw.txt').write_bytes(raw)
        self.attempt.update(state='response_saved',send_click_started=True,conversation_url='https://chatgpt.com/c/original',raw_sha256=hashlib.sha256(raw).hexdigest());self.save()
        self.assertIsNotNone(evidence(self.root,self.text))
    def test_damaged_saved_receipt_never_authorizes_cleanup(self):
        (self.folder/'response-raw.txt').write_bytes(b'changed')
        self.attempt.update(state='response_saved',send_click_started=True,conversation_url='https://chatgpt.com/c/original',raw_sha256='wrong');self.save()
        self.assertIsNone(evidence(self.root,self.text))

    def test_review_draft_uses_archived_explicit_unsent_receipt(self):
        rid='a'*24;text='材料标识 card-review-'+rid+'；正文'
        folder=self.root/'card_reviews'/'paper'/rid;folder.mkdir(parents=True)
        (folder/'prompt-actual.txt').write_text(text)
        archive=folder/'history'/'unsent';archive.mkdir(parents=True)
        attempt={'review_id':rid,'state':'not_sent','send_click_started':False,
                 'actual_prompt_sha256':hashlib.sha256(text.encode()).hexdigest()}
        (archive/'attempt.json').write_text(json.dumps(attempt))
        self.assertIsNotNone(evidence(self.root,text))
        self.assertIsNone(evidence(self.root,text+'用户修改'))
        attempt['send_click_started']=True
        (archive/'attempt.json').write_text(json.dumps(attempt))
        self.assertIsNone(evidence(self.root,text))

    def test_verified_blank_requires_fresh_unchanged_ledger(self):
        import time
        from browser.restored_web_draft import verified_blank
        path=self.folder/'attempt.json'
        entry={'blank_history_verified_at':time.time(),
               'blank_history_ledger_hashes':{str(path):hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.assertTrue(verified_blank(entry))
        path.write_text('{}')
        self.assertFalse(verified_blank(entry))
        entry['blank_history_verified_at']=time.time()-61
        self.assertFalse(verified_blank(entry))
