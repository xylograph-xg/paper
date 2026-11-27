"""Behavioral contracts using isolated databases; no model or external network."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.api import catalog__Catalog as Catalog, literature_catalog__metadata_rows as metadata_rows
from literature.api import Store, Library, Conflict


class LiteratureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root/'catalog.db')
        self.a = self.catalog.upsert({'title':'Energy transfer study','doi':'10.1000/a','year':2018,'venue':'Journal A','abstract':'We study reverse intersystem crossing using transient spectroscopy.','keywords':['RISC','exciton'],'authors':['A Li']})
        self.b = self.catalog.upsert({'title':'Organic crystal methods','doi':'10.1000/b','year':2024,'abstract':'Quantum calculations on organic crystals.','keywords':['crystals']})
        self.c = self.catalog.upsert({'title':'Unknown date and abstract','doi':'10.1000/c'})
        self.catalog.update(self.a, acquisition='available', asset_path=str(self.root/'source.pdf'), asset_hash='source-v1')
        self.library = Library(self.catalog.path)
        self.store = self.library.store
        self.tag = self.store.save_tag(dimension='mechanism',name_zh='反向系间窜越',name_en='reverse intersystem crossing',aliases=['RISC'])

    def record(self, pid=None, **kw):
        return {'paper_id':pid or self.a,'tag_id':self.tag['id'],'quote':'reverse intersystem crossing','scope':'abstract','page':None,'relation':'about','input_fingerprint':'input-v1','generator_version':'candidate-v1','origin':'automatic',**kw}

    def seed_legacy(self, **kw):
        # Historical records are fixtures, never a supported new manual-label path.
        from literature.store import fingerprint, encode
        r=self.record(**kw);r['origin']='manual';r.setdefault('locator',{})
        with self.store.connect(True) as db:
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(fingerprint(r),r['paper_id'],r['tag_id'],r['quote'],r['scope'],r['page'],r['relation'],r['input_fingerprint'],r['generator_version'],'manual','legacy',encode(r['locator'])))
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?)',(r['paper_id'],r['tag_id'],kw.get('state','confirmed'),'manual',1))

    def test_all_papers_not_curated_subset_and_no_catalog_writes(self):
        with self.catalog.connect() as db: before = list(db.iterdump())
        self.assertEqual(self.library.query()['total'],3)
        self.library.auto_label([self.a])
        self.library.store.save_collection(name='学习')
        with self.catalog.connect() as db: after = list(db.iterdump())
        self.assertEqual(before,after)
        self.assertEqual(self.library.detail(self.a)['metadata']['keywords'],['RISC','exciton'])

    def test_alias_normalization_collision_and_edit_retains_evidence(self):
        self.assertEqual(self.store.resolve(' ＲＩＳＣ ', 'mechanism'),self.tag['id'])
        with self.assertRaises(Conflict):self.store.save_tag(dimension='mechanism',name_zh='重复',aliases=['risc'])
        self.store.annotate([self.record()])
        changed=self.store.save_tag(**{k:self.tag[k] for k in ('id','dimension','name_zh','name_en','aliases','parent_id','status')},expected_version=1)
        self.assertEqual(changed['version'],2)
        self.assertEqual(len(self.store.annotations(self.a)[0]['evidence']),1)
        with self.assertRaises(Conflict):self.store.save_tag(dimension='mechanism',name_zh='旧编辑',id=self.tag['id'],expected_version=1)

    def test_tree_depth_cycles_dimension_and_descendant_move(self):
        child=self.store.save_tag(dimension='mechanism',name_zh='二层',parent_id=self.tag['id'])
        grand=self.store.save_tag(dimension='mechanism',name_zh='三层',parent_id=child['id'])
        with self.assertRaises(ValueError):self.store.save_tag(dimension='mechanism',name_zh='四层',parent_id=grand['id'])
        with self.assertRaises(ValueError):self.store.save_tag(dimension='object',name_zh='错维度',parent_id=self.tag['id'])
        with self.assertRaises(ValueError):self.store.save_tag(dimension='mechanism',name_zh='循环',id=self.tag['id'],parent_id=child['id'],expected_version=1)
        other=self.store.save_tag(dimension='mechanism',name_zh='另一根')
        with self.assertRaises(ValueError):self.store.save_tag(dimension='mechanism',name_zh='移根',id=self.tag['id'],parent_id=other['id'],expected_version=1)

    def test_manual_rejection_protected_and_evidence_append_only(self):
        self.seed_legacy(state='rejected')
        result=self.store.annotate([self.record(input_fingerprint='new-input')])
        self.assertTrue(result[0]['manual_protected'])
        a=self.store.annotations(self.a)[0]
        self.assertEqual((a['state'],a['actor'],a['version']),('rejected','manual',1))
        self.assertEqual(len(a['evidence']),2)
        self.store.annotate([self.record(input_fingerprint='new-input')])
        self.assertEqual(len(self.store.annotations(self.a)[0]['evidence']),2)
        self.assertEqual(self.library.query({'q':'RISC'})['total'],1) # source keywords still searchable
        self.assertEqual(self.library.query({'tags':{'mechanism':[self.tag['id']]}})['total'],0)
        with self.assertRaises(ValueError):self.store.annotate([self.record(state='confirmed')])
        with self.assertRaisesRegex(ValueError,'人工'):self.store.annotate([self.record(origin='manual',state='confirmed',expected_version=0)])

    def test_batch_atomicity_and_missing_paper(self):
        with self.assertRaises(ValueError):self.store.annotate([self.record(),self.record(self.b,scope='invented')])
        self.assertEqual(self.store.annotations(),[])
        with self.assertRaises(ValueError):self.library.annotate([self.record('missing')])
        self.assertEqual(self.store.annotations(),[])

    def test_abstract_quote_validation_and_fulltext_fingerprint(self):
        with self.assertRaises(ValueError):self.library.dispatch('annotate',{'records':[{'paper_id':self.a,'tag_id':self.tag['id'],'quote':'invented quote','scope':'abstract','relation':'about'}]})
        self.store.annotate([self.record(quote='PDF quote',scope='fulltext',page=4,relation='used',input_fingerprint='source-v1')])
        evidence=self.store.annotations(self.a)[0]['evidence'][0]
        self.assertEqual(evidence['input_fingerprint'],'source-v1')
        self.assertEqual(evidence['page'],4)
        with self.assertRaises(ValueError):self.store.annotate([self.record(page=1)])
        with self.assertRaises(ValueError):self.library.dispatch('annotate',{'records':[{'paper_id':self.b,'tag_id':self.tag['id'],'quote':'no source','scope':'fulltext','relation':'about'}]})

    def test_multi_dimension_parent_alias_missing_year_and_relation(self):
        child=self.store.save_tag(dimension='mechanism',name_zh='子过程',parent_id=self.tag['id'],aliases=['subprocess'])
        obj=self.store.save_tag(dimension='object',name_zh='有机晶体')
        self.store.annotate([self.record(tag_id=child['id'],relation='mentioned'),self.record(tag_id=obj['id'])])
        self.assertEqual(self.library.query({'q':'SUBPROCESS'})['total'],1)
        self.assertEqual(self.library.query({'tags':{'mechanism':[self.tag['id']],'object':[obj['id']]}})['total'],1)
        self.assertEqual(self.library.query({'year_from':2020})['total'],1)
        self.assertEqual(self.library.query({'has_pdf':True})['papers'][0]['id'],self.a)
        self.assertEqual(next(a for a in self.library.detail(self.a)['annotations'] if a['tag_id']==child['id'])['evidence'][0]['relation'],'mentioned')
        with self.assertRaises(ValueError):self.library.query({'tags':{'object':[self.tag['id']]}})
        self.assertEqual(self.library.query({'state':'confirmed'})['total'],0)

    def test_collection_dynamic_include_exclude_and_local_roles(self):
        c=self.store.save_collection(name='主题A',filters={'year_from':2020})
        self.assertEqual(self.library.query(collection_id=c['id'])['papers'][0]['id'],self.b)
        self.library.save_member(collection_id=c['id'],paper_id=self.b,mode='exclude')
        self.library.save_member(collection_id=c['id'],paper_id=self.a,mode='include',role='intro',position=1,progress='reading',note='先读')
        rows=self.library.query(collection_id=c['id'])['papers']
        self.assertEqual([p['id'] for p in rows],[self.a]);self.assertEqual(rows[0]['membership']['role'],'intro')
        second=self.store.save_collection(name='主题B')
        self.assertEqual(self.library.query(collection_id=second['id'])['total'],0)
        self.library.save_member(collection_id=second['id'],paper_id=self.a,role='method')
        self.assertEqual(self.library.query(collection_id=second['id'])['papers'][0]['membership']['role'],'method')
        with self.assertRaises(Conflict):self.library.save_member(collection_id=c['id'],paper_id=self.a,role='debate',expected_version=0)
        self.assertFalse(self.library.detail(self.a)['is_read']) # topic progress does not mutate reading state
        with self.assertRaises(Conflict):self.store.save_collection(name='旧版本',id=c['id'],expected_version=0)

    def test_store_cannot_be_primary_catalog(self):
        with self.assertRaises(ValueError):Library(self.catalog.path,self.catalog.path)
        self.assertEqual(len(metadata_rows(self.catalog.path)),3)

    def test_fresh_metadata_and_missing_scores_are_not_invented(self):
        self.assertIsNone(self.library.detail(self.a)['review_score'])
        self.catalog.upsert({'title':'Updated title','doi':'10.1000/a','year':2025})
        row=self.library.detail(self.a)
        self.assertEqual(row['title'],'Updated title');self.assertEqual(row['metadata']['year'],2025)
        self.assertEqual(self.library.query({'year_from':2025})['total'],1)

    def test_optional_vocabulary_keeps_manual_choices_and_no_auto_annotations(self):
        # Existing confirmed RISC is retained, including its aliases and UUID.
        result=self.library.dispatch('import_oled_vocabulary',{})
        self.assertEqual(len(result['created']),18)
        self.assertEqual(len(result['skipped']),1)
        self.assertEqual(result['papers_annotated'],0)
        self.assertTrue(all(t['status']=='candidate' for t in result['created']))
        self.assertEqual(self.store.annotations(),[])
        self.assertEqual(self.library.dispatch('import_oled_vocabulary',{})['created'],[])
        self.assertEqual(self.store.resolve('RISC','mechanism'),self.tag['id'])
        self.assertEqual(next(t for t in self.store.tags() if t['id']==self.tag['id'])['status'],'confirmed')

    def test_locator_roundtrip_and_changed_source_is_visible(self):
        locator={'entity':'compound 1','table':'Table 2','figure':'Fig. 3b','conditions':'MeCN, 298 K'}
        self.seed_legacy(quote='Original evidence',scope='fulltext',page=3,relation='used',locator=locator,input_fingerprint='source-v1')
        evidence=self.library.detail(self.a)['annotations'][0]['evidence'][0]
        self.assertEqual(evidence['locator'],locator);self.assertTrue(evidence['input_current'])
        self.catalog.update(self.a,asset_hash='source-v2')
        annotation=self.library.detail(self.a)['annotations'][0]
        self.assertEqual(annotation['state'],'confirmed') # human decision preserved
        self.assertFalse(annotation['evidence'][0]['input_current'])
        with self.assertRaises(ValueError):self.store.annotate([self.record(locator=locator)])

    def test_scores_are_live_version_bound_stored_values(self):
        with self.catalog.connect() as db:
            db.execute("INSERT INTO paper_card_scores(paper_id,card_path,source_hash,stat_key,card_sha256,overall_quality,direction_novelty,key_findings,work_summary,updated) VALUES(?,?,'source-v1','','card-v1',72,60,'','','')",(self.a,'/tmp/literature-synthetic-card.json'))
        self.catalog.update(self.a,card_path='/tmp/literature-synthetic-card.json')
        self.assertEqual(self.library.detail(self.a)['overall_quality'],72)
        with self.catalog.connect() as db:db.execute('UPDATE paper_card_scores SET overall_quality=79 WHERE paper_id=?',(self.a,))
        self.assertEqual(self.library.detail(self.a)['overall_quality'],79)
        self.catalog.update(self.a,asset_hash='source-v2')
        self.assertIsNone(self.library.detail(self.a)['overall_quality'])


if __name__=='__main__':unittest.main()
