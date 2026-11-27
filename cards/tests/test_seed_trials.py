"""Offline campaign safety, independent material identity and real-score selection."""
import copy
import json
import unittest
from unittest.mock import patch
from cards import seed_trials as trials
from cards.tests import test_web_card_retry as fixtures
from cards.web_card_inputs import prepare,digest
from review.card_review_queue import public_result


class SeedTrials(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RetryTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.catalog;self.pid=self.fixture.pid;self.root=self.fixture.root
        self.config=copy.deepcopy(self.fixture.config);self.config['card_review']={'enabled':True}
        self.auth=self.root/'authorization.md';self.auth.write_text('Explicit three new source-only candidates for this root.')
        self.config['web_cards']['manual_seed_trials']={'enabled':True,'rounds':3,'paper_ids':[self.pid],
            'authorization':str(self.auth),'authorization_sha256':digest(self.auth),'sources':{self.pid:digest(self.fixture.source)}}
        with self.c.connect() as db:
            db.execute('INSERT INTO manual_seed_roots VALUES(?,?,?,?)',(self.pid,str(self.fixture.source),digest(self.fixture.source),1))

    def test_unknown_original_is_retained_and_no_new_round_is_queued(self):
        original=self.fixture.attempt('submitted',send_click_started=True)
        report=trials.run_once(self.c,self.config)
        self.assertIn('证据',report['items'][0]['reason'])
        self.assertEqual(self.fixture.state(),'failed')
        self.assertEqual(json.loads((self.fixture.folder/'chatgpt/attempt.json').read_text()),original)
        self.assertEqual(trials._load(self.c,self.pid)['resets'],[])

    def test_explicit_unsent_archived_once_and_old_retry_count_retained(self):
        original=self.fixture.attempt('not_sent',send_click_started=False)
        (self.fixture.folder/'retry.json').write_text(json.dumps({'external_retries':2,'state':'old'}))
        report=trials.run_once(self.c,self.config)
        self.assertEqual(report['items'][0]['state'],'generating')
        run=trials._load(self.c,self.pid);self.assertEqual(run['round'],1)
        self.assertEqual(self.fixture.state(),'queued')
        self.assertEqual(json.loads((self.fixture.folder/'retry.json').read_text())['external_retries'],2)
        with self.c.connect() as db:job=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(self.pid,)).fetchone())
        paths=trials.archived_receipts(self.c,job)
        self.assertEqual(len(paths),1);self.assertEqual(json.loads(paths[0].read_text()),original)
        trials.run_once(self.c,self.config)
        self.assertEqual(len(trials._load(self.c,self.pid)['resets']),1)
        paths[0].write_text('{}')
        with self.assertRaises(ValueError):trials.archived_receipts(self.c,job)

    def test_archive_interruption_resumes_without_a_second_generation_intent(self):
        from core.archive_paths import move_with_links
        self.fixture.attempt('not_sent',send_click_started=False)
        def interrupted(*args):
            move_with_links(*args);raise OSError('synthetic interruption after directory move')
        with patch('core.archive_paths.move_with_links',side_effect=interrupted):
            trials.run_once(self.c,self.config)
        self.assertEqual(self.fixture.state(),'seed_trial_reset_pending')
        trials.run_once(self.c,self.config)
        run=trials._load(self.c,self.pid)
        self.assertEqual(self.fixture.state(),'queued');self.assertEqual(len(run['resets']),1)
        self.assertEqual(run['resets'][0]['state'],'committed')

    def test_original_claim_race_preserves_original_job_and_unstarted_intent(self):
        self.fixture.attempt('not_sent',send_click_started=False)
        original=trials._finish_reset
        def claim_first(catalog,config,run,paper):
            with catalog.connect() as db:db.execute("UPDATE web_card_jobs SET state='preparing' WHERE paper_id=?",(self.pid,))
            return original(catalog,config,run,paper)
        with patch('cards.seed_trials._finish_reset',side_effect=claim_first):
            trials.run_once(self.c,self.config)
        run=trials._load(self.c,self.pid)
        self.assertEqual(run['state'],'waiting');self.assertEqual(run['resets'][0]['state'],'not_started')
        self.assertEqual(self.fixture.state(),'preparing')
        self.assertTrue((self.fixture.folder/'chatgpt/attempt.json').exists())
        trials.run_once(self.c,self.config)
        self.assertEqual(len(trials._load(self.c,self.pid)['resets']),1)
        with self.c.connect() as db:db.execute("UPDATE web_card_jobs SET state='failed' WHERE paper_id=?",(self.pid,))
        trials.run_once(self.c,self.config)
        run=trials._load(self.c,self.pid)
        self.assertEqual(run['state'],'generating');self.assertEqual(len(run['resets']),2)

    def test_independent_generation_does_not_shorten_original_backoff(self):
        import time
        self.fixture.attempt('not_sent',send_click_started=False)
        deadline=time.time()+3600
        with self.c.connect() as db:db.execute('UPDATE web_card_jobs SET retry_at=? WHERE paper_id=?',(deadline,self.pid))
        report=trials.run_once(self.c,self.config)
        self.assertIn('backoff',report['items'][0]['reason'])
        self.assertEqual(trials._load(self.c,self.pid)['resets'],[])
        with self.c.connect() as db:self.assertEqual(db.execute('SELECT retry_at FROM web_card_jobs WHERE paper_id=?',(self.pid,)).fetchone()[0],deadline)

    def test_final_owner_guard_rechecks_root_scope_and_material_identity(self):
        self.fixture.attempt('not_sent',send_click_started=False)
        trials.run_once(self.c,self.config)
        with self.c.connect() as db:job=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(self.pid,)).fetchone())
        marker=json.loads(job['selection'])['manual_seed_trial']['request_id']
        packet=prepare(self.fixture.source,self.fixture.folder,self.pid,'Synthetic source',digest(self.fixture.source),independent_request=marker)
        trials.check_request(self.c,self.config,job,packet)
        context=self.fixture.folder/'source-context.json';value=json.loads(context.read_text());value['independent_request_id']='another-request';context.write_text(json.dumps(value))
        with self.assertRaises(ValueError):trials.check_request(self.c,self.config,job,packet)
        value['independent_request_id']=marker;context.write_text(json.dumps(value))
        with self.c.connect() as db:db.execute('DELETE FROM manual_seed_roots WHERE paper_id=?',(self.pid,))
        with self.assertRaises(ValueError):trials.check_request(self.c,self.config,job,packet)

    def test_fully_saved_old_generation_is_not_replayed_and_raw_answer_survives(self):
        self.fixture.attempt('response_saved',raw='original complete response',send_click_started=True)
        with self.c.connect() as db:db.execute("UPDATE web_card_jobs SET state='completed' WHERE paper_id=?",(self.pid,))
        report=trials.run_once(self.c,self.config)
        self.assertEqual(report['items'][0]['state'],'generating')
        run=trials._load(self.c,self.pid);history=self.fixture.folder/'history'/('manual-seed-trial-'+run['id']+'-1')
        self.assertEqual((history/'chatgpt/response-raw.txt').read_text(),'original complete response')

    def test_missing_archived_prompt_is_proven_without_changing_original_files(self):
        from browser.web_upload_bundle import ZIP_INSTRUCTION
        original=self.fixture.attempt('response_saved',raw='complete original answer',send_click_started=True)
        provider=self.fixture.folder/'chatgpt';actual=provider/'prompt-actual.txt'
        actual.write_text(actual.read_text()+ZIP_INSTRUCTION)
        original.update(actual_prompt_sha256=digest(actual),upload_bundle=self.fixture.packet['upload_bundle'])
        (provider/'attempt.json').write_text(json.dumps(original))
        (self.fixture.folder/'prompt.txt').unlink()
        before={path.name:path.read_bytes() for path in provider.iterdir()}
        proofs=trials._receipt_proofs(self.fixture.folder,digest(self.fixture.source))
        self.assertEqual(proofs[0]['archived_prompt_proof'],'exact_saved_wrapper_and_frozen_prompt_sha')
        self.assertFalse((self.fixture.folder/'prompt.txt').exists())
        self.assertEqual({path.name:path.read_bytes() for path in provider.iterdir()},before)
        report=trials.run_once(self.c,self.config)
        self.assertEqual(report['items'][0]['state'],'generating')
        with self.c.connect() as db:job=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(self.pid,)).fetchone())
        self.assertEqual(len(trials.archived_receipts(self.c,job)),1)

    def test_missing_prompt_proof_rejects_changed_prefix_or_changed_wrapper(self):
        from browser.web_upload_bundle import ZIP_INSTRUCTION
        original=self.fixture.attempt('response_saved',raw='complete original answer',send_click_started=True)
        provider=self.fixture.folder/'chatgpt';actual=provider/'prompt-actual.txt';prompt=actual.read_text()
        (self.fixture.folder/'prompt.txt').unlink()
        for text in ('changed-prefix'+ZIP_INSTRUCTION,prompt+'changed-wrapper'):
            actual.write_text(text)
            original.update(actual_prompt_sha256=digest(actual),upload_bundle=self.fixture.packet['upload_bundle'])
            (provider/'attempt.json').write_text(json.dumps(original))
            with self.assertRaises(ValueError):trials._receipt_proofs(self.fixture.folder,digest(self.fixture.source))

    def test_pauses_human_decisions_and_source_change_never_reset(self):
        from core.services import atomic_json
        atomic_json(self.c.path.parent/'web-card-control.json',{'paused_by_user':True})
        self.assertEqual(trials.run_once(self.c,self.config)['state'],'paused')
        self.assertIsNone(trials._load(self.c,self.pid))
        atomic_json(self.c.path.parent/'web-card-control.json',{'paused_by_user':False})
        self.fixture.source.write_bytes(b'changed')
        self.assertIn('指纹',trials.run_once(self.c,self.config)['items'][0]['reason'])
        self.assertEqual(self.fixture.state(),'failed')

    def test_authorization_change_and_out_of_scope_root_do_not_start(self):
        self.auth.write_text('changed authorization')
        with self.assertRaises(ValueError):trials.run_once(self.c,self.config)
        self.assertEqual(self.fixture.state(),'failed')

    def test_three_materials_have_independent_ids_without_old_answers(self):
        packets=[]
        for number in range(1,4):
            folder=self.root/('independent-'+str(number))
            packets.append(prepare(self.fixture.source,folder,self.pid,'Synthetic source',digest(self.fixture.source),independent_request='run-'+str(number)))
            context=json.loads((folder/'source-context.json').read_text())
            self.assertEqual(context['independent_request_id'],'run-'+str(number))
            self.assertNotIn('old_card',context);self.assertNotIn('assessment',context)
        self.assertEqual(len({p['upload_bundle']['zip_sha256'] for p in packets}),3)
        self.assertEqual(len({p['source_original_sha256'] for p in packets}),1)
        with self.assertRaises(ValueError):prepare(self.fixture.source,self.root/'invalid',self.pid,'x',digest(self.fixture.source),independent_request='bad/marker')

    def test_priority_marker_is_never_a_displayed_quality_score(self):
        row=public_result({'priority':1000000.0,'result':'{}'})
        self.assertIsNone(row['priority']);self.assertIsNone(row['review_score'])
        row=public_result({'priority':1000000.0,'article_quality':82.0,'result':'{"weighted_score":91}'})
        self.assertEqual(row['priority'],82);self.assertEqual(row['review_score'],91)

    def candidate(self,number,score,**changes):
        assessment={'weighted_score':score,'pass':True,'model_report_pass':True,'action':'pass','verdict':'pass',
            'full_source_checked':True,'missing_inputs':[],'issue_counts':{'major':0,'critical':0}}
        assessment.update(changes)
        return {'round':number,'assessment':assessment}

    def test_highest_complete_passing_review_wins_without_changing_scores(self):
        rows=[self.candidate(1,91),self.candidate(2,99,issue_counts={'major':1,'critical':0}),self.candidate(3,94)]
        before=copy.deepcopy(rows)
        self.assertIs(trials.choose(rows),rows[2]);self.assertEqual(rows,before)
        self.assertIsNone(trials.choose([self.candidate(1,99,missing_inputs=['figure']),self.candidate(2,84),self.candidate(3,98,verdict='revise')]))
        self.assertIsNone(trials.choose([self.candidate(1,95,action='correct')]))


