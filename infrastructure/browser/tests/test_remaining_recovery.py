"""Keep original request evidence while recovering proven local failures."""
import copy
import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from codex_desktop_chat.api import bundles__prepare_upload_bundle as prepare_bundle
from browser.collective_page_restart import eligible
from browser.shared_claim_recovery import locate_retired_receipt
from browser.attempt_history import read_attempt
from browser.shared_page_repair import stalled_page_fallback


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


class RemainingRecovery(unittest.TestCase):
    def test_legacy_review_bundle_requires_exact_packet_input_and_prompt_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'card_reviews/paper/review';folder.mkdir(parents=True)
            source=folder/'input.txt';source.write_text('original source')
            prompt=folder/'prompt-actual.txt';prompt.write_text('original prompt')
            bundle=prepare_bundle([str(source)],bundle_dir=str(root/'app-upload-zips'))
            packet={'job_id':'review','input_hashes':{'input.txt':digest(source)},
                    'actual_prompt_sha256':digest(prompt),'upload_bundle':bundle}
            path=folder/'packet.json';path.write_text(json.dumps(packet))
            record={'review_id':'review','state':'not_sent','target_id':'target','send_click_started':False,
                    'inputs':packet['input_hashes'],'actual_prompt_sha256':digest(prompt),
                    '_ledger_path':str(folder/'attempt.json')}
            snapshot={'target_id':'target','inspection_complete':True,'streaming':False,
                      'url':'https://chatgpt.com/','draft':'\n','attachments':1,
                      'attachment_names':[Path(bundle['zip_path']).stem+'(1).zip']}
            health={'health':'dirty','evidence':{'snapshot':snapshot}}
            self.assertTrue(eligible(health,{},record,[]))
            for update in ({'job_id':'other'},{'actual_prompt_sha256':'changed'}, {'input_hashes':{}}):
                path.write_text(json.dumps({**packet,**update}))
                self.assertFalse(eligible(health,{},record,[]))
            path.write_text(json.dumps(packet));source.write_text('changed source')
            self.assertFalse(eligible(health,{},record,[]))

    def test_unused_nonce_restored_numbered_zip_is_verified_and_user_draft_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'input.txt';source.write_text('original')
            bundle=prepare_bundle([str(source)],bundle_dir=str(root/'app-upload-zips'))
            entry={'never_submitted':True,'origin':'shared_page_health_repair','repair_id':'original-nonce',
                   '_material_root':str(root)}
            s={'target_id':'target','inspection_complete':True,'streaming':False,
               'url':'https://chatgpt.com/','draft':'\n','attachments':1,
               'attachment_names':[Path(bundle['zip_path']).stem+'(2).zip']}
            self.assertTrue(eligible({'health':'dirty','evidence':{'snapshot':s}},entry,None,[]))
            changed={**s,'draft':'user new draft'}
            self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':changed}},entry,None,[]))
            Path(bundle['zip_path']).write_bytes(b'corrupt')
            self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':s}},entry,None,[]))

    def test_whitespace_composer_does_not_block_archived_unknown_page_replacement(self):
        policy={'web_cards':{'shared_window':{'health_repair':{'replace_unrecoverable_pages':True}}}}
        s={'target_id':'target','inspection_complete':True,'streaming':False,'draft':'\n'}
        h={'health':'unknown','collect_allowed':False,'bounded_recheck':
           {'state':'still_protected','reads':1,'first_seen':0},'evidence':{'snapshot':s}}
        self.assertTrue(stalled_page_fallback(policy,h,{'state':'needs_inspection'}, {'target_id':'target'},at=160))
        h=copy.deepcopy(h);h['evidence']['snapshot']['draft']='user draft'
        self.assertFalse(stalled_page_fallback(policy,h,{}, {'target_id':'target'},at=160))

    def test_retired_receipt_can_use_exact_archived_original_without_rewriting_live_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'web_cards/paper/chatgpt';folder.mkdir(parents=True)
            ledger=folder/'attempt.json';ledger.write_text(json.dumps({'target_id':'old','state':'not_sent'}))
            original=ledger.read_bytes();record=read_attempt(ledger)
            archive=root/'diagnostics/ledger-before.json';archive.parent.mkdir();archive.write_bytes(original)
            ledger.write_text(json.dumps({'target_id':'new','state':'submitted'}));current=ledger.read_bytes()
            result=locate_retired_receipt(record,archive_path=archive)
            self.assertEqual(result['_ledger_sha256'],record['_ledger_sha256'])
            self.assertEqual(result['_ledger_path'],record['_ledger_path'])
            self.assertEqual(ledger.read_bytes(),current)
            archive.write_text(json.dumps({'target_id':'old','state':'changed'}))
            with self.assertRaises(ValueError):locate_retired_receipt(record,archive_path=archive)
