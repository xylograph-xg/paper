import json,tempfile,unittest,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from review import web_feedback as w,review_cycle as cycle,card_review_queue as q
from core.catalog import Catalog

class AuditRegressions(unittest.TestCase):
    def test_all_frozen_inputs_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'mixed';folder.mkdir()
            for name in ('paper-review.pdf','card-review.json','prompt.txt'):(folder/name).write_text(name)
            sample={'kind':'mixed','packet_files':['paper-review.pdf','card-review.json'],
                    'review_pdf_sha256':w.digest(folder/'paper-review.pdf'),
                    'input_hashes':{n:w.digest(folder/n) for n in ('paper-review.pdf','card-review.json','prompt.txt')}}
            self.assertEqual(len(w.packet_files(root,sample)),2)
            for name in sample['input_hashes']:
                original=(folder/name).read_bytes();(folder/name).write_text('changed')
                with self.assertRaises(ValueError):w.packet_files(root,sample)
                (folder/name).write_bytes(original)
            with self.assertRaises(ValueError):w.packet_files(root,{**sample,'kind':'../outside'})

    def test_injected_factory_does_not_bypass_pause(self):
        factory=lambda: self.fail('factory must not be opened')
        with patch('core.api.catalog__load_config',return_value={'catalog_path':'/tmp/audit-paused/catalog.sqlite3'}):
            with self.assertRaises(PermissionError):w.run_reviews(Path('/tmp'),factory=factory)

    def test_incomplete_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'response-raw.txt').write_text('{}')
            for kind in ('material','incomplete','ambiguous','unsubstantiated'):
                with patch('review.card_review_repair.collected'),patch.object(q,'parse_review',return_value=({}, {'action':'needs_user','failure_kind':kind})):
                    with self.assertRaises(ValueError):cycle.completed_failure(None,{'folder':d})

    def test_atomic_claim_competing_directories(self):
        from concurrent.futures import ThreadPoolExecutor
        from review.review_ledger import reserve,install
        with tempfile.TemporaryDirectory() as d:
            c=Catalog(Path(d)/'catalog.sqlite3');install(c)
            with ThreadPoolExecutor(2) as ex:
                results=list(ex.map(lambda r:reserve(c,'paper','card',r),('one','two')))
            self.assertEqual(sum(results),1)

    def test_publication_replays_after_file_write_database_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c=Catalog(root/'catalog.sqlite3');q.install(c)
            path=root/'card.json';path.write_text('{}');before=w.digest(path)
            pid=c.upsert({'title':'Version-bound publication recovery'})
            c.update(pid,asset_hash='source',card_path=str(path))
            report=root/'feedback.json';report.write_text('{}')
            candidate={'meta':{'source_review':{'report_sha256':w.digest(report)}}}
            w.save_json(root/'card-candidate.json',candidate)
            job={'id':'old','paper_id':pid,'card_sha256':before,'source_sha256':'source',
                 'folder':str(root),'priority':None,'novelty':None,'title':'test'}
            with c.connect() as db:
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) VALUES('old',?,?,'source','test','applying',?,'now')",(pid,before,str(root)))
            intent={'job':job,'path':str(path),'before':before,'after':w.digest(root/'card-candidate.json'),'result':{'pass':True}}
            with patch.object(q,'enabled',return_value=True),patch.object(q,'current',return_value=({'id':pid},path,{})),patch.object(q,'protected',return_value=False),patch.object(q,'check_packet',return_value={}):
                with patch.object(q,'replacement',side_effect=RuntimeError('injected')):
                    with self.assertRaises(RuntimeError):q.finish_publication(c,intent,root,{})
                self.assertEqual(w.digest(path),intent['after'])
                q.finish_publication(c,intent,root,{})
                q.update(c,'old','needs_user','simulate journal write failure after DB commit')
                q.finish_publication(c,intent,root,{})
            with c.connect() as db:
                self.assertEqual(db.execute("SELECT state FROM card_review_jobs WHERE id='old'").fetchone()[0],'passed')
                self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='card_source_review'").fetchone()[0],1)

    def test_reset_cleanup_failure_keeps_claim_blocked_and_replays(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c=Catalog(root/'catalog.sqlite3')
            from cards.api import web_card_queue__install
            web_card_queue__install(c)
            with c.connect() as db:
                db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,state,selection,updated) VALUES('paper','source','test','review_reset_pending','{}','now')")
            work=root/'web';history=work/'history'/'reset';active=work/'attempt-1'
            active.mkdir(parents=True);(active/'attempt.json').write_text('receipt')
            (history/'attempt-1').mkdir(parents=True);(history/'attempt-1'/'attempt.json').write_text('receipt')
            (work/'packet.json').write_text('packet');(history/'packet.json').write_text('packet')
            with patch.object(q.shutil,'rmtree',side_effect=OSError('injected cleanup')):
                with self.assertRaises(OSError):q.finish_rework_reset(c,'paper',work,history)
            with c.connect() as db:self.assertEqual(db.execute("SELECT state FROM web_card_jobs WHERE paper_id='paper'").fetchone()[0],'review_reset_pending')
            q.finish_rework_reset(c,'paper',work,history);q.finish_rework_reset(c,'paper',work,history)
            self.assertTrue((history/'attempt-1'/'attempt.json').exists())
            with c.connect() as db:self.assertEqual(db.execute("SELECT state FROM web_card_jobs WHERE paper_id='paper'").fetchone()[0],'queued')

    def test_supplement_quote_uses_separate_page_domain(self):
        from review.tests.test_card_review_queue import ReviewQueue
        fixture=ReviewQueue();fixture.setUp()
        try:
            job,path,card=fixture.card();folder,packet=fixture.packet(job,card)
            quote='This supplemental observation is uniquely supported by the control.'
            w.save_json(folder/'supplement-context.json',{'source_text':[{'source_page':1,'text':quote}]})
            packet['input_hashes']['supplement-context.json']=w.digest(folder/'supplement-context.json')
            packet['supplement']={'page_count':1};w.save_json(folder/'packet.json',packet)
            feedback=fixture.feedback();feedback.update(verdict='revise',supplement_pages_reviewed=[1])
            feedback['issues']=[{'severity':'major','artifact':'Fig. 1','finding':'wrong claim','evidence':quote,
                                 'source_page':1,'source_quote':quote,'source_document':'supplement'}]
            self.assertEqual(q.parse_review(json.dumps(feedback),folder)[1]['action'],'rework')
            feedback['issues'][0]['source_document']='main'
            self.assertEqual(q.parse_review(json.dumps(feedback),folder)[1]['failure_kind'],'unsubstantiated')
        finally:fixture.doCleanups()

    def test_changed_source_keeps_history_but_never_current_pass(self):
        from review.review_protection import protection
        from review.card_evaluation import RUBRIC,assess_feedback
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);card=root/'card';card.mkdir();(card/'card.json').write_text('{}');(card/'source.pdf').write_text('new source')
            run=root/'reviews'/'one';review=run/'mixed';review.mkdir(parents=True)
            feedback={'sample_kind':'mixed','scores':{k:9 for k in RUBRIC},'missing_inputs':[],'issues':[],'verdict':'pass'}
            w.save_json(review/'feedback.json',feedback);(review/'feedback-raw.txt').write_text(json.dumps(feedback))
            w.save_json(review/'web-attempt.json',{'state':'feedback_received','feedback_sha256':w.digest(review/'feedback.json'),
                       'raw_sha256':w.digest(review/'feedback-raw.txt'),'assessment':assess_feedback(feedback,'mixed')})
            w.save_json(run/'run.json',{'samples':[{'kind':'mixed','card_sha256':w.digest(card/'card.json'),'source_sha256':'old source'}]})
            result=protection(card,root/'reviews')
            self.assertTrue(result['source_changed']);self.assertFalse(result['pass']);self.assertEqual(result['weighted_score'],90)


    def test_two_processes_compete_for_one_version(self):
        from review.review_ledger import install
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'catalog.sqlite3';install(Catalog(db))
            script="from core.catalog import Catalog; from review.review_ledger import reserve; import sys; print(int(reserve(Catalog(sys.argv[1]),'paper','card',sys.argv[2])))"
            workers=[subprocess.Popen([sys.executable,'-c',script,str(db),run],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for run in ('one','two')]
            results=[]
            try:
                for worker in workers:
                    output,error=worker.communicate(timeout=15)
                    self.assertEqual(worker.returncode,0,error);results.append(int(output.strip()))
            finally:
                for worker in workers:
                    if worker.poll() is None:worker.kill();worker.wait()
            self.assertEqual(sum(results),1)