class TrialReviewCapture(unittest.TestCase):
    def setUp(self):
        from review.tests import test_card_review_queue as review_fixtures
        from core.services import atomic_json
        self.f=review_fixtures.ReviewQueue();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.job,self.path,self.card=self.f.card('manual-root')
        self.auth=self.f.root/'auth.md';self.auth.write_text('explicit triple')
        self.f.config['web_cards']['manual_seed_trials']={'enabled':True,'rounds':3,'paper_ids':[self.job['paper_id']],
            'authorization':str(self.auth),'authorization_sha256':digest(self.auth),'sources':{self.job['paper_id']:self.job['source_sha256']}}
        marker={'run_id':'test-run','round':1,'request_id':'test-run-1'}
        self.card['meta']['selection']={'manual_seed_trial':marker};atomic_json(self.path,self.card)
        self.job['card_sha256']=digest(self.path)
        with self.f.catalog.connect() as db:
            db.execute('UPDATE card_review_jobs SET card_sha256=? WHERE id=?',(self.job['card_sha256'],self.job['id']))
        self.folder,self.packet=self.f.packet(self.job,self.card)
        self.f.receipt(self.folder,self.packet,self.f.feedback())
        trials._save(self.f.catalog,{'id':'test-run','paper_id':self.job['paper_id'],'source_sha256':self.job['source_sha256'],
            'state':'generating','round':1,'candidates':[],'resets':[]})

    def test_real_review_captured_without_publishing_before_three_and_duplicate_is_idempotent(self):
        from review import card_review_queue as q
        before=self.path.read_bytes()
        q.apply_result(self.f.catalog,self.job,self.f.config)
        run=trials._load(self.f.catalog,self.job['paper_id'])
        self.assertEqual(len(run['candidates']),1);self.assertEqual(run['candidates'][0]['assessment']['weighted_score'],90)
        self.assertEqual(self.path.read_bytes(),before)
        q.apply_result(self.f.catalog,self.job,self.f.config)
        self.assertEqual(len(trials._load(self.f.catalog,self.job['paper_id'])['candidates']),1)
        self.assertEqual(self.path.read_bytes(),before)
        with self.f.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM card_review_jobs WHERE id=?',(self.job['id'],)).fetchone()[0],'trial_reviewed')

    def test_fabricated_candidate_score_is_rejected(self):
        from review import card_review_queue as q
        from core.services import atomic_json
        data,result=q.parse_review((self.folder/'response-raw.txt').read_text(),self.folder)
        atomic_json(self.folder/'feedback.json',data)
        with self.assertRaisesRegex(ValueError,'替代评分'):
            trials.record_review(self.f.catalog,self.f.config,self.job,{**result,'weighted_score':100})
        self.assertEqual(trials._load(self.f.catalog,self.job['paper_id'])['candidates'],[])

    def test_late_first_round_callback_cannot_publish_while_round_two_waits(self):
        from review import card_review_queue as q
        before=self.path.read_bytes()
        q.apply_result(self.f.catalog,self.job,self.f.config)
        run=trials._load(self.f.catalog,self.job['paper_id']);run.update(state='generating',round=2)
        trials._save(self.f.catalog,run)
        q.apply_result(self.f.catalog,self.job,self.f.config)
        after=trials._load(self.f.catalog,self.job['paper_id'])
        self.assertEqual(after['state'],'generating');self.assertEqual(after['round'],2)
        self.assertEqual(len(after['candidates']),1);self.assertEqual(self.path.read_bytes(),before)

    def test_completed_candidate_is_not_collected_again_from_browser(self):
        from unittest.mock import Mock
        from review.card_review_lane import ReviewLane
        lane=ReviewLane.__new__(ReviewLane);lane.config=self.f.config
        lane.ledgers=Mock(return_value=[(self.folder/'attempt.json',{'state':'response_saved','target_id':'original'},
            {**self.job,'state':'trial_reviewed','result':'{}'})])
        page=Mock()
        active=lane.collect({'original':page},{},{},Mock(),Mock(),lambda:False)
        self.assertEqual(active,0);self.assertEqual(page.mock_calls,[])


    def test_three_rounds_keep_all_versions_choose_real_best_and_resume_post_publication_crash(self):
        import hashlib
        import shutil
        from core.services import atomic_json
        from review import card_review_queue as q
        f=self.f;pid=self.job['paper_id'];root=f.catalog.path.parent/'web_cards'/pid;root.mkdir(parents=True)
        with f.catalog.connect() as db:
            db.execute('INSERT INTO manual_seed_roots VALUES(?,?,?,?)',(pid,'root.pdf',self.job['source_sha256'],1))
            db.execute("UPDATE card_review_jobs SET state='superseded' WHERE id=?",(self.job['id'],))
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,'{}','completed','initial')",(pid,self.job['source_sha256'],'manual-root'))
        def receipt(number):
            for name,content in [('source.pdf','clean synthetic PDF'),('visual.pdf','visual'),('source-context.json','original source only'),('prompt.txt','source only generation '+str(number))]:
                (root/name).write_text(content)
            packet={'source_original_sha256':self.job['source_sha256'],'input_hashes':{n:digest(root/n) for n in ('source.pdf','visual.pdf','source-context.json','prompt.txt')}}
            atomic_json(root/'packet.json',packet)
            out=root/'chatgpt';out.mkdir(exist_ok=True);(out/'response-raw.txt').write_text('complete generation '+str(number))
            (out/'prompt-actual.txt').write_text((root/'prompt.txt').read_text())
            attempt={'provider':'chatgpt','state':'response_saved','inputs':packet['input_hashes'],
                'actual_prompt_sha256':digest(out/'prompt-actual.txt'),'raw_sha256':digest(out/'response-raw.txt'),
                'conversation_url':'https://chatgpt.com/c/generation-'+str(number),'send_click_started':True}
            atomic_json(out/'attempt.json',attempt);return packet,attempt
        receipt(0)
        run=trials._load(f.catalog,pid);run.update(state='waiting',candidates=[],resets=[]);trials._save(f.catalog,run)
        original=self.path.read_bytes();versions=[]
        for number,score in enumerate((9.0,9.5,9.2),1):
            report=trials.run_once(f.catalog,f.config)
            self.assertEqual(trials._load(f.catalog,pid)['round'],number,report)
            with f.catalog.connect() as db:
                selection=json.loads(db.execute('SELECT selection FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()[0])
            packet,attempt=receipt(number)
            version=self.path.parent/'publications'/('trial-'+str(number));version.mkdir(parents=True)
            card=copy.deepcopy(self.card);card['meta'].update(publication_id=version.name,input_hashes=packet['input_hashes'],selection=selection)
            card['meta']['source_sha256']=digest(root/'source.pdf')
            atomic_json(version/'card.json',card);shutil.copy2(root/'source.pdf',version/'source.pdf')
            atomic_json(version/'web-provenance.json',{'publication_id':version.name,'attempt':attempt})
            f.catalog.update(pid,card_path=str(version/'card.json'))
            rid='round-'+str(number);folder=f.root/'card_reviews'/pid/rid
            job={**self.job,'id':rid,'folder':str(folder),'card_sha256':digest(version/'card.json')}
            with f.catalog.connect() as db:
                db.execute("UPDATE web_card_jobs SET state='completed' WHERE paper_id=?",(pid,))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'web_card_generated',?,'now')",(pid,json.dumps({'card_path':str(version/'card.json')})))
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) VALUES(?,?,?,?,?,'response_saved',?,'now')",(rid,pid,job['card_sha256'],job['source_sha256'],'manual-root',str(folder)))
            review_folder,review_packet=f.packet(job,card);data=f.feedback();data['scores']={k:score for k in data['scores']}
            f.receipt(review_folder,review_packet,data)
            # Unique formal URL per independent review.
            record=json.loads((review_folder/'attempt.json').read_text());record['conversation_url']='https://chatgpt.com/c/review-'+str(number);atomic_json(review_folder/'attempt.json',record)
            q.apply_result(f.catalog,job,f.config);versions.append(version/'card.json')
            self.assertFalse(json.loads(versions[-1].read_text())['meta']['scientific_verified'])
        self.assertEqual(len(trials._load(f.catalog,pid)['candidates']),3)
        original_apply=q.apply_result
        def crash_after_publish(*args):
            original_apply(*args);raise OSError('synthetic crash after real publication')
        with patch('review.card_review_queue.apply_result',side_effect=crash_after_publish):
            trials.run_once(f.catalog,f.config)
        self.assertEqual(trials._load(f.catalog,pid)['state'],'selecting')
        trials.run_once(f.catalog,f.config)
        run=trials._load(f.catalog,pid)
        self.assertEqual(run['state'],'selected');self.assertEqual(run['winner'],2)
        self.assertEqual(f.catalog.get(pid)['card_path'],str(versions[1]))
        self.assertEqual(run['candidates'][1]['assessment']['weighted_score'],95)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertTrue(all(path.is_file() for path in versions))
        self.assertTrue(json.loads(versions[1].read_text())['meta']['scientific_verified'])
        self.assertFalse(json.loads(versions[1].read_text())['meta']['production_contract_complete'])

