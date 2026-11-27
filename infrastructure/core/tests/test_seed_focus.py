import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from core import seed_focus as focus


class SeedFocus(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.path=self.root/'catalog.sqlite3';self.config={'catalog_path':str(self.path)}
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE manual_seed_roots(paper_id TEXT);CREATE TABLE papers(id TEXT,title TEXT,card_path TEXT);CREATE TABLE web_card_jobs(paper_id TEXT,state TEXT,error TEXT,updated TEXT);CREATE TABLE card_review_jobs(id TEXT,paper_id TEXT,state TEXT,error TEXT,result TEXT,updated TEXT);')
            db.execute("INSERT INTO manual_seed_roots VALUES('seed')");db.execute("INSERT INTO papers VALUES('seed','Seed',NULL)")
            db.execute("INSERT INTO web_card_jobs VALUES('seed','needs_inspection','original receipt missing','1970-01-01T00:01:40+00:00')")
        folder=self.root/'web_cards/seed/chatgpt';folder.mkdir(parents=True)
        (folder/'attempt.json').write_text('{"state":"submitted","send_click_started":true}')
        self.pause=self.root/'web-card-control.json';self.pause.write_text('{"paused_by_user":true}')

    def test_exclusive_filter_and_switch_never_changes_pause_or_receipts(self):
        old=self.pause.read_bytes();receipt=(self.root/'web_cards/seed/chatgpt/attempt.json').read_bytes()
        ordinary={'paper_id':'other'};seed={'paper_id':'seed'}
        self.assertTrue(focus.allowed(self.config,'other'));focus.set_enabled(self.config,True)
        with sqlite3.connect(self.path) as db:self.assertEqual(focus.filter_records(db,[ordinary,seed]),[seed])
        self.assertFalse(focus.allowed(self.config,'other'));self.assertTrue(focus.allowed(self.config,'seed'))
        focus.set_enabled(self.config,False);self.assertTrue(focus.allowed(self.config,'other'))
        self.assertEqual(self.pause.read_bytes(),old);self.assertEqual((self.root/'web_cards/seed/chatgpt/attempt.json').read_bytes(),receipt)

    def test_heartbeat_and_technical_error_do_not_reset_three_hour_clock(self):
        one=focus.monitor(self.config,at=1000)['items'][0];self.assertFalse(one['stalled'])
        two=focus.monitor(self.config,at=10900)['items'][0];self.assertTrue(two['stalled']);self.assertEqual(two['last_advanced_at'],100)
        with sqlite3.connect(self.path) as db:db.execute("UPDATE web_card_jobs SET error='different technical error',updated='new'")
        three=focus.monitor(self.config,at=12000)['items'][0];self.assertEqual(three['last_advanced_at'],100)
        self.assertEqual(len((self.root/'seed-tracking/seed/events.jsonl').read_text().splitlines()),2)

    def test_review_state_without_material_evidence_does_not_advance_clock(self):
        focus.monitor(self.config,at=1000)
        with sqlite3.connect(self.path) as db:db.execute("INSERT INTO card_review_jobs VALUES('review','seed','response_saved','','{}','new')")
        next_step=focus.monitor(self.config,at=2000)['items'][0];self.assertEqual(next_step['last_advanced_at'],100)
        focus.monitor(self.config,at=2100)
        with sqlite3.connect(self.path) as db:db.execute("UPDATE card_review_jobs SET state='needs_user',error='technical failure'")
        self.assertEqual(focus.monitor(self.config,at=2200)['items'][0]['last_advanced_at'],100)

    def test_original_evidence_survives_move_and_error_is_not_a_finished_card(self):
        item=focus.monitor(self.config,at=12000)['items'][0];manifest=json.loads(Path(item['evidence_manifest']).read_text())
        entry=manifest['inputs'][0];data=Path(entry['path']).read_bytes();Path(entry['path']).unlink()
        self.assertEqual(Path(entry['object']).read_bytes(),data);self.assertFalse(item['complete'])
        card=self.root/'card.json';card.write_text('{"meta":{"scientific_verified":true}}')
        with sqlite3.connect(self.path) as db:db.execute('UPDATE papers SET card_path=?',(str(card),))
        self.assertFalse(focus.monitor(self.config,at=13000)['items'][0]['complete'])

    def test_corrupt_focus_control_fails_closed_and_fetch_pause_is_separate(self):
        (self.root/'seed-focus-control.json').write_text('not json')
        self.assertTrue(focus.active(self.config));self.assertFalse(focus.allowed(self.config,'ordinary'))
        from core.control import pause_decision
        self.assertFalse(pause_decision(self.config,'fetch').allowed)
        self.assertEqual(self.pause.read_text(),'{"paused_by_user":true}')

    def test_ordinary_upload_is_refused_before_model_or_browser_operation(self):
        from browser.web_card_transport import submit_gpt_background,DeferredWeb
        focus.set_enabled(self.config,True);session=SimpleNamespace(_pending_answer=None,verify_settings=Mock())
        from contextlib import nullcontext
        with patch('browser.upload_trace.root',return_value=self.root):
            with self.assertRaises(DeferredWeb):submit_gpt_background(session,'prompt',[],upload_context={'paper_id':'ordinary'},lock_factory=nullcontext)
        session.verify_settings.assert_not_called()

    def test_literature_focus_overlay_preserves_original_control_bytes(self):
        from literature.background import read
        p=self.root/'literature-level1-control.json';p.write_text('{"paused_by_user":false}')
        original=p.read_bytes();focus.set_enabled(self.config,True)
        self.assertTrue(read(p)['paused_by_user']);self.assertTrue(read(p)['paused_by_seed_focus'])
        self.assertEqual(p.read_bytes(),original);focus.set_enabled(self.config,False)
        self.assertFalse(read(p)['paused_by_user'])

    def test_selected_card_requires_both_contracts_and_keeps_completed_trace(self):
        import hashlib
        card=self.root/'card.json';meta={'scientific_verified':True,'production_contract_complete':False,'source_original_sha256':'source'}
        card.write_text(json.dumps({'meta':meta}))
        run=self.root/'manual_seed_trials/seed/run.json';run.parent.mkdir(parents=True)
        def save_run():run.write_text(json.dumps({'state':'selected','winner':1,'source_sha256':'source','candidates':[{'round':1,'card_sha256':hashlib.sha256(card.read_bytes()).hexdigest()}]}))
        save_run()
        with sqlite3.connect(self.path) as db:db.execute('UPDATE papers SET card_path=?',(str(card),))
        self.assertFalse(focus.monitor(self.config,at=12000)['items'][0]['complete'])
        meta['production_contract_complete']=True;card.write_text(json.dumps({'meta':meta}));save_run()
        done=focus.monitor(self.config,at=13000)['items'][0];self.assertTrue(done['complete']);self.assertFalse(done['stalled'])
        self.assertTrue(Path(done['evidence_manifest']).exists());self.assertTrue((self.root/'seed-tracking/seed/events.jsonl').exists())

    def test_normal_manual_root_outside_three_candidate_experiment_can_finish(self):
        import hashlib
        card=self.root/'card.json';original={'title':'Original scientific content','meta':{}}
        card.write_text(json.dumps(original));sha=hashlib.sha256(card.read_bytes()).hexdigest()
        backup=self.root/'history/source-review-normal/card.json';backup.parent.mkdir(parents=True)
        backup.write_bytes(card.read_bytes())
        final={**original,'meta':{'scientific_verified':True,'production_contract_complete':True,
            'source_original_sha256':'source','source_review':{'job_id':'normal','card_sha256':sha,'report_sha256':'report'}}}
        card.write_text(json.dumps(final))
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE papers ADD COLUMN asset_hash TEXT')
            db.execute('UPDATE papers SET card_path=?,asset_hash=?',(str(card),'source'))
            db.execute("INSERT INTO card_review_jobs VALUES('normal','seed','passed','','{}','now')")
        self.assertTrue(focus.monitor(self.config,at=12000)['items'][0]['complete'])
        self.assertFalse((self.root/'manual_seed_trials/seed/run.json').exists())

    def test_seed_mode_holds_only_unclaimed_ordinary_page_bindings(self):
        from browser.shared_page_backlog import _cleanup
        focus.set_enabled(self.config,True)
        with sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE shared_page_backlog(lane TEXT,job_id TEXT,paper_id TEXT,target_id TEXT,state TEXT)')
            db.execute("INSERT INTO web_card_jobs VALUES('other','queued','','old')")
            db.execute("INSERT INTO shared_page_backlog VALUES('cards','other','other','page','queued')")
            db.execute("INSERT INTO shared_page_backlog VALUES('cards','other-active','other','active','claimed')")
            _cleanup(db,self.config)
            self.assertEqual([r['state'] for r in db.execute('SELECT * FROM shared_page_backlog')],['claimed'])
            self.assertEqual(db.execute("SELECT state FROM web_card_jobs WHERE paper_id='other'").fetchone()[0],'queued')
        self.assertEqual(len(list((self.root/'seed-focus-held-bindings').glob('*.json'))),1)

    def test_submitted_and_unknown_requests_do_not_advance_material_clock(self):
        focus.monitor(self.config,at=1000)
        path=self.root/'web_cards/seed/chatgpt/attempt.json'
        data={'state':'needs_inspection','send_click_started':True,'created':1100,'target_id':'original-target','actual_prompt_sha256':'original-prompt'}
        path.write_text(json.dumps(data));self.assertEqual(focus.monitor(self.config,at=1200)['items'][0]['last_advanced_at'],100)
        data['state']='submitted';path.write_text(json.dumps(data))
        self.assertEqual(focus.monitor(self.config,at=1300)['items'][0]['last_advanced_at'],100)
        self.assertEqual(focus.monitor(self.config,at=1400)['items'][0]['last_advanced_at'],100)

    def test_review_metadata_publication_keeps_binding_but_scientific_edit_does_not(self):
        import hashlib
        card=self.root/'card.json';original={'title':'science','meta':{'source_original_sha256':'source'}};card.write_text(json.dumps(original));raw=card.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        backup=self.root/'history/source-review-reviewed/card.json';backup.parent.mkdir(parents=True);backup.write_bytes(raw)
        selected={'round':1,'card_sha256':sha,'review_id':'reviewed','report_sha256':'report'}
        run=self.root/'manual_seed_trials/seed/run.json';run.parent.mkdir(parents=True);run.write_text(json.dumps({'state':'selected','winner':1,'source_sha256':'source','candidates':[selected]}))
        final={'title':'science','meta':{'source_original_sha256':'source','scientific_verified':True,'production_contract_complete':True,
            'source_review':{'job_id':'reviewed','card_sha256':sha,'report_sha256':'report'}}};card.write_text(json.dumps(final))
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE papers SET card_path=?',(str(card),));db.execute("INSERT INTO card_review_jobs VALUES('reviewed','seed','passed','','{}','now')")
        self.assertTrue(focus.monitor(self.config,at=12000)['items'][0]['complete'])
        final['title']='changed science';card.write_text(json.dumps(final))
        self.assertFalse(focus.monitor(self.config,at=13000)['items'][0]['complete'])

    def test_repaired_successor_finishes_only_with_same_trial_and_passing_version(self):
        import hashlib
        card=self.root/'card.json';old={'title':'repaired science','meta':{}};card.write_text(json.dumps(old));raw=card.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        backup=self.root/'history/source-review-final/card.json';backup.parent.mkdir(parents=True);backup.write_bytes(raw)
        run=self.root/'manual_seed_trials/seed/run.json';run.parent.mkdir(parents=True);run.write_text(json.dumps({'id':'authorized-run','state':'repairing','source_sha256':'source','candidates':[]}))
        meta={'scientific_verified':True,'production_contract_complete':True,'source_original_sha256':'source','selection':{'manual_seed_trial':{'run_id':'wrong-run'}},
            'source_review':{'job_id':'final','card_sha256':sha,'report_sha256':'report'}}
        card.write_text(json.dumps({'title':'repaired science','meta':meta}))
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE papers SET card_path=?',(str(card),));db.execute("INSERT INTO card_review_jobs VALUES('final','seed','passed','','{}','now')")
        self.assertFalse(focus.monitor(self.config,at=12000)['items'][0]['complete'])
        meta['selection']['manual_seed_trial']['run_id']='authorized-run';card.write_text(json.dumps({'title':'repaired science','meta':meta}))
        self.assertTrue(focus.monitor(self.config,at=13000)['items'][0]['complete'])

    def test_fetch_keeper_survives_focus_but_still_respects_user_pause(self):
        from fetch.fetch_service import _keeper_paused,paused
        focus.set_enabled(self.config,True)
        self.assertTrue(paused(self.config));self.assertFalse(_keeper_paused(self.config))
        control=self.root/'fetch-control.json';control.write_text('{"paused_by_user":true,"reason":"user stop"}')
        self.assertTrue(_keeper_paused(self.config))
        from core.control import pause_decision
        self.assertEqual(pause_decision(self.config,'fetch').reason,'user stop')
        focus.set_enabled(self.config,False);self.assertTrue(_keeper_paused(self.config))
        control.write_text('{"paused_by_user":false}')
        self.assertFalse(_keeper_paused(self.config))

    def test_focus_review_producer_leaves_ordinary_saved_reports_unapplied(self):
        import threading
        from contextlib import contextmanager
        from concurrent.futures import Future
        from review.card_review_queue import ReviewProducer
        focus.set_enabled(self.config,True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE shared_workflow_arrivals(lane TEXT,job_id TEXT,queued_at REAL,sequence INTEGER)')
            db.execute("INSERT INTO card_review_jobs VALUES('ordinary','other','response_saved','','{}','old')")
            db.execute("INSERT INTO card_review_jobs VALUES('seed-review','seed','response_saved','','{}','old')")
            db.execute("INSERT INTO shared_workflow_arrivals VALUES('review','ordinary',1,1)")
            db.execute("INSERT INTO shared_workflow_arrivals VALUES('review','seed-review',2,2)")
        @contextmanager
        def connect():
            db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()
        producer=ReviewProducer.__new__(ReviewProducer);producer.config={**self.config,'card_review':{'parallel_jobs':1}};producer.catalog=SimpleNamespace(path=self.path,connect=connect)
        producer.stop_event=threading.Event();producer.futures={};producer.executor=Mock();claimed=[]
        def submit(callback,*args):
            if args:claimed.append(args[0]['paper_id']);producer.stop_event.set()
            return Future()
        producer.executor.submit.side_effect=submit
        with patch('review.card_review_queue.enabled',return_value=True),patch('browser.api.shared_page_backlog__preparation_head_ids',return_value=set()):producer.run()
        self.assertEqual(claimed,['seed'])
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute("SELECT state FROM card_review_jobs WHERE id='ordinary'").fetchone()[0],'response_saved')

class QualifiedMaterialClock(unittest.TestCase):
    setUp=SeedFocus.setUp

    def complete_receipt(self, lane='card_reviews', *, finished=1800):
        import hashlib
        with sqlite3.connect(self.path) as db:
            columns={r[1] for r in db.execute('pragma table_info(papers)')}
            if 'asset_hash' not in columns:db.execute('alter table papers add column asset_hash text')
            db.execute("update papers set asset_hash='source'")
        folder=self.root/lane/'seed'/('review' if lane=='card_reviews' else 'chatgpt')
        folder.mkdir(parents=True,exist_ok=True);prompt=b'original frozen prompt';raw=b'{"complete":"original answer"}'
        (folder/'prompt-actual.txt').write_bytes(prompt);(folder/'response-raw.txt').write_bytes(raw)
        hashes={'source.pdf':'frozen-source'}
        packet={'source_original_sha256':'source','input_hashes':hashes}
        packet_path=folder/'packet.json' if lane=='card_reviews' else folder.parent/'packet.json';packet_path.write_text(json.dumps(packet))
        a={'state':'response_saved','created':1100,'finished':finished,'target_id':'target',
           'actual_prompt_sha256':hashlib.sha256(prompt).hexdigest(),'raw_sha256':hashlib.sha256(raw).hexdigest(),
           'inputs':hashes,'conversation_url':'https://chatgpt.com/c/original'}
        (folder/'attempt.json').write_text(json.dumps(a));return folder,a

    def test_complete_review_uses_original_finished_time_not_poll_time(self):
        focus.monitor(self.config,at=1000);self.complete_receipt()
        item=focus.monitor(self.config,at=2000)['items'][0]
        self.assertEqual(item['last_advanced_at'],1800)
        self.assertEqual(focus.monitor(self.config,at=3000)['items'][0]['last_advanced_at'],1800)

    def test_ended_empty_and_only_submitted_never_advance(self):
        focus.monitor(self.config,at=1000);folder,a=self.complete_receipt('web_cards')
        a.update(state='submitted',send_click_started=True);(folder/'attempt.json').write_text(json.dumps(a))
        (folder/'response-raw.txt').unlink()
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],100)

    def test_false_legacy_clock_is_corrected_with_old_bytes_retained(self):
        import hashlib
        focus.monitor(self.config,at=1000);self.complete_receipt()
        saved=self.root/'seed-tracking/seed/trace.json';old=json.loads(saved.read_text());old.pop('qualified_progress',None)
        old['last_advanced_at']=1900;old['checked_at']=1900;raw=json.dumps(old).encode();saved.write_bytes(raw)
        item=focus.monitor(self.config,at=2000)['items'][0]
        self.assertEqual(item['last_advanced_at'],1800)
        proof=item['clock_migration_evidence'];self.assertEqual(proof['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(Path(proof['path']).read_bytes(),raw)
        self.assertEqual(focus.monitor(self.config,at=2500)['items'][0]['last_advanced_at'],1800)

    def test_archiving_and_late_finish_update_do_not_refresh_clock(self):
        import shutil
        focus.monitor(self.config,at=1000);folder,a=self.complete_receipt('web_cards')
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],1800)
        archive=folder.parent/'history'/'moved';archive.mkdir(parents=True)
        folder.rename(archive/'chatgpt');(folder.parent/'packet.json').rename(archive/'packet.json')
        a['finished']=2300;(archive/'chatgpt/attempt.json').write_text(json.dumps(a))
        self.assertEqual(focus.monitor(self.config,at=2400)['items'][0]['last_advanced_at'],1800)

    def test_corrupt_raw_prompt_or_source_binding_cannot_advance(self):
        focus.monitor(self.config,at=1000);folder,a=self.complete_receipt()
        (folder/'response-raw.txt').write_bytes(b'changed')
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],100)
        (folder/'response-raw.txt').write_bytes(b'{"complete":"original answer"}')
        (folder/'prompt-actual.txt').write_bytes(b'changed prompt')
        self.assertEqual(focus.monitor(self.config,at=2100)['items'][0]['last_advanced_at'],100)
        (folder/'prompt-actual.txt').write_bytes(b'original frozen prompt')
        pkt=json.loads((folder/'packet.json').read_text());pkt['source_original_sha256']='other source';(folder/'packet.json').write_text(json.dumps(pkt))
        self.assertEqual(focus.monitor(self.config,at=2200)['items'][0]['last_advanced_at'],100)

    def test_card_body_advances_once_but_metadata_and_status_do_not(self):
        import os
        focus.monitor(self.config,at=1000)
        with sqlite3.connect(self.path) as db:
            db.execute('alter table papers add column asset_hash text');db.execute("update papers set asset_hash='source'")
        card=self.root/'card.json';value={'title':'first','meta':{'producer':'web_card_service','source_original_sha256':'source'}}
        card.write_text(json.dumps(value));os.utime(card,(1500,1500))
        with sqlite3.connect(self.path) as db:db.execute('update papers set card_path=?',(str(card),))
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],1500)
        value['meta']['diagnostic']='new status';card.write_text(json.dumps(value));os.utime(card,(2200,2200))
        self.assertEqual(focus.monitor(self.config,at=2300)['items'][0]['last_advanced_at'],1500)
        value['title']='second';card.write_text(json.dumps(value));os.utime(card,(2400,2400))
        self.assertEqual(focus.monitor(self.config,at=2500)['items'][0]['last_advanced_at'],2400)

    def test_completed_review_is_seen_even_after_immediate_rework_state(self):
        focus.monitor(self.config,at=1000);self.complete_receipt()
        with sqlite3.connect(self.path) as db:db.execute("insert into card_review_jobs values('review','seed','rework_queued','','{}','new')")
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],1800)

    def test_duplicate_original_receipts_do_not_create_new_progress(self):
        import shutil
        focus.monitor(self.config,at=1000);folder,a=self.complete_receipt('web_cards')
        self.assertEqual(focus.monitor(self.config,at=2000)['items'][0]['last_advanced_at'],1800)
        archive=folder.parent/'history'/'copy';archive.mkdir(parents=True);shutil.copytree(folder,archive/'chatgpt');shutil.copyfile(folder.parent/'packet.json',archive/'packet.json')
        self.assertEqual(focus.monitor(self.config,at=3000)['items'][0]['last_advanced_at'],1800)

    def test_current_scientific_pass_and_production_are_distinct_evidence(self):
        import hashlib,os
        focus.monitor(self.config,at=1000)
        with sqlite3.connect(self.path) as db:
            db.execute('alter table papers add column asset_hash text');db.execute("update papers set asset_hash='source'")
        card=self.root/'card.json';original={'title':'science','meta':{'producer':'web_card_service','source_original_sha256':'source'}}
        card.write_text(json.dumps(original));sha=hashlib.sha256(card.read_bytes()).hexdigest()
        backup=self.root/'history/source-review-reviewed/card.json';backup.parent.mkdir(parents=True);backup.write_bytes(card.read_bytes())
        value={**original,'meta':{**original['meta'],'source_review':{'job_id':'reviewed','card_sha256':sha,'report_sha256':'report'}}}
        card.write_text(json.dumps(value));os.utime(card,(1200,1200))
        result={'full_source_checked':True,'weighted_score':90,'verdict':'pass','missing_inputs':[],'issue_counts':{'major':1}}
        with sqlite3.connect(self.path) as db:
            db.execute('update papers set card_path=?',(str(card),));db.execute('insert into card_review_jobs values(?,?,?,?,?,?)',('reviewed','seed','passed','',json.dumps(result),'1970-01-01T00:25:00+00:00'))
        with sqlite3.connect(self.path) as db:
            db.execute('alter table card_review_jobs add column source_sha256 text')
            db.execute('alter table card_review_jobs add column card_sha256 text')
            db.execute('update card_review_jobs set source_sha256=?,card_sha256=?',('source',sha))
        self.assertEqual(focus.monitor(self.config,at=1600)['items'][0]['last_advanced_at'],1200)
        result['issue_counts']['major']=0
        with sqlite3.connect(self.path) as db:
            db.execute('update card_review_jobs set result=?,source_sha256=?,card_sha256=?',(json.dumps(result),'foreign-source',sha))
        self.assertEqual(focus.monitor(self.config,at=1650)['items'][0]['last_advanced_at'],1200)
        with sqlite3.connect(self.path) as db:db.execute("update card_review_jobs set source_sha256='source'")
        item=focus.monitor(self.config,at=1700)['items'][0];self.assertEqual(item['last_advanced_at'],1500);self.assertFalse(item['complete'])
        value['meta'].update(scientific_verified=True,production_contract_complete=True)
        card.write_text(json.dumps(value));os.utime(card,(1800,1800))
        item=focus.monitor(self.config,at=2000)['items'][0];self.assertEqual(item['last_advanced_at'],1800);self.assertTrue(item['complete'])
        self.assertEqual(focus.monitor(self.config,at=2500)['items'][0]['last_advanced_at'],1800)
