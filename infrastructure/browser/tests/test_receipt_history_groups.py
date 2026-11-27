import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from browser.receipt_history_groups import group_histories

class ReceiptHistoryGroups(unittest.TestCase):
    def test_exact_legacy_grouping_with_archives_and_prefix_siblings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'review').mkdir()
            (root/'review-old').mkdir()
            file = root/'file'; file.touch()
            items = [{'id':'root','source':str(root)}, {'id':'review','source':str(root/'review')},
                     {'id':'file','source':str(file)}, {'id':'missing','source':str(root/'missing')},
                     {'id':'page:t'}, {'id':'review','source':str(root/'review-old')},
                     {'id':'relative','source':'review'}]
            records = {str(i):{'target_id':t, '_ledger_path':str(root/p)} for i,(t,p) in enumerate(
                [('t','review/a/attempt.json'), ('t','review/archive/b/attempt.json'),
                 ('u','review-old/attempt.json'), ('u','file')])}
            expected = {}
            for item in items:
                key = item['id']
                original = next(x for x in items if x['id']==key)
                source = Path(original.get('source') or root)
                expected[key] = ([r for r in records.values() if r.get('target_id')==key[5:]]
                    if key.startswith('page:') else [r for r in records.values()
                    if Path(r['_ledger_path']).is_relative_to(source)] if source.is_dir() else [])
            self.assertEqual(group_histories(items, records, root), expected)

if __name__ == '__main__': unittest.main()

class ArrivalMigration(unittest.TestCase):
    def test_registration_preserves_sequence_and_does_not_reinsert_registered_rows(self):
        import sqlite3
        from browser.shared_workflow_queue import install
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'db.sqlite'
            statements = []
            class Catalog:
                def connect(self):
                    db = sqlite3.connect(path)
                    db.set_trace_callback(statements.append)
                    return db
            catalog = Catalog()
            with catalog.connect() as db:
                db.execute('CREATE TABLE card_review_jobs(id TEXT PRIMARY KEY)')
                db.executemany('INSERT INTO card_review_jobs VALUES(?)', [('z',), ('a',), ('b',)])
            install(catalog)
            with catalog.connect() as db:
                before = db.execute('SELECT * FROM shared_workflow_arrivals ORDER BY sequence').fetchall()
            self.assertEqual([r[2] for r in before], ['z','a','b'])
            self.assertTrue(all(r[4]=='migration_registration' for r in before))
            statements.clear()
            install(catalog)
            with catalog.connect() as db:
                self.assertEqual(db.execute('SELECT * FROM shared_workflow_arrivals ORDER BY sequence').fetchall(), before)
                db.execute("INSERT INTO card_review_jobs VALUES('next')")
                new = db.execute("SELECT * FROM shared_workflow_arrivals WHERE job_id='next'").fetchone()
            self.assertEqual(new[0], 4)
            self.assertEqual(new[4], 'enqueue')
            self.assertEqual(sum('SELECT ?, source.' in s for s in statements),0)
            self.assertEqual(sum('FROM card_review_jobs AS source' in s for s in statements),1)

class ReviewRefillSeparation(unittest.TestCase):
    def test_only_original_producer_runs_failure_cycle(self):
        from unittest.mock import patch
        from core.catalog import Catalog
        from review.card_review_queue import enqueue
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            catalog=Catalog(root/'catalog.sqlite3')
            config={'catalog_path':str(catalog.path),'card_review':{'enabled':True}}
            with patch('review.review_cycle.run_once') as cycle, patch('review.review_channel_recovery.recover'):
                self.assertEqual(enqueue(catalog,config,maintain_cycles=False),0)
                cycle.assert_not_called()
                self.assertEqual(enqueue(catalog,config),0)
                cycle.assert_called_once_with(catalog,config)
