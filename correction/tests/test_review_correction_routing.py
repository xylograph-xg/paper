"""Collected review suggestions must be routed before a local publisher claims them."""
import json
from unittest.mock import patch
import unittest
from . import test_card_correction_queue as fixtures
from correction import card_correction_queue as q
from correction.recover_review_corrections import run_once
from review import card_review_queue as review
from cards.web_card_inputs import digest
from core.services import atomic_json


class CorrectionRouting(unittest.TestCase):
    setUp = fixtures.CorrectionQueue.setUp
    card = fixtures.CorrectionQueue.card
    packet = fixtures.CorrectionQueue.packet
    feedback = fixtures.CorrectionQueue.feedback
    receipt = fixtures.CorrectionQueue.receipt
    def obsolete_formatting(self):
        job,path,card=self.card()
        folder,_=self.receipt(job,card)
        data=json.loads((folder/'feedback.json').read_text())
        data['corrections'][0].update(before='A condition.',after='A scientific change.')
        (folder/'response-raw.txt').write_text(json.dumps(data))
        attempt=json.loads((folder/'attempt.json').read_text());attempt['raw_sha256']=digest(folder/'response-raw.txt')
        atomic_json(folder/'attempt.json',attempt)
        parsed,assessment,evidence=q._collected_review(self.catalog,job)
        old=q._enqueue(self.catalog,job,'formatting',{'feedback':parsed,'assessment':{**assessment,'action':'correct'},'evidence':evidence},state='needs_user',error='修正原字符串不一致')
        self.config['card_correction']['priority_passed_first']=True
        return job,path,old
    def test_scientific_change_routes_to_source_rework_without_touching_original_or_sending(self):
        job,path,old=self.obsolete_formatting();before=path.read_bytes();raw=(__import__('core.paths',fromlist=['WorkspacePath']).WorkspacePath(job['folder'])/'response-raw.txt').read_bytes()
        report=run_once(self.catalog,self.config)
        self.assertEqual(len(report['advanced']),1);self.assertEqual(report['pending'],[])
        rows=q.rows(self.catalog);self.assertEqual({r['kind']:r['state'] for r in rows},{'formatting':'superseded','source_rework':'queued'})
        self.assertEqual(path.read_bytes(),before);self.assertEqual((__import__('core.paths',fromlist=['WorkspacePath']).WorkspacePath(job['folder'])/'response-raw.txt').read_bytes(),raw)
        self.assertEqual(run_once(self.catalog,self.config)['advanced'],[])
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM web_card_jobs').fetchone()[0],0)
    def test_pause_and_changed_receipt_cannot_route(self):
        job,path,old=self.obsolete_formatting()
        self.config['card_correction']['enabled']=False
        self.assertEqual(run_once(self.catalog,self.config)['advanced'],[])
        self.config['card_correction']['enabled']=True
        from core.paths import WorkspacePath
        (WorkspacePath(job['folder'])/'response-raw.txt').write_text('changed')
        report=run_once(self.catalog,self.config)
        self.assertEqual(report['advanced'],[]);self.assertTrue(report['pending'])
        self.assertEqual(len(q.rows(self.catalog)),1)
    def test_valid_whitespace_stays_local_but_unmatched_or_scientific_patches_never_do(self):
        job,path,card=self.card();folder,_=self.receipt(job,card)
        data,result=review.parse_review((folder/'response-raw.txt').read_text(),folder)
        self.assertEqual(result['action'],'correct')
        for field,before,after in [('figures.0.summary','A condition.','A scientific change.'),('intro_summary','i','changed'),('figures.0.summary','partial','partial\n')]:
            data['corrections'][0].update(path=field,before=before,after=after)
            _,result=review.parse_review(json.dumps(data),folder)
            self.assertEqual(result['action'],'rework')
    def test_new_local_contract_rejection_resumes_only_without_its_own_transport_ledger(self):
        job,path,old=self.obsolete_formatting();first=run_once(self.catalog,self.config)
        cid=first['advanced'][0]['successor_correction_id']
        q.update(self.catalog,cid,'needs_user','重大问题原核验报告变化')
        report=run_once(self.catalog,self.config)
        self.assertEqual(len(report['advanced']),1)
        self.assertEqual(next(r for r in q.rows(self.catalog) if r['id']==cid)['state'],'queued')
        q.update(self.catalog,cid,'needs_user','重大问题原核验报告变化')
        from core.paths import WorkspacePath
        target=self.catalog.path.parent/'web_cards'/job['paper_id']/'synthetic';target.mkdir(parents=True)
        atomic_json(target/'attempt.json',{'correction_id':cid,'state':'needs_inspection'})
        report=run_once(self.catalog,self.config)
        self.assertEqual(report['advanced'],[])
        self.assertEqual(next(r for r in q.rows(self.catalog) if r['id']==cid)['state'],'needs_user')
    def test_config_mismatch_failed_task_recovers_without_successor_marker(self):
        job,path,old=self.obsolete_formatting();first=run_once(self.catalog,self.config)
        cid=first['advanced'][0]['successor_correction_id']
        q.update(self.catalog,cid,'needs_user','重大问题原核验报告变化')
        with self.catalog.connect() as db:
            db.execute("UPDATE card_correction_jobs SET state='failed',error='自动终止：重大问题原核验报告变化' WHERE id=?",(cid,))
        from pathlib import Path
        (Path(old['folder'])/'routing-resolution.json').unlink()
        report=run_once(self.catalog,self.config)
        self.assertEqual([r['id'] for r in report['advanced']],[cid])
        fresh=next(r for r in q.rows(self.catalog) if r['id']==cid)
        self.assertEqual(fresh['state'],'queued')
        self.assertTrue((Path(fresh['folder'])/'config-routing-recovery.json').exists())
        self.assertEqual(run_once(self.catalog,self.config)['advanced'],[])

    def test_registered_versioned_publication_is_allowed_but_unregistered_or_changed_inputs_block(self):
        job,path,card=self.card();publication=path.parent/'publications'/'synthetic-publication';publication.mkdir(parents=True)
        card['meta'].update(publication_id=publication.name,input_hashes={'source.pdf':digest(path.with_name('source.pdf'))})
        import shutil
        shutil.copy2(path.with_name('source.pdf'),publication/'source.pdf');atomic_json(publication/'card.json',card)
        self.catalog.update(job['paper_id'],card_path=str(publication/'card.json'))
        provenance={'publication_id':publication.name,'attempt':{'inputs':card['meta']['input_hashes'],'state':'response_saved','raw_sha256':'synthetic-raw','actual_prompt_sha256':'synthetic-prompt','conversation_url':'https://chatgpt.com/c/synthetic-publication'}}
        atomic_json(publication/'web-provenance.json',provenance)
        newer={**job,'card_sha256':digest(publication/'card.json')}
        with self.assertRaisesRegex(ValueError,'发布'):review.current(self.catalog,newer,self.config)
        self.catalog.event(job['paper_id'],'web_card_generated',{'card_path':str(publication/'card.json')})
        self.assertEqual(review.current(self.catalog,newer,self.config)[1],publication/'card.json')
        provenance['attempt']['inputs']={};atomic_json(publication/'web-provenance.json',provenance)
        with self.assertRaisesRegex(ValueError,'绑定'):review.current(self.catalog,newer,self.config)
