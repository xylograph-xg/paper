import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, now
from correction import card_correction_queue as correction
from review import card_review_queue as review
from cards import web_card_queue as cards
from core.services import atomic_json
from cards.web_card_inputs import digest


QUOTE = 'The observation was supported by an independent control experiment.'


class CorrectionQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path), 'studio_library_root':str(self.root/'library'),
            'card_review':{'enabled':True, 'parallel_jobs':4, 'max_reworks':2},
            'card_correction':{'enabled':True, 'parallel_jobs':4},
            'web_cards':{'enabled':True, 'max_parallel_jobs':20, 'shared_window':{'enabled':True}}}
        review.install(self.catalog); cards.install(self.catalog); correction.install(self.catalog)

    def card(self, name='Synthetic'):
        pid = self.catalog.upsert({'title':name, 'doi':'10.9999/'+name})
        source = self.root/(pid+'.pdf'); source.write_bytes(b'original synthetic PDF')
        folder = self.root/'library'/pid; folder.mkdir(parents=True)
        (folder/'source.pdf').write_bytes(b'clean synthetic PDF')
        card = {'title':name, 'info':{}, 'one_line_summary':'s', 'key_findings':'k', 'intro_summary':'i',
            'conclusion_summary':'c', 'warnings':[],
            'figures':[{'label':'Fig. 1', 'source_page':1, 'evidence_id':'P001', 'image_path':'P001.png',
                        'evidence_quote':QUOTE, 'summary':'A condition.'}], 'equations':[], 'tables':[],
            'paper_evaluation':{k:{'score':90, 'reason':'Synthetic source reason', 'source_pages':[1]}
                                for k in ('overall_quality', 'direction_novelty')},
            'meta':{'producer':'web_card_service', 'provider':'chatgpt', 'source_original_sha256':digest(source),
                    'source_sha256':digest(folder/'source.pdf'), 'scientific_verified':False,
                    'production_contract_complete':False}}
        path = folder/'card.json'; atomic_json(path, card)
        self.catalog.update(pid, asset_path=str(source), asset_hash=digest(source), card_path=str(path), acquisition='available')
        review.enqueue(self.catalog, self.config)
        job = next(j for j in review.rows(self.catalog) if j['paper_id'] == pid)
        return job, path, card

    def packet(self, job, card, texts=(QUOTE,)):
        folder = Path(job['folder']); folder.mkdir(parents=True, exist_ok=True)
        atomic_json(folder/'card-original.json', card)
        atomic_json(folder/'source-context.json', {'source_text':[{'source_page':i+1, 'text':t} for i,t in enumerate(texts)]})
        atomic_json(folder/'source-text-verified.json', list(texts))
        for name in ('source.pdf', 'visual.pdf', 'card-review.json', 'prompt.txt', 'prompt-actual.txt', 'bundle.zip'):
            (folder/name).write_text(name)
        packet = {'page_count':len(texts),
            'input_hashes':{n:digest(folder/n) for n in ('source.pdf', 'visual.pdf', 'source-context.json', 'card-original.json', 'card-review.json', 'prompt.txt')},
            'upload_bundle':{'zip_path':str(folder/'bundle.zip'), 'zip_sha256':digest(folder/'bundle.zip')},
            'actual_prompt_sha256':digest(folder/'prompt-actual.txt')}
        atomic_json(folder/'packet.json', packet)
        return folder, packet

    def feedback(self, action='formatting'):
        data = {'sample_kind':'mixed', 'scores':{k:9 for k in __import__('review.card_evaluation', fromlist=['RUBRIC']).RUBRIC},
            'missing_inputs':[], 'issues':[], 'verdict':'pass', 'source_identity_checked':True,
            'key_findings_checked':True, 'source_pages_reviewed':[1],
            'checked_items':[{'group':'figures', 'label':'Fig. 1', 'source_page':1}], 'corrections':[]}
        if action == 'formatting':
            data['corrections'] = [{'path':'figures.0.summary', 'before':'A condition.', 'after':'A\ncondition.',
                                    'source_page':1, 'source_quote':QUOTE}]
        elif action == 'rework':
            data.update(verdict='revise', issues=[{'severity':'major', 'finding':'Numerical mismatch',
                'evidence':'Source quote', 'source_page':1, 'source_quote':QUOTE, 'path':'figures.0.summary'}])
        return data

    def receipt(self, job, card, action='formatting'):
        folder, packet = self.packet(job, card); data = self.feedback(action)
        (folder/'response-raw.txt').write_text(json.dumps(data))
        atomic_json(folder/'attempt.json', {'state':'response_saved', 'finished':1,
            'raw_sha256':digest(folder/'response-raw.txt'), 'actual_prompt_sha256':packet['actual_prompt_sha256'],
            'inputs':packet['input_hashes'], 'conversation_url':'https://chatgpt.com/c/'+job['id']})
        parsed, result = review.parse_review((folder/'response-raw.txt').read_text(), folder)
        atomic_json(folder/'feedback.json', parsed); atomic_json(folder/'assessment.json', result)
        return folder, result

    def ambiguous_receipt(self,job,card):
        folder,_=self.receipt(job,card,'rework')
        data=json.loads((folder/'feedback.json').read_text());data['verdict']='cannot_evaluate'
        (folder/'response-raw.txt').write_text(json.dumps(data))
        attempt=json.loads((folder/'attempt.json').read_text());attempt['raw_sha256']=digest(folder/'response-raw.txt')
        atomic_json(folder/'attempt.json',attempt)
        data,result=review.parse_review((folder/'response-raw.txt').read_text(),folder)
        atomic_json(folder/'feedback.json',data);atomic_json(folder/'assessment.json',result)
        return folder,data,result

    def test_complete_ambiguity_with_grounded_defect_enters_bounded_rework(self):
        job,path,card=self.card();folder,data,result=self.ambiguous_receipt(job,card)
        self.assertEqual(result['action'],'needs_user');self.assertFalse(result['pass'])
        with self.assertRaises(ValueError):correction.enqueue_review(self.catalog,job,self.config)
        self.config['card_correction']['partial_ambiguous_rework']=True
        before=digest(path)
        task=correction.enqueue_review(self.catalog,job,self.config)
        self.assertEqual(task['kind'],'source_rework');self.assertEqual(task['state'],'queued')
        self.assertEqual(digest(path),before)
        self.assertTrue(json.loads(task['payload'])['preserve_original_ambiguity'])
        self.assertEqual(json.loads(task['payload'])['assessment']['verdict'],'cannot_evaluate')
        self.assertEqual(correction.enqueue_review(self.catalog,job,self.config)['id'],task['id'])

    def test_partial_rework_refuses_incomplete_unquoted_or_unknown_paths(self):
        job,path,card=self.card();folder,data,result=self.ambiguous_receipt(job,card)
        self.assertTrue(correction.partial_rework_allowed(data,result,folder))
        for changed in [{'full_source_checked':False},{'missing_inputs':['supplement']}]:
            self.assertFalse(correction.partial_rework_allowed(data,{**result,**changed},folder))
        for changed in [{'path':'figures.99.summary'},{'source_quote':'Invented source evidence that does not exist.'}]:
            altered=copy.deepcopy(data);altered['issues'][0].update(changed)
            self.assertFalse(correction.partial_rework_allowed(altered,result,folder))

    def original_card_receipt(self, job, path):
        root = self.root/'web_cards'/job['paper_id']; root.mkdir(parents=True, exist_ok=True)
        (root/'source.pdf').write_bytes(path.with_name('source.pdf').read_bytes())
        atomic_json(root/'source-context.json', {'source_text':[{'source_page':1, 'text':QUOTE}]})
        (root/'visual.pdf').write_bytes(b'synthetic visual')
        (root/'prompt.txt').write_text('Only a source and a blank structure.')
        packet = {'source_original_sha256':job['source_sha256'], 'page_count':1,
            'input_hashes':{n:digest(root/n) for n in ('source.pdf', 'source-context.json', 'visual.pdf', 'prompt.txt')}}
        atomic_json(root/'packet.json', packet)
        provider = root/'chatgpt'; provider.mkdir()
        (provider/'response-raw.txt').write_text('Complete original synthetic source-only answer.')
        (provider/'prompt-actual.txt').write_text((root/'prompt.txt').read_text())
        atomic_json(provider/'attempt.json', {'provider':'chatgpt', 'state':'response_saved', 'target_id':'original-target',
            'finished':1, 'send_click_started':True, 'raw_sha256':digest(provider/'response-raw.txt'),
            'inputs':packet['input_hashes'], 'actual_prompt_sha256':digest(provider/'prompt-actual.txt'),
            'conversation_url':'https://chatgpt.com/c/original-synthetic-card'})
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)',
                (job['paper_id'], job['source_sha256'], job['title'], '{}', 'completed', now()))
        return root

    def test_request_retains_card_and_report_and_is_idempotent(self):
        job, path, card = self.card(); folder, result = self.receipt(job, card)
        before = digest(path); raw = digest(folder/'response-raw.txt')
        queued = correction.enqueue_review(self.catalog, job, self.config)
        again = correction.enqueue_review(self.catalog, job, self.config)
        self.assertEqual(queued['id'], again['id']); self.assertEqual(queued['kind'], 'formatting')
        self.assertEqual(queued['state'], 'queued'); self.assertEqual(before, digest(path))
        self.assertEqual(raw, digest(folder/'response-raw.txt'))
        self.assertEqual(queued['queued_at'], queued['fifo_at'])
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM shared_workflow_arrivals WHERE lane='correction' AND job_id=?", (queued['id'],)).fetchone()
        self.assertEqual(row['basis'], 'enqueue')

    def test_independent_pause_does_not_require_cards_or_review_running(self):
        for file in ('web-card-control.json', 'card-review-control.json'):
            atomic_json(self.root/file, {'paused_by_user':True})
        self.assertTrue(correction.enabled(self.config))
        atomic_json(self.root/'card-correction-control.json', {'paused_by_user':True})
        self.assertFalse(correction.enabled(self.config))
        (self.root/'card-correction-control.json').write_text('{')
        self.assertFalse(correction.enabled(self.config))

    def test_apply_whitespace_keeps_science_unverified_and_requeues_new_version(self):
        job, path, card = self.card(); folder, old_score = self.receipt(job, card)
        raw_hash = digest(folder/'response-raw.txt'); old_hash = digest(path)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        correction.process(self.catalog, correction.claim(self.catalog), self.config)
        published = json.loads(path.read_text())
        self.assertEqual(published['figures'][0]['summary'], 'A\ncondition.')
        self.assertFalse(published['meta']['scientific_verified'])
        self.assertFalse(published['meta']['production_contract_complete'])
        self.assertEqual(digest(path.parent/'history'/('correction-'+queued['id'])/'card.json'), old_hash)
        self.assertEqual(digest(folder/'response-raw.txt'), raw_hash)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'applied')
        latest = next(j for j in review.rows(self.catalog) if j['card_sha256'] == digest(path))
        self.assertEqual(latest['state'], 'queued')
        original = next(j for j in review.rows(self.catalog) if j['id'] == job['id'])
        self.assertEqual(json.loads(original['result'])['weighted_score'], old_score['weighted_score'])

    def test_formatting_cannot_change_scientific_text_or_numbers(self):
        job, path, card = self.card(); folder, _ = self.receipt(job, card)
        data = self.feedback(); data['corrections'][0]['after'] = 'A 2 condition.'
        (folder/'response-raw.txt').write_text(json.dumps(data))
        attempt = json.loads((folder/'attempt.json').read_text()); attempt['raw_sha256'] = digest(folder/'response-raw.txt')
        atomic_json(folder/'attempt.json', attempt)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        self.assertEqual(queued['kind'], 'source_rework')
        old_hash = digest(path)
        # No original web-card material exists in this fixture: source-only
        # rework must stop at that guard, never apply the numerical edit locally.
        with self.assertRaises(FileNotFoundError):
            correction.process(self.catalog, queued, self.config)
        self.assertEqual(digest(path), old_hash)

    def test_pause_after_enqueue_preserves_task_and_card(self):
        job, path, card = self.card(); self.receipt(job, card)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        atomic_json(self.root/'card-correction-control.json', {'paused_by_user':True})
        with self.assertRaises(correction.CorrectionPaused):
            correction.process(self.catalog, queued, self.config)
        self.assertEqual(digest(path), job['card_sha256'])
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'queued')

    def test_frozen_report_change_rejects_and_preserves_card(self):
        job, path, card = self.card(); folder, _ = self.receipt(job, card)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        (folder/'response-raw.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, '指纹变化'):
            correction.process(self.catalog, queued, self.config)
        self.assertEqual(digest(path), job['card_sha256'])

    def test_unknown_review_cannot_enqueue_or_send(self):
        job, _, card = self.card(); folder, _ = self.receipt(job, card)
        receipt = json.loads((folder/'attempt.json').read_text()); receipt['state'] = 'needs_inspection'
        atomic_json(folder/'attempt.json', receipt)
        with self.assertRaisesRegex(ValueError, '尚未完整'):
            correction.enqueue_review(self.catalog, job, self.config)
        self.assertEqual(correction.rows(self.catalog), [])

    def test_superseded_card_and_human_decision_are_protected(self):
        job, path, card = self.card(); self.receipt(job, card)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError, '版本变化'):
            correction.process(self.catalog, queued, self.config)
        job2, path2, card2 = self.card('human'); self.receipt(job2, card2)
        self.catalog.event(job2['paper_id'], 'human_decision', {'decision':'keep'})
        human = correction.enqueue_review(self.catalog, job2, self.config)
        self.assertEqual(human['state'], 'needs_user')
        with self.assertRaisesRegex(ValueError, '人工决定'):
            correction.process(self.catalog, human, self.config)
        self.assertEqual(digest(path2), job2['card_sha256'])

    def test_atomic_claim_uses_fifo_and_does_not_double_claim(self):
        first, _, card = self.card('first'); self.receipt(first, card)
        first_c = correction.enqueue_review(self.catalog, first, self.config)
        second, _, card = self.card('second'); self.receipt(second, card)
        second_c = correction.enqueue_review(self.catalog, second, self.config)
        self.assertEqual(correction.claim(self.catalog)['id'], first_c['id'])
        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = list(executor.map(lambda _:correction.claim(self.catalog), range(8)))
        claimed = [job for job in claims if job]
        self.assertEqual([j['id'] for j in claimed], [second_c['id']])

    def test_quote_location_only_keeps_figure_page_and_image(self):
        job, path, card = self.card(); self.packet(job, card, ('Another page.', QUOTE))
        self.original_card_receipt(job, path)
        queued = correction.enqueue_quotes(self.catalog, job, self.config)
        correction.process(self.catalog, queued, self.config)
        corrected = json.loads(path.read_text())['figures'][0]
        self.assertEqual(corrected['source_page'], 1); self.assertEqual(corrected['evidence_id'], 'P001')
        self.assertEqual(corrected['image_path'], 'P001.png'); self.assertEqual(corrected['evidence_source_page'], 2)
        self.assertEqual(corrected['evidence_quote'], QUOTE)
        self.assertEqual(queued['kind'], 'quote_location')

    def test_quote_location_requires_immutable_verified_source_text(self):
        job, path, card = self.card(); folder, _ = self.packet(job, card, ('Another page.', QUOTE))
        self.original_card_receipt(job, path)
        queued = correction.enqueue_quotes(self.catalog, job, self.config)
        atomic_json(folder/'source-text-verified.json', [QUOTE, 'Changed source.'])
        with self.assertRaisesRegex(ValueError, '指纹变化'):
            correction.process(self.catalog, queued, self.config)
        self.assertEqual(digest(path), job['card_sha256'])

    def test_rework_archives_only_complete_original_and_marks_independent_kind(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        root = self.original_card_receipt(job, path)
        original_raw = digest(root/'chatgpt'/'response-raw.txt')
        queued = correction.enqueue_review(self.catalog, job, self.config)
        result = correction.process(self.catalog, queued, self.config)
        self.assertEqual(result['state'], 'ready')
        current = cards.jobs(self.catalog)[0]
        self.assertEqual(current['state'], 'queued'); self.assertEqual(correction.web_job_kind(current), 'correction')
        self.assertEqual(json.loads(current['selection'])['rework']['correction_id'], queued['id'])
        self.assertEqual(digest(path), job['card_sha256'])
        archived = root/'history'/('source-review-'+job['id'])/'chatgpt'/'response-raw.txt'
        self.assertEqual(digest(archived), original_raw)
        self.assertFalse((root/'packet.json').exists())
        self.assertFalse((root/'chatgpt').exists())

    def test_rework_never_resets_unknown_original_send(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        root = self.original_card_receipt(job, path)
        receipt = json.loads((root/'chatgpt'/'attempt.json').read_text()); receipt['state'] = 'needs_inspection'
        atomic_json(root/'chatgpt'/'attempt.json', receipt)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        with self.assertRaises(ValueError):
            correction.process(self.catalog, queued, self.config)
        self.assertEqual(cards.jobs(self.catalog)[0]['state'], 'completed')
        self.assertTrue((root/'chatgpt'/'attempt.json').exists())
        self.assertTrue((root/'packet.json').exists())

    def test_completion_label_without_new_card_does_not_complete_correction(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        correction.process(self.catalog, queued, self.config)
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='completed' WHERE paper_id=?", (job['paper_id'],))
        correction.sync(self.catalog, self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'needs_user')
        self.assertEqual(digest(path), job['card_sha256'])

    def test_web_completion_hook_requires_publication_check(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        correction.process(self.catalog, queued, self.config)
        webjob = cards.jobs(self.catalog)[0]
        correction.mark_web_state(self.catalog, webjob, 'completed')
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'ready')
        correction.mark_web_state(self.catalog, webjob, 'submitted')
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'submitted')

    def test_legacy_rework_adoption_does_not_reset_existing_queue(self):
        job, path, card = self.card(); _, result = self.receipt(job, card, 'rework')
        root = self.original_card_receipt(job, path)
        paper = self.catalog.get(job['paper_id'])
        review.queue_rework(self.catalog, job, self.config, paper, path, result)
        before = cards.jobs(self.catalog)[0]
        report = correction.adopt_legacy(self.catalog, self.config)
        self.assertEqual(report['adopted'], 1); self.assertEqual(report['errors'], [])
        after = cards.jobs(self.catalog)[0]
        self.assertEqual(after['state'], before['state']); self.assertEqual(after['retry_at'], before['retry_at'])
        self.assertEqual(after['attempts'], before['attempts'])
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'ready')
        self.assertEqual(correction.adopt_legacy(self.catalog, self.config)['adopted'], 0)
        self.assertFalse((root/'chatgpt').exists())

    def test_status_is_read_only_and_counts_local_vs_page_tasks(self):
        job, path, card = self.card(); self.receipt(job, card)
        correction.enqueue_review(self.catalog, job, self.config)
        summary = correction.status(self.config)
        self.assertEqual(summary['counts'], {'queued':1}); self.assertEqual(summary['local_pending'], 1)
        self.assertEqual(summary['page_pending'], 0); self.assertIsNone(summary['last_finished_at'])
        self.assertEqual(summary['parallel_jobs'], 4)

    def published_rework(self, job, path, card):
        root = self.root/'web_cards'/job['paper_id']
        packet = json.loads((root/'history'/('source-review-'+job['id'])/'packet.json').read_text())
        atomic_json(root/'packet.json', packet)
        provider = root/'chatgpt'; provider.mkdir(exist_ok=True)
        (provider/'response-raw.txt').write_text('New complete source-only synthetic answer.')
        (provider/'prompt-actual.txt').write_text((root/'prompt.txt').read_text())
        receipt = {'provider':'chatgpt', 'state':'response_saved', 'finished':2, 'target_id':'new-target',
            'raw_sha256':digest(provider/'response-raw.txt'), 'actual_prompt_sha256':digest(provider/'prompt-actual.txt'),
            'inputs':packet['input_hashes'], 'conversation_url':'https://chatgpt.com/c/new-synthetic-card'}
        atomic_json(provider/'attempt.json', receipt)
        webjob = cards.jobs(self.catalog)[0]
        new_card = copy.deepcopy(card); new_card['one_line_summary'] = 'New source-only work synthesis.'
        new_card['meta'].update(raw_sha256=receipt['raw_sha256'], actual_prompt_sha256=receipt['actual_prompt_sha256'],
            conversation_url=receipt['conversation_url'], selection=json.loads(webjob['selection']))
        atomic_json(path, new_card)
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='completed' WHERE paper_id=?", (job['paper_id'],))
        return root, new_card

    def test_proven_completed_rework_is_applied_and_rechecked(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        correction.process(self.catalog, queued, self.config)
        self.published_rework(job, path, card)
        correction.sync(self.catalog, self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'applied')
        self.assertEqual(next(j for j in review.rows(self.catalog) if j['card_sha256'] == digest(path))['state'], 'queued')
        self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])

    def test_versioned_publication_requires_bound_provenance_before_applying(self):
        job,path,card=self.card();self.receipt(job,card,'rework');self.original_card_receipt(job,path)
        queued=correction.enqueue_review(self.catalog,job,self.config)
        correction.process(self.catalog,queued,self.config)
        root,new_card=self.published_rework(job,path,card)
        packet=json.loads((root/'packet.json').read_text())
        publication=path.parent/'publications'/('a'*32);publication.mkdir(parents=True)
        (publication/'source.pdf').write_bytes(path.with_name('source.pdf').read_bytes())
        version=publication/'card.json'
        new_card['meta'].update(publication_id=publication.name,input_hashes=packet['input_hashes'])
        atomic_json(version,new_card)
        provenance={'publication_id':publication.name,'card_sha256':digest(version),'packet':str(root/'packet.json'),
                    'attempt':json.loads((root/'chatgpt'/'attempt.json').read_text())}
        provenance['card_sha256']='tampered';atomic_json(publication/'web-provenance.json',provenance)
        self.catalog.update(job['paper_id'],card_path=str(version))
        correction.sync(self.catalog,self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'needs_user')
        provenance['card_sha256']=digest(version);atomic_json(publication/'web-provenance.json',provenance)
        correction.sync(self.catalog,self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'applied')
        self.assertTrue(any(j['card_sha256']==digest(version) and j['state']=='queued' for j in review.rows(self.catalog)))

    def test_new_card_with_unbound_prompt_is_not_applied(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        queued = correction.enqueue_review(self.catalog, job, self.config)
        correction.process(self.catalog, queued, self.config)
        root, new_card = self.published_rework(job, path, card)
        (root/'chatgpt'/'prompt-actual.txt').write_text('A changed scientific request.')
        correction.sync(self.catalog, self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'needs_user')
        self.assertFalse(any(j['card_sha256'] == digest(path) for j in review.rows(self.catalog)))

    def test_completed_legacy_rework_is_adopted_without_changing_card_or_sending(self):
        job, path, card = self.card(); _, result = self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        review.queue_rework(self.catalog, job, self.config, self.catalog.get(job['paper_id']), path, result)
        self.published_rework(job, path, card)
        before = digest(path)
        adopted = correction.adopt_legacy(self.catalog, self.config)
        self.assertEqual(adopted['adopted'], 1)
        correction.sync(self.catalog, self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'applied')
        self.assertEqual(digest(path), before)
        self.assertEqual(cards.jobs(self.catalog)[0]['state'], 'completed')

    def test_legacy_queued_with_click_started_is_protected_not_ready(self):
        job, path, card = self.card(); _, result = self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        review.queue_rework(self.catalog, job, self.config, self.catalog.get(job['paper_id']), path, result)
        provider = self.root/'web_cards'/job['paper_id']/'chatgpt'; provider.mkdir()
        receipt = {'state':'not_sent', 'send_click_started':True, 'target_id':'uncertain'}
        atomic_json(provider/'attempt.json', receipt)
        adopted = correction.adopt_legacy(self.catalog, self.config)
        self.assertEqual(adopted['adopted'], 1)
        self.assertEqual(correction.rows(self.catalog)[0]['state'], 'needs_user')
        self.assertEqual(json.loads((provider/'attempt.json').read_text()), receipt)
        self.assertEqual(cards.jobs(self.catalog)[0]['state'], 'queued')

    def test_rework_limit_preserves_original_card_and_ledger(self):
        job, path, card = self.card(); self.receipt(job, card, 'rework')
        root = self.original_card_receipt(job, path)
        for number in (1, 2):
            self.catalog.event(job['paper_id'], 'card_review_rework', {'number':number})
        queued = correction.enqueue_review(self.catalog, job, self.config)
        result = correction.process(self.catalog, queued, self.config)
        self.assertEqual(result['state'], 'needs_user')
        self.assertEqual(cards.jobs(self.catalog)[0]['state'], 'completed')
        self.assertEqual(digest(path), job['card_sha256'])
        self.assertTrue((root/'chatgpt'/'attempt.json').exists())

    def test_failed_legacy_adoption_preserves_old_work_without_card_lane_fallback(self):
        from browser import web_page_queue
        from browser.shared_workflow_queue import heads
        job, path, card = self.card(); folder, result = self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        review.queue_rework(self.catalog, job, self.config, self.catalog.get(job['paper_id']), path, result)
        old_webjob = cards.jobs(self.catalog)[0]
        (folder/'feedback.json').write_text('An altered historical review report')
        report = correction.adopt_legacy(self.catalog, self.config)
        self.assertEqual(report['adopted'], 0); self.assertEqual(len(report['errors']), 1)
        current = cards.jobs(self.catalog)[0]
        self.assertEqual(current, old_webjob)
        self.assertEqual(correction.rows(self.catalog), [])
        self.assertEqual(correction.web_job_kind(current), 'correction')
        self.assertFalse(correction.allows_web_job(self.config, current))
        web_page_queue.install(self.catalog)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,?,?)',
                       (job['paper_id'], 'original-target', 'ready', 1))
            db.execute('UPDATE web_card_jobs SET retry_at=0 WHERE paper_id=?', (job['paper_id'],))
        pending = heads(self.catalog, self.config)
        self.assertEqual(pending['cards'], []); self.assertEqual(pending['correction'], [])
        self.assertEqual(digest(path), job['card_sha256'])

    def test_unbound_submitted_rework_is_labelled_before_first_observation_without_mutating_receipt(self):
        job, path, card=self.card();folder,result=self.receipt(job,card,'rework')
        self.original_card_receipt(job,path)
        review.queue_rework(self.catalog,job,self.config,self.catalog.get(job['paper_id']),path,result)
        (folder/'feedback.json').write_text('An incomplete legacy review report')
        root=self.root/'web_cards'/job['paper_id'];provider=root/'chatgpt';provider.mkdir()
        receipt={'state':'submitted','target_id':'original-target','send_click_started':True,
                 'conversation_url':'https://chatgpt.com/c/original-correction-generation'}
        atomic_json(provider/'attempt.json',receipt)
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='submitted' WHERE paper_id=?",(job['paper_id'],))
        self.assertEqual(correction.adopt_legacy(self.catalog,self.config)['adopted'],0)
        entries={'original-target':{'state':'busy','kind':'cards','paper_id':job['paper_id'],
                                    'conversation_url':receipt['conversation_url']}}
        original_entries=copy.deepcopy(entries)
        correction.sync(self.catalog,self.config,entries)
        self.assertEqual(entries['original-target']['kind'],'correction')
        self.assertNotIn('correction_id',entries['original-target'])
        self.assertEqual(json.loads((provider/'attempt.json').read_text()),receipt)
        self.assertEqual(correction.rows(self.catalog),[])
        self.assertFalse(correction.allows_web_job(self.config,cards.jobs(self.catalog)[0]))
        for drift in ({'review_id':'another-active-review'}, {'active_paper_id':'another-paper'},
                      {'conversation_url':'https://chatgpt.com/c/another-conversation'}):
            protected=copy.deepcopy(original_entries);protected['original-target'].update(drift)
            correction.sync(self.catalog,self.config,protected)
            self.assertEqual(protected['original-target']['kind'],'cards')
        receipt['conversation_url']='https://chatgpt.com/c/local-chatgpt-provisional'
        atomic_json(provider/'attempt.json',receipt)
        provisional=copy.deepcopy(original_entries);provisional['original-target']['conversation_url']=receipt['conversation_url']
        correction.sync(self.catalog,self.config,provisional)
        self.assertEqual(provisional['original-target']['kind'],'cards')

    def test_pause_after_candidate_preserves_queued_intent_and_resume_applies_once(self):
        job,path,card=self.card();self.receipt(job,card)
        queued=correction.enqueue_review(self.catalog,job,self.config)
        producer=correction.CorrectionProducer(self.config)
        claimed=correction.claim(self.catalog)
        real_atomic=correction.atomic_json
        def pause_after_candidate(destination,value,*args,**kwargs):
            real_atomic(destination,value,*args,**kwargs)
            if Path(destination).name=='card-candidate.json':
                real_atomic(self.root/'card-correction-control.json',{'paused_by_user':True})
        with patch('correction.card_correction_queue.atomic_json',side_effect=pause_after_candidate):
            producer.work(claimed)
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'queued')
        self.assertEqual(digest(path),job['card_sha256'])
        self.assertTrue((Path(queued['folder'])/'card-candidate.json').is_file())
        self.assertEqual(len(review.rows(self.catalog)),1)
        atomic_json(self.root/'card-correction-control.json',{'paused_by_user':False})
        producer.work(correction.claim(self.catalog))
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'applied')
        self.assertEqual(json.loads(path.read_text())['figures'][0]['summary'],'A\ncondition.')
        self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='card_correction_applied'").fetchone()[0],1)
        self.assertEqual(next(j for j in review.rows(self.catalog) if j['card_sha256']==digest(path))['state'],'queued')

    def test_human_change_together_with_pause_remains_needs_user(self):
        job,path,card=self.card();self.receipt(job,card)
        correction.enqueue_review(self.catalog,job,self.config)
        producer=correction.CorrectionProducer(self.config);claimed=correction.claim(self.catalog)
        real_atomic=correction.atomic_json
        def protect_and_pause(destination,value,*args,**kwargs):
            real_atomic(destination,value,*args,**kwargs)
            if Path(destination).name=='card-candidate.json':
                self.catalog.event(job['paper_id'],'human_decision',{'decision':'keep'})
                real_atomic(self.root/'card-correction-control.json',{'paused_by_user':True})
        with patch('correction.card_correction_queue.atomic_json',side_effect=protect_and_pause):
            producer.work(claimed)
        row=correction.rows(self.catalog)[0]
        self.assertEqual(row['state'],'needs_user');self.assertIn('人工保护',row['error'])
        self.assertEqual(digest(path),job['card_sha256'])

    def test_changed_source_together_with_pause_remains_needs_user(self):
        job,path,card=self.card();self.receipt(job,card)
        correction.enqueue_review(self.catalog,job,self.config)
        producer=correction.CorrectionProducer(self.config);claimed=correction.claim(self.catalog)
        source=Path(self.catalog.get(job['paper_id'])['asset_path'])
        source.write_bytes(b'A changed original source')
        atomic_json(self.root/'card-correction-control.json',{'paused_by_user':True})
        producer.work(claimed)
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'needs_user')
        self.assertEqual(digest(path),job['card_sha256'])

    def test_source_rework_pause_at_lock_preserves_original_attempt_until_resume(self):
        job,path,card=self.card();self.receipt(job,card,'rework')
        root=self.original_card_receipt(job,path)
        correction.enqueue_review(self.catalog,job,self.config)
        producer=correction.CorrectionProducer(self.config);claimed=correction.claim(self.catalog)
        original_current=review.current;checks=0
        def pause_at_lock(*args,**kwargs):
            nonlocal checks
            result=original_current(*args,**kwargs);checks+=1
            if checks==2:
                atomic_json(self.root/'card-correction-control.json',{'paused_by_user':True})
            return result
        with patch('review.card_review_queue.current',side_effect=pause_at_lock), \
             patch('review.card_review_queue.queue_rework',wraps=review.queue_rework) as reset:
            producer.work(claimed)
            reset.assert_not_called()
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'queued')
        self.assertTrue((root/'chatgpt'/'attempt.json').exists())
        self.assertEqual(cards.jobs(self.catalog)[0]['state'],'completed')
        atomic_json(self.root/'card-correction-control.json',{'paused_by_user':False})
        producer.work(correction.claim(self.catalog))
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'ready')
        self.assertEqual(cards.jobs(self.catalog)[0]['state'],'queued')
        self.assertEqual(digest(path),job['card_sha256'])


if __name__ == '__main__':
    unittest.main()
