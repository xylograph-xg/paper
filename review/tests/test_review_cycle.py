import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog
from review.card_review_queue import install
from correction.card_correction_queue import install as corrections
from review.review_cycle import run_once

class Cycle(unittest.TestCase):
    def test_blocked_scientific_recovery_never_bounces_terminal_state(self):
        from core.automatic_issue_handler import normalize_needs_user
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir();(root/'config').mkdir()
            (root/'config/review-cycle-policy.json').write_text('{"enabled":true}')
            cat=Catalog(root/'data/catalog.sqlite3');install(cat);corrections(cat)
            pid=cat.upsert({'title':'synthetic','doi':'10.9999/stable-failure'})
            with cat.connect() as db:
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,error,updated) VALUES('r',?,'card','source','synthetic','failed',?,?,'自动终止：原原因','original')",
                           (pid,str(root/'review'),json.dumps({'failure_kind':'scientific'})))
                before=dict(db.execute("SELECT * FROM card_review_jobs WHERE id='r'").fetchone())
            config={'catalog_path':str(cat.path),'review_standard':{'no_user_state':True}}
            with patch('review.card_review_queue.enabled',return_value=True),patch('review.card_review_queue.current',return_value=({'id':pid},root/'card',{})),patch('review.card_review_queue.protected',return_value=False),patch('review.review_cycle.completed_failure',return_value={'action':'rework','failure_kind':'scientific'}),patch('review.card_review_repair.repair',side_effect=ValueError('unchanged local preparation failure')) as repair:
                for _ in range(3):
                    report=run_once(cat,config);normalize_needs_user(cat,config)
                    self.assertFalse(report['advanced']);self.assertEqual(len(report['pending']),1)
                    with cat.connect() as db:
                        self.assertEqual(dict(db.execute("SELECT * FROM card_review_jobs WHERE id='r'").fetchone()),before)
                        self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind IN ('review_cycle_terminal_recovered','automatic_review_failed','card_review_cycle')").fetchone()[0],0)
                self.assertEqual(repair.call_count,3)

    def test_third_completed_failure_returns_to_source_recard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir();(root/'config').mkdir()
            (root/'config/review-cycle-policy.json').write_text('{"enabled":true}')
            cat=Catalog(root/'data/catalog.sqlite3');install(cat);corrections(cat)
            pid=cat.upsert({'title':'synthetic','doi':'10.9999/cycle'})
            with cat.connect() as db:
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES('r',?,'card','source','synthetic','needs_user',?,'{}','now')",(pid,str(root/'review')))
            config={'catalog_path':str(cat.path)}
            with patch('review.card_review_queue.enabled',return_value=True),patch('review.card_review_queue.current',return_value=({'id':pid},root/'card',{})),patch('review.card_review_queue.protected',return_value=False),patch('review.review_cycle.completed_failure',return_value={'action':'needs_user'}) as gate,patch('review.card_review_repair.repair',return_value={'state':'ready'}) as repair,patch('review.card_review_queue.queue_rework') as recard:
                run_once(cat,config);repair.assert_called_once();recard.assert_not_called()
                with cat.connect() as db:
                    db.execute("UPDATE card_review_jobs SET state='failed',result=? WHERE id='r'",(json.dumps({'failure_kind':'scientific'}),))
                run_once(cat,config)
                self.assertEqual(repair.call_count,2)
                with cat.connect() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='review_cycle_terminal_recovered'").fetchone()[0],0)
                gate.side_effect=ValueError('unknown receipt')
                run_once(cat,config);self.assertEqual(repair.call_count,2);recard.assert_not_called()
                gate.side_effect=None
                for i in range(2):cat.event(pid,'card_review_cycle',{'card_sha256':'card','old_folder':str(root/str(i)),'old_review_id':str(i)})
                run_once(cat,config);recard.assert_called_once()
                self.assertEqual(recard.call_args.args[-1]['cycle_failure_count'],3)


    def test_stop_between_historical_reports_preserves_failure_evidence(self):
        from review.review_cycle import failure_count
        with tempfile.TemporaryDirectory() as d:
            cat=Catalog(Path(d)/'catalog.sqlite3');pid=cat.upsert({'title':'test','doi':'10.9999/stop'})
            cat.event(pid,'card_review_cycle',{'card_sha256':'card','old_folder':d,'old_review_id':'old'})
            with patch('review.review_cycle.completed_failure') as collected:
                with self.assertRaises(InterruptedError):
                    failure_count(cat,{'paper_id':pid,'card_sha256':'card'},stopping=lambda:True)
            collected.assert_not_called()
            with cat.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='card_review_cycle'").fetchone()[0],1)

    def test_stop_after_current_assessment_never_repairs_or_recounts(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir();(root/'config').mkdir()
            (root/'config/review-cycle-policy.json').write_text('{"enabled":true}')
            cat=Catalog(root/'data/catalog.sqlite3');install(cat);corrections(cat)
            pid=cat.upsert({'title':'test','doi':'10.9999/stop-cycle'})
            with cat.connect() as db:
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES('r',?,'card','source','test','needs_user',?,'{}','now')",(pid,d))
            stop=threading.Event()
            def finish(*args):stop.set();return {'action':'needs_user'}
            with patch('review.card_review_queue.enabled',return_value=True),patch('review.card_review_queue.current',return_value=({'id':pid},root/'card',{})),patch('review.card_review_queue.protected',return_value=False),patch('review.review_cycle.completed_failure',side_effect=finish),patch('review.review_cycle.failure_count') as count,patch('review.card_review_repair.repair') as repair:
                result=run_once(cat,{'catalog_path':str(cat.path)},stopping=stop.is_set)
            self.assertEqual(result['state'],'stopping');count.assert_not_called();repair.assert_not_called()
            with cat.connect() as db:self.assertEqual(db.execute("SELECT state,result FROM card_review_jobs WHERE id='r'").fetchone()[:],('needs_user','{}'))
