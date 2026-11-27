import unittest
from reading.tests.test_reading_library import ReadingLibrary
from correction.tests.test_corrected_library import mark_corrected
from fetch import manual_seed_lineage as lineage
from reading.reading_library import update

class ManualLineageTests(unittest.TestCase):
    setUp=ReadingLibrary.setUp
    tearDown=ReadingLibrary.tearDown
    paper=ReadingLibrary.paper

    def register(self,pid):
        lineage.install(self.catalog)
        lineage.register_root(self.catalog,self.catalog.get(pid),self.source,self.source_hash)

    def test_descendant_promotion_keeps_recursive_manual_origin_and_cycles_are_bounded(self):
        root=self.paper('root');self.register(root)
        child=self.catalog.upsert({'title':'child','doi':'10.1000/child','discovered_from_seed_dois':['10.1000/root']})
        self.catalog.upsert({'title':'child','doi':'10.1000/child'},seed=True)
        grand=self.catalog.upsert({'title':'grand','doi':'10.1000/grand','discovered_from_seed_dois':['10.1000/child']})
        self.catalog.upsert({'title':'root','doi':'10.1000/root','discovered_from_seed_dois':['10.1000/grand']})
        self.assertEqual(lineage.reconcile(self.catalog),{'manual_seeds':1,'derived':2})
        with self.catalog.connect() as db:
            self.assertEqual({r[0] for r in db.execute('SELECT paper_id FROM manual_seed_lineage')},{child,grand})
        self.assertTrue(self.catalog.get(child)['seed'])

    def test_exact_legacy_reason_backfills_but_ambiguous_parent_does_not(self):
        root=self.paper('root');child=self.paper('child')
        self.catalog.upsert({'title':'child','doi':'10.1000/child'},reason='参考文献：root')
        self.register(root)
        self.assertEqual(lineage.reconcile(self.catalog)['derived'],1)
        self.catalog.upsert({'title':'same','doi':'10.1000/one'})
        self.catalog.upsert({'title':'same','doi':'10.1000/two'})
        self.catalog.upsert({'title':'ambiguous','doi':'10.1000/ambiguous'},reason='引用种子：same')
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM seed_discovery_origins WHERE seed_doi IN ('10.1000/one','10.1000/two')").fetchone()[0],0)

    def test_library_split_preserves_review_read_search_and_pagination(self):
        root=self.paper('root',90,80);self.register(root)
        child=self.paper('child',95,80);grand=self.paper('grand',80,80)
        ordinary=self.paper('ordinary',100,80);pending=self.paper('pending',99,80)
        for name,parent in [('child','root'),('grand','child'),('pending','root')]:
            self.catalog.upsert({'title':name,'doi':'10.1000/'+name,'discovered_from_seed_dois':['10.1000/'+parent]},seed=name=='child')
        lineage.reconcile(self.catalog)
        for pid in (root,child,grand,ordinary):mark_corrected(self.catalog,pid,self.root)
        self.assertEqual([r['id'] for r in self.catalog.page(tab='deep_regular')['papers']],[ordinary])
        seeds=self.catalog.page(tab='deep_manual_seeds')
        self.assertEqual([r['id'] for r in seeds['papers']],[root])
        self.assertEqual(seeds['stats']['deep_manual_derived'],2)
        self.assertEqual(self.catalog.page(1,0,tab='deep_manual_derived')['papers'][0]['id'],child)
        self.assertEqual(self.catalog.page(1,1,tab='deep_manual_derived')['papers'][0]['id'],grand)
        self.assertEqual(self.catalog.page(query='pending',tab='deep_manual_derived')['total'],0)
        update(self.catalog,child,{'is_read':True})
        self.assertEqual(self.catalog.page(tab='deep_manual_derived')['total'],1)
        self.assertEqual(self.catalog.page(tab='read')['papers'][0]['id'],child)
        update(self.catalog,child,{'is_read':False})
        self.assertEqual(self.catalog.page(tab='deep_manual_derived')['total'],2)

    def test_multiple_roots_are_preserved_and_repeated_scan_is_stable(self):
        a=self.paper('a');b=self.paper('b');self.register(a);self.register(b)
        self.catalog.upsert({'title':'child','doi':'10.1000/child','discovered_from_seed_dois':['10.1000/a']})
        self.catalog.upsert({'title':'child','doi':'10.1000/child','discovered_from_seed_dois':['10.1000/b']})
        lineage.reconcile(self.catalog)
        before=self.catalog.page()['revision']
        self.register(a);lineage.reconcile(self.catalog)
        self.assertEqual(self.catalog.page()['revision'],before)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM manual_seed_lineage').fetchone()[0],2)