class SiblingFrozenPacket(unittest.TestCase):
    def test_reset_preserves_complete_sibling_retry_receipts_and_finds_exact_packet(self):
        import shutil
        from cards.tests.test_web_card_retry import RetryTests
        fixture=RetryTests('test_explicit_single_json_wrapper_keeps_scientific_values_and_delivery_guard');fixture.setUp()
        try:
            fixture.attempt('response_saved',raw='complete original answer',send_click_started=True)
            sibling=fixture.folder/'history/prior-retry/chatgpt';sibling.parent.mkdir(parents=True)
            shutil.copytree(fixture.folder/'chatgpt',sibling)
            packet=fixture.folder/'packet.json';moved=fixture.folder/'history/committed-reset/packet.json';moved.parent.mkdir(parents=True);packet.replace(moved)
            proofs=trials._receipt_proofs(fixture.folder,digest(fixture.source));self.assertEqual(len(proofs),2)
            self.assertEqual((sibling/'response-raw.txt').read_text(),'complete original answer')
            # No packet is synthesized and an unrelated identity is never substituted.
            self.assertFalse(packet.exists());original=moved.read_bytes();changed=json.loads(original);changed['source_original_sha256']='different';moved.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):trials._receipt_proofs(fixture.folder,digest(fixture.source))
        finally:fixture.doCleanups()
