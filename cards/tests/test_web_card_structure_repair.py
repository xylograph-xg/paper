import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from core.catalog import Catalog
from cards import web_card_queue
from cards.web_card_inputs import digest, SCHEMA
from cards.web_card_structure_repair import schedule, authorized_archives
from browser.attempt_history import submission_history
from codex_desktop_chat.bundles import prepare_upload_bundle


class StructureRepairTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite3');self.pid=self.catalog.upsert({'title':'Synthetic'})
        self.source=self.root/'original.pdf';self.source.write_bytes(b'original')
        self.catalog.update(self.pid,asset_path=str(self.source),asset_hash=digest(self.source))
        web_card_queue.install(self.catalog)
        self.folder=self.root/'web_cards'/self.pid;self.folder.mkdir(parents=True)
        for name,value in [('source.pdf','clean original'),('visual.pdf','visual'),('prompt.txt','old source-only prompt')]:
            (self.folder/name).write_text(value)
        (self.folder/'source-context.json').write_text(json.dumps({'source_text':['original text'],'schema':SCHEMA}))
        self.packet={'source_original_sha256':digest(self.source),'page_manifest':[],
            'input_hashes':{n:digest(self.folder/n) for n in ['source.pdf','visual.pdf','source-context.json','prompt.txt']}}
        (self.folder/'packet.json').write_text(json.dumps(self.packet))
        chat=self.folder/'chatgpt';chat.mkdir();(chat/'response-raw.txt').write_text('{"incomplete":true}')
        (chat/'prompt-actual.txt').write_text((self.folder/'prompt.txt').read_text())
        self.attempt={'state':'response_saved','provider':'chatgpt','inputs':self.packet['input_hashes'],
            'raw_sha256':digest(chat/'response-raw.txt'),'actual_prompt_sha256':digest(chat/'prompt-actual.txt'),
            'conversation_url':'https://chatgpt.com/c/synthetic'}
        (chat/'attempt.json').write_text(json.dumps(self.attempt))
        (self.folder/'retry.json').write_text(json.dumps({'external_retries':2,'delivery_repair':{'used':1}}))
        with self.catalog.connect() as db:
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,'{}','failed','original')",
                       (self.pid,digest(self.source),'Synthetic'))
            db.execute("CREATE TABLE web_page_queue(paper_id TEXT PRIMARY KEY,target_id TEXT,state TEXT,assigned REAL,error TEXT)")
        self.candidate=self.root/'candidates'/self.pid;self.candidate.mkdir(parents=True)
        for name in ['source.pdf','visual.pdf','source-context.json']:(self.candidate/name).write_bytes((self.folder/name).read_bytes())
        (self.candidate/'prompt.txt').write_text('new generic source-only prompt')
        bundle=prepare_upload_bundle([str(self.candidate/n) for n in ['source.pdf','visual.pdf','source-context.json']],bundle_dir=self.root/'zips')
        packet={**self.packet,'upload_bundle':bundle,'input_hashes':{n:digest(self.candidate/n) for n in self.packet['input_hashes']}}
        (self.candidate/'packet.json').write_text(json.dumps(packet))
        self.item={'paper_id':self.pid,'candidate_folder':str(self.candidate),'candidate_packet_sha256':digest(self.candidate/'packet.json'),
            'candidate_bundle':bundle,'old_frozen_packet_sha256':digest(self.folder/'packet.json'),
            'old_attempt_sha256':digest(chat/'attempt.json'),'old_response_sha256':self.attempt['raw_sha256']}
        self.auth=self.root/'audit_index'/'structure.json';self.auth.parent.mkdir()
        self.auth.write_text(json.dumps({'kind':'human_one_extra_structure_retry','authorization_id':'synthetic',
            'max_extra_per_paper':1,'requests':[self.item]}))
        self.config={'catalog_path':str(self.catalog.path),'studio_library_root':str(self.root/'cards'),'web_cards':{'enabled':True}}

    def test_schedule_preserves_counters_and_old_inputs_and_is_single_use(self):
        old_prompt=(self.folder/'prompt.txt').read_bytes();old_raw=(self.folder/'chatgpt/response-raw.txt').read_bytes()
        self.assertEqual(schedule(self.config,self.auth)[0]['structure_repair_used'],1)
        ledger=json.loads((self.folder/'retry.json').read_text());self.assertEqual(ledger['external_retries'],2)
        self.assertEqual(ledger['delivery_repair']['used'],1)
        history=Path(ledger['structure_repair']['history']);self.assertEqual((history/'prompt.txt').read_bytes(),old_prompt)
        self.assertEqual((history/'chatgpt/response-raw.txt').read_bytes(),old_raw)
        self.assertEqual(digest(self.folder/'packet.json'),self.item['candidate_packet_sha256'])
        self.assertTrue(submission_history(self.folder).allowed)
        with self.assertRaises(ValueError):schedule(self.config,self.auth)

    def test_unknown_nested_attempt_blocks_without_consuming_grant(self):
        p=self.folder/'history'/'unknown';p.mkdir(parents=True);(p/'attempt.json').write_text(json.dumps({'state':'submitted'}))
        with self.assertRaises(ValueError):schedule(self.config,self.auth)
        self.assertNotIn('structure_repair',json.loads((self.folder/'retry.json').read_text()))

    def test_changed_candidate_and_changed_original_source_block(self):
        (self.candidate/'prompt.txt').write_text('changed')
        with self.assertRaises(ValueError):schedule(self.config,self.auth)
        (self.candidate/'prompt.txt').write_text('new generic source-only prompt');self.source.write_bytes(b'changed original')
        with self.assertRaises(ValueError):schedule(self.config,self.auth)

    def test_pause_and_human_protection_block(self):
        control=self.root/'web-card-control.json';control.write_text(json.dumps({'paused_by_user':True}))
        with self.assertRaises(ValueError):schedule(self.config,self.auth)
        control.unlink();self.catalog.event(self.pid,'human_decision',{'keep':True})
        with self.assertRaises(ValueError):schedule(self.config,self.auth)

    def test_archive_change_and_new_unknown_request_are_not_exempt(self):
        schedule(self.config,self.auth);ledger=json.loads((self.folder/'retry.json').read_text())
        chat=self.folder/'chatgpt';chat.mkdir();(chat/'attempt.json').write_text(json.dumps({'state':'submitted'}))
        self.assertFalse(submission_history(self.folder).allowed)
        old=Path(ledger['structure_repair']['history'])/'chatgpt/response-raw.txt';old.write_text('changed')
        with self.assertRaises(ValueError):authorized_archives(self.folder,ledger['structure_repair'])

    def test_interrupted_grant_blocks_and_cannot_repeat(self):
        ledger=json.loads((self.folder/'retry.json').read_text());ledger['structure_repair']={'used':1,'state':'preparing'}
        (self.folder/'retry.json').write_text(json.dumps(ledger))
        with self.assertRaises(ValueError):submission_history(self.folder)
        with self.assertRaises(ValueError):schedule(self.config,self.auth)


if __name__=='__main__':unittest.main()
