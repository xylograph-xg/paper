import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from review import card_review_queue as queue, production_contract as contract
from review.tests import test_card_review_queue as fixtures
from cards.web_card_inputs import SCHEMA, digest
from core.services import atomic_json


class ProductionAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReviewQueue('test_priorities_and_idempotent_versions_with_missing_scores_last')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        _, self.path, self.card = f.card()
        self.card['info'] = {name:'Source evidence' for name in SCHEMA['info']}
        self.image = self.path.with_name('P001.png');self.image.write_bytes(b'real frozen image identity')
        self.card['figures'][0].update(number='1', caption='Caption', figure_info='Original figure',
            one_line='Observation', detail='Detail', result='Result', image_path=str(self.image))
        self.card['meta'].update(card_contract_version='card-contract-v2',structural_complete=True)
        atomic_json(self.path,self.card);queue.enqueue(f.catalog,f.config)
        self.job=next(j for j in queue.rows(f.catalog) if j['card_sha256']==digest(self.path))
        self.folder,self.packet=f.packet(self.job,self.card)
        # The fixture's simple bundle stands for already frozen transport bytes;
        # all original/review/image transforms and receipts are checked for real.
        self.packet.update(job_id=self.job['id'],card_sha256=self.job['card_sha256'],
            source_original_sha256=self.job['source_sha256'],review_images_version=1,review_materials_version=2)
        (self.folder/'source.pdf').write_bytes(self.path.with_name('source.pdf').read_bytes())
        sent={k:copy.deepcopy(v) for k,v in self.card.items() if k not in ('meta','paper_evaluation')}
        sent['figures'][0].update(image_path='card-images.pdf#page=1',
            review_image={'file':'card-images.pdf','page':1,'sha256':digest(self.image)})
        atomic_json(self.folder/'card-review.json',sent)
        atomic_json(self.folder/'card-image-manifest.json',{'images':[{'path':str(self.image),'page':1,'sha256':digest(self.image)}]})
        for name in ('source.pdf','card-review.json','card-image-manifest.json'):
            self.packet['input_hashes'][name]=digest(self.folder/name)
        # finished_response requires the actual, unwrapped prompt identity here.
        (self.folder/'prompt-actual.txt').write_bytes((self.folder/'prompt.txt').read_bytes())
        self.packet['actual_prompt_sha256']=digest(self.folder/'prompt-actual.txt')
        atomic_json(self.folder/'packet.json',self.packet)
        f.receipt(self.folder,self.packet,f.feedback())
        self.data,self.assessment=queue.parse_review((self.folder/'response-raw.txt').read_text(),self.folder)
        atomic_json(self.folder/'feedback.json',self.data)

    def evaluate(self):
        return contract.evaluate(self.card,self.path,self.job,self.folder,self.assessment)

    def test_real_complete_contract_and_scientific_pass_are_both_required(self):
        self.assertTrue(self.evaluate()['complete'])
        for field,value in [('verdict','revise'),('pass',False),('full_source_checked',False),
                            ('weighted_score',float('nan')),('missing_inputs',['source.pdf']),
                            ('issue_counts',{'major':1,'critical':0})]:
            with self.subTest(field=field):
                assessment={**self.assessment,field:value}
                result=contract.evaluate(self.card,self.path,self.job,self.folder,assessment)
                self.assertFalse(result['complete']);self.assertTrue(result['blockers'])

    def test_publication_sets_true_only_after_independent_acceptance(self):
        before=self.path.read_bytes();queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        result=json.loads(self.path.read_text())
        self.assertTrue(result['meta']['production_contract_complete'])
        self.assertTrue(result['meta']['scientific_verified'])
        self.assertEqual({k:v for k,v in result.items() if k!='meta'},
                         {k:v for k,v in self.card.items() if k!='meta'})
        self.assertEqual((self.path.parent/'history'/('source-review-'+self.job['id'])/'card.json').read_bytes(),before)

    def test_changed_image_and_unrecognized_structure_never_become_complete(self):
        self.image.write_bytes(b'changed')
        self.assertFalse(self.evaluate()['complete'])
        self.card['meta']['card_contract_version']='legacy'
        self.assertIn('结构合同',self.evaluate()['blockers'][0])

    def test_transformation_cannot_hide_a_scientific_edit(self):
        sent=json.loads((self.folder/'card-review.json').read_text());sent['figures'][0]['summary']='Different scientific result'
        atomic_json(self.folder/'card-review.json',sent)
        self.packet['input_hashes']['card-review.json']=digest(self.folder/'card-review.json')
        atomic_json(self.folder/'packet.json',self.packet)
        result=self.evaluate();self.assertFalse(result['complete'])
        self.assertIn('逐项转换',result['blockers'][0])

    def test_resume_existing_pass_preserves_scientific_report_and_original_intent(self):
        # Reproduce a card published before this acceptance exit existed.
        with patch.object(contract,'evaluate',return_value={'version':contract.VERSION,'complete':False,'blockers':['legacy exit']}):
            queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        reports={n:(self.folder/n).read_bytes() for n in ('response-raw.txt','feedback.json','assessment.json','publication-intent.json')}
        result=contract.reconcile(self.fixture.catalog,self.fixture.config)
        self.assertEqual(result['accepted'],[self.job['paper_id']],result)
        self.assertTrue(json.loads(self.path.read_text())['meta']['production_contract_complete'])
        self.assertEqual(reports,{n:(self.folder/n).read_bytes() for n in reports})
        self.assertFalse(contract.reconcile(self.fixture.catalog,self.fixture.config)['accepted'])

    def test_paused_reconciliation_never_touches_card_or_pause_bytes(self):
        p=self.fixture.root/'card-review-control.json';p.write_text('{"paused_by_user":true}')
        before=self.path.read_bytes();pause=p.read_bytes()
        self.assertEqual(contract.reconcile(self.fixture.catalog,self.fixture.config)['state'],'paused')
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(p.read_bytes(),pause)

    def test_legacy_pass_diagnostics_do_not_block_exact_production_acceptance(self):
        with patch.object(contract,'evaluate',return_value={'version':contract.VERSION,'complete':False,'blockers':['old exit']}):
            queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        reports={name:(self.folder/name).read_bytes() for name in ('feedback.json','assessment.json','publication-intent.json')}
        current=json.loads(reports['assessment.json'])
        saved={key:value for key,value in current.items() if key not in ('coverage_limitations','raw_weighted_score')}
        saved['failure_kind']='unsubstantiated'
        self.assertTrue(contract.same_scientific_pass(saved,current))
        for change in ({'weighted_score':85}, {'issue_counts':{'major':1}}, {'missing_inputs':['source.pdf']},
                       {'coverage_limitations':['SI']}, {'failure_kind':'scientific'}, {'raw_weighted_score':85}):
            self.assertFalse(contract.same_scientific_pass({**saved,**change},current))
        encoded=json.dumps(saved)
        with self.fixture.catalog.connect() as db:
            db.execute('UPDATE card_review_jobs SET result=? WHERE id=?',(encoded,self.job['id']))
        outcome=contract.reconcile(self.fixture.catalog,self.fixture.config)
        self.assertEqual(outcome['accepted'],[self.job['paper_id']],outcome)
        self.assertEqual(reports,{name:(self.folder/name).read_bytes() for name in reports})
        with self.fixture.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT result FROM card_review_jobs WHERE id=?',(self.job['id'],)).fetchone()[0],encoded)

    def test_acceptance_reconciles_crash_after_card_write_before_alias_commit(self):
        with patch.object(contract,'evaluate',return_value={'version':contract.VERSION,'complete':False,'blockers':['old exit']}):
            queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        with patch.object(queue,'replacement',side_effect=OSError('interrupted alias publication')):
            first=contract.reconcile(self.fixture.catalog,self.fixture.config)
        self.assertTrue(first['blocked'])
        self.assertTrue(json.loads(self.path.read_text())['meta']['production_contract_complete'])
        second=contract.reconcile(self.fixture.catalog,self.fixture.config)
        self.assertEqual(second['accepted'],[self.job['paper_id']],second)
        self.assertFalse(contract.reconcile(self.fixture.catalog,self.fixture.config)['accepted'])

    def test_catalog_pointer_change_after_preflight_preserves_both_versions(self):
        before=self.path.read_bytes()
        with patch.object(queue,'finish_publication',side_effect=RuntimeError('pause at frozen intent')):
            with self.assertRaises(RuntimeError):queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        intent=json.loads((self.folder/'publication-intent.json').read_text())
        original_current=queue.current
        successor=self.path.with_name('successor.json');successor.write_bytes(before)
        def changed(*args):
            result=original_current(*args)
            self.fixture.catalog.update(self.job['paper_id'],card_path=str(successor))
            return result
        with patch.object(queue,'current',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'正式指针'):
                queue.finish_publication(self.fixture.catalog,intent,self.folder,self.fixture.config)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(successor.read_bytes(),before)

    def test_readonly_legacy_pointer_resolution_does_not_rewrite_catalog_pointer(self):
        self.fixture.catalog.update(self.job['paper_id'],card_path='unchanged-legacy-pointer')
        original_path=queue.Path
        def resolve(value):
            return self.path if value=='unchanged-legacy-pointer' else original_path(value)
        with patch.object(queue,'Path',side_effect=resolve):
            queue.apply_result(self.fixture.catalog,self.job,self.fixture.config)
        self.assertTrue(json.loads(self.path.read_text())['meta']['production_contract_complete'])
        self.assertEqual(self.fixture.catalog.get(self.job['paper_id'])['card_path'],'unchanged-legacy-pointer')

