import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import patch
from core.catalog import Catalog
from reading.reading_library import reading, update, refresh_scores, ReadingConflict


class ReadingLibrary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.catalog=Catalog(self.root/'catalog.db')
        self.source=self.root/'source.pdf';self.source.write_bytes(b'%PDF synthetic source')
        self.source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
    def tearDown(self):self.temp.cleanup()
    def paper(self,title,quality=None,novelty=None,seed=False,findings=None,summary=None):
        pid=self.catalog.upsert({'title':title,'doi':'10.1000/'+title,'channels':['journal']},seed=seed,candidate=True)
        card={'title':title,'meta':{'source_original_sha256':self.source_hash,'scientific_verified':False,'production_contract_complete':False}}
        if findings is not None:card['key_findings']=findings
        if summary is not None:card['one_line_summary']=summary
        if quality is not None or novelty is not None:
            card['paper_evaluation']={name:{'score':score,'reason':'Synthetic evidence','source_pages':[1]} for name,score in (('overall_quality',quality),('direction_novelty',novelty))}
        path=self.root/(pid+'.json');path.write_text(json.dumps(card))
        self.catalog.update(pid,card_path=str(path),asset_path=str(self.source),asset_hash=self.source_hash,acquisition='available')
        return pid
    def test_global_score_order_precedes_pagination_and_seeds(self):
        missing=self.paper('missing',seed=True);lower=self.paper('lower',82,99,seed=True)
        tie_low=self.paper('tie_low',95,20);tie_high=self.paper('tie_high',95,88);zero=self.paper('zero',0,0)
        ids=[self.catalog.page(1,i,tab='all')['papers'][0]['id'] for i in range(5)]
        self.assertEqual(ids,[tie_high,tie_low,lower,zero,missing])
        self.assertIsNone(self.catalog.page(1,4,tab='all')['papers'][0]['overall_quality'])

    def review(self,pid,score,state='needs_user',full=False,source_hash=None,card_hash=None):
        from review.card_review_queue import install
        install(self.catalog)
        fingerprint=card_hash or hashlib.sha256(Path(self.catalog.get(pid)['card_path']).read_bytes()).hexdigest()
        with self.catalog.connect() as db:
            db.execute("INSERT OR REPLACE INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid+fingerprint,pid,fingerprint,source_hash or self.source_hash,pid,state,str(self.root),
                 json.dumps({'weighted_score':score,'full_source_checked':full}), 'test'))

    def test_combined_global_rank_uses_current_review_before_pagination_in_all_libraries(self):
        high_paper=self.paper('high_paper',98,99,seed=True);self.review(high_paper,20)
        high_total=self.paper('high_total',80,70);self.review(high_total,95)
        same_total=self.paper('same_total',95,40);self.review(same_total,80)
        pending=self.paper('pending_review',99,99)
        zero=self.paper('zero_pair',0,0);self.review(zero,0)
        unknown=self.paper('no_paper_score');self.review(unknown,100)
        expected=[same_total,high_total,high_paper,zero,pending,unknown]
        for tab in ('all','candidates'):
            wanted=[pid for pid in expected if tab!='candidates' or pid!=high_paper]
            self.assertEqual([self.catalog.page(1,i,tab=tab)['papers'][0]['id'] for i in range(len(wanted))],wanted)
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual((row['overall_quality'],row['review_score'],row['total_score']),(95,80,175))
        self.assertFalse(row['review_full_source_checked']);self.assertEqual(row['review_state'],'needs_user')
        for pid in expected:update(self.catalog,pid,{'is_read':True})
        self.assertEqual([p['id'] for p in self.catalog.page(tab='read')['papers']],expected)

    def test_missing_review_is_unknown_and_current_version_and_source_are_required(self):
        pid=self.paper('version',90,80);path=Path(self.catalog.get(pid)['card_path'])
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertIsNone(row['review_score']);self.assertIsNone(row['total_score'])
        self.review(pid,88.75);row=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(row['total_score'],178.75)
        card=json.loads(path.read_text());card['key_findings']='new version';path.write_text(json.dumps(card))
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertIsNone(row['review_score']);self.assertIsNone(row['total_score'])
        self.review(pid,99,source_hash='other-source')
        self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['review_score'])

    def test_review_update_changes_rank_revision_without_touching_cards(self):
        from review.card_review_queue import update as review_update, rows
        first=self.paper('first',90,80);self.review(first,50)
        second=self.paper('second',80,70);self.review(second,90)
        before=[Path(self.catalog.get(pid)['card_path']).read_bytes() for pid in (first,second)]
        page=self.catalog.page(tab='all');self.assertEqual(page['papers'][0]['id'],second)
        job=next(j for j in rows(self.catalog) if j['paper_id']==first)
        review_update(self.catalog,job['id'],'needs_user',result={'weighted_score':100,'full_source_checked':False})
        after=self.catalog.page(tab='all');self.assertEqual(after['papers'][0]['id'],first)
        self.assertGreater(after['revision'],page['revision'])
        self.assertEqual([Path(self.catalog.get(pid)['card_path']).read_bytes() for pid in (first,second)],before)

    def test_existing_review_table_acquires_revision_triggers_when_workbench_opens(self):
        pid=self.paper('legacy_review_table',90,80);self.review(pid,80)
        with self.catalog.connect() as db:
            for op in ('insert','update','delete'):db.execute('DROP TRIGGER revision_card_review_jobs_'+op)
        reopened=Catalog(self.catalog.path);before=reopened.page(tab='all')
        with reopened.connect() as db:
            db.execute('UPDATE card_review_jobs SET result=? WHERE paper_id=?',(json.dumps({'weighted_score':85}),pid))
        after=reopened.page(tab='all');self.assertGreater(after['revision'],before['revision'])
        self.assertEqual(after['papers'][0]['total_score'],175)

    def test_invalid_review_scores_do_not_enter_total_ranking(self):
        pid=self.paper('invalid_review',90,80)
        for score in (True,101,-1,'98',float('nan')):
            self.review(pid,score)
            row=self.catalog.page(tab='all')['papers'][0]
            self.assertIsNone(row['review_score']);self.assertIsNone(row['total_score'])
    def test_read_is_reversible_durable_and_independent_of_decisions_jobs_and_science(self):
        pid=self.paper('read_me',92,50);path=Path(self.catalog.get(pid)['card_path']);original=path.read_bytes()
        from correction.tests.test_corrected_library import mark_corrected
        mark_corrected(self.catalog,pid,self.root)
        first=update(self.catalog,pid,{'is_read':True});self.assertTrue(first['read_at'])
        self.assertEqual(update(self.catalog,pid,{'is_read':True})['read_at'],first['read_at'])
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        self.assertEqual(self.catalog.page(tab='candidates')['total'],0)
        self.assertEqual(self.catalog.page(tab='read')['papers'][0]['id'],pid)
        reopened=Catalog(self.catalog.path);self.assertTrue(reading(reopened,pid)['is_read'])
        update(reopened,pid,{'is_read':False});self.assertIsNone(reading(reopened,pid)['read_at'])
        self.assertEqual(reopened.page(tab='deep')['total'],1)
        self.assertEqual(reopened.get(pid)['decision'],'unreviewed');self.assertEqual(path.read_bytes(),original)
        self.assertNotIn('note',reopened.get(pid));self.assertNotIn('note',reopened.list()[0])
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='human_decision'").fetchone()[0],0)
    def test_notes_persist_survive_metadata_update_and_are_searchable_with_literal_symbols(self):
        pid=self.paper('annotated');text='用户备注：50% _literal_ <img src=x onerror=alert(1)>\n疑问需要再核对。'
        saved=update(self.catalog,pid,{'note':text,'note_version':0});self.assertEqual(saved['note_version'],1)
        self.catalog.upsert({'title':'annotated','doi':'10.1000/annotated','abstract':'New metadata'})
        reopened=Catalog(self.catalog.path);self.assertEqual(reading(reopened,pid)['note'],text)
        self.assertEqual(reopened.page(query='50% _literal_')['papers'][0]['id'],pid)
        self.assertEqual(reopened.page(query='New metadata')['papers'][0]['note'],text)
        update(reopened,pid,{'note':'','note_version':1});self.assertEqual(reading(reopened,pid)['note_version'],2)
    def test_stale_note_update_rolls_back_the_whole_patch_and_preserves_newer_note(self):
        pid=self.paper('conflict');update(self.catalog,pid,{'note':'First window','note_version':0})
        with self.assertRaises(ReadingConflict):update(self.catalog,pid,{'note':'Stale draft','note_version':0,'is_read':True})
        state=reading(self.catalog,pid);self.assertEqual(state['note'],'First window');self.assertFalse(state['is_read'])
        update(self.catalog,pid,{'is_read':True});self.assertEqual(reading(self.catalog,pid)['note_version'],1)
    def test_invalid_reading_updates_do_not_change_existing_state(self):
        pid=self.paper('validate');before=reading(self.catalog,pid)
        for patch in ({},{'is_read':1},{'note':None,'note_version':0},{'note':'text'},{'note':'x'*20001,'note_version':0},{'note':'text','note_version':True},{'decision':'deep_read'}):
            with self.subTest(patch=str(patch)[:60]):
                with self.assertRaises(ValueError):update(self.catalog,pid,patch)
                self.assertEqual(reading(self.catalog,pid),before)
        with self.assertRaises(KeyError):update(self.catalog,'unknown',{'is_read':True})
    def test_invalid_or_unproven_scores_are_unknown_and_not_replaced_by_card_review_scores(self):
        pid=self.paper('bad_score',True,88);path=Path(self.catalog.get(pid)['card_path']);card=json.loads(path.read_text())
        card['paper_evaluation']['direction_novelty']['source_pages']=[];card['meta']['quality_review']={'weighted_score':99}
        path.write_text(json.dumps(card));row=self.catalog.page(tab='all')['papers'][0]
        self.assertIsNone(row['overall_quality']);self.assertIsNone(row['direction_novelty'])
        for invalid in (float('nan'),101,-1,'98'):
            card['paper_evaluation']['overall_quality']['score']=invalid;path.write_text(json.dumps(card))
            self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['overall_quality'])
    def test_score_cache_refreshes_for_changed_card_source_or_removed_card_without_writing_cards(self):
        pid=self.paper('score_change',70,30);path=Path(self.catalog.get(pid)['card_path']);before=path.read_bytes()
        first=self.catalog.page(tab='all')['papers'][0];self.assertEqual(first['overall_quality'],70)
        revision=self.catalog.page(tab='all')['revision'];self.assertEqual(self.catalog.page(tab='all')['revision'],revision)
        self.assertEqual(path.read_bytes(),before)
        card=json.loads(before);card['paper_evaluation']['overall_quality']['score']=97;path.write_text(json.dumps(card))
        second=self.catalog.page(tab='all')['papers'][0];self.assertEqual(second['overall_quality'],97)
        self.assertNotEqual(first['evaluation_card_sha256'],second['evaluation_card_sha256'])
        self.catalog.update(pid,asset_hash='changed_source');self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['overall_quality'])
        self.catalog.update(pid,card_path=None);self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM paper_card_scores').fetchone()[0],0)
    def test_card_findings_are_listed_without_assessment_or_scores_and_do_not_change_card(self):
        findings='1. 测量观察到受条件限制的结果（第1页，图1）。\n2. 模型拟合支持作者解释。'
        pid=self.paper('generated_findings',findings=findings);path=Path(self.catalog.get(pid)['card_path']);before=path.read_bytes()
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(row['card_key_findings'],findings);self.assertIsNone(row['assessment']);self.assertIsNone(row['overall_quality'])
        self.assertIsNone(row['direction_novelty']);self.assertEqual(path.read_bytes(),before)
        card=json.loads(before);self.assertFalse(card['meta']['scientific_verified']);self.assertFalse(card['meta']['production_contract_complete'])
        self.catalog.update(pid,assessment={'core_findings':'Old screening summary'})
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(row['card_key_findings'],findings);self.assertEqual(row['assessment']['core_findings'],'Old screening summary')
        self.assertEqual(path.read_bytes(),before)
    def test_card_findings_are_searchable_with_literal_symbols(self):
        findings='制卡独有结论：效率50% _literal_；不是旧初筛摘要。'
        pid=self.paper('findings_search',findings=findings)
        rows=self.catalog.page(query='制卡独有结论 50% _literal_')['papers'];self.assertEqual([r['id'] for r in rows],[pid])
        self.assertEqual(rows[0]['card_key_findings'],findings)
        self.assertEqual(self.catalog.page(query='50X _literal_')['total'],0)
    def test_old_card_score_cache_migrates_and_reindexes_without_changing_notes_or_cards(self):
        findings='Migrated generated core findings';summary='本文将分散观测连成可检验的解释。';pid=self.paper('legacy_cache',84,66,findings=findings,summary=summary)
        path=Path(self.catalog.get(pid)['card_path']);before=path.read_bytes();stat=path.stat()
        old_key=json.dumps([stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns])
        update(self.catalog,pid,{'note':'Keep my note','note_version':0,'is_read':True})
        with self.catalog.connect() as db:
            db.execute('DROP TABLE paper_card_scores')
            db.execute('CREATE TABLE paper_card_scores(paper_id TEXT PRIMARY KEY REFERENCES papers(id),card_path TEXT NOT NULL,'
                       'source_hash TEXT NOT NULL,stat_key TEXT NOT NULL,card_sha256 TEXT NOT NULL,overall_quality REAL,direction_novelty REAL,updated TEXT NOT NULL)')
            db.execute('INSERT INTO paper_card_scores VALUES(?,?,?,?,?,?,?,?)',(pid,str(path),self.source_hash,old_key,hashlib.sha256(before).hexdigest(),84,66,'old'))
        reopened=Catalog(self.catalog.path)
        with reopened.connect() as db:self.assertTrue({'key_findings','work_summary'}<={r['name'] for r in db.execute('PRAGMA table_info(paper_card_scores)')})
        row=reopened.page(tab='read')['papers'][0]
        self.assertEqual(row['card_key_findings'],findings);self.assertEqual(row['card_work_summary'],summary);self.assertEqual(row['overall_quality'],84)
        self.assertEqual(row['note'],'Keep my note');self.assertEqual(row['note_version'],1);self.assertTrue(row['is_read'])
        self.assertEqual(path.read_bytes(),before)
        with reopened.connect() as db:self.assertNotEqual(db.execute('SELECT stat_key FROM paper_card_scores WHERE paper_id=?',(pid,)).fetchone()[0],old_key)
    def test_missing_invalid_or_corrupt_card_findings_do_not_use_other_card_fields(self):
        pid=self.paper('missing_findings',95,80);path=Path(self.catalog.get(pid)['card_path']);card=json.loads(path.read_text())
        card['one_line_summary']='Do not substitute';self.catalog.update(pid,assessment={'core_findings':'Do not substitute screening'})
        for value in (None,'',' \n ',[],{},True,42):
            with self.subTest(value=value):
                if value is None:card.pop('key_findings',None)
                else:card['key_findings']=value
                path.write_text(json.dumps(card));before=path.read_bytes()
                self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings']);self.assertEqual(path.read_bytes(),before)
        path.write_text('{broken card');before=path.read_bytes()
        self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings']);self.assertEqual(path.read_bytes(),before)
    def test_card_findings_refresh_and_invalidate_when_card_or_source_changes(self):
        pid=self.paper('findings_change',findings='First generated findings');path=Path(self.catalog.get(pid)['card_path'])
        first=self.catalog.page(tab='all')['papers'][0];revision=self.catalog.page(tab='all')['revision']
        self.assertEqual(first['card_key_findings'],'First generated findings');self.assertEqual(self.catalog.page(tab='all')['revision'],revision)
        card=json.loads(path.read_text());card['key_findings']='Replacement generated findings';path.write_text(json.dumps(card));before=path.read_bytes()
        second=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(second['card_key_findings'],'Replacement generated findings');self.assertNotEqual(first['evaluation_card_sha256'],second['evaluation_card_sha256'])
        self.assertEqual(path.read_bytes(),before)
        self.catalog.update(pid,asset_hash='changed_source');self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings'])
        self.assertEqual(self.catalog.page(query='Replacement generated findings')['total'],0)
        self.catalog.update(pid,asset_hash=self.source_hash)
        for meta in ({'source_original_sha256':'wrong_source'}, {}, None, [], {'source_original_sha256':None}):
            with self.subTest(meta=meta):
                card['meta']=meta;path.write_text(json.dumps(card));self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings'])
        card['meta']={'source_original_sha256':self.source_hash};path.write_text(json.dumps(card))
        self.catalog.update(pid,asset_hash='');self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings'])
        self.catalog.update(pid,asset_hash=self.source_hash);self.assertEqual(self.catalog.page(tab='all')['papers'][0]['card_key_findings'],'Replacement generated findings')
        path.unlink();self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_key_findings'])
    def test_card_changing_during_indexing_does_not_publish_findings_or_scores(self):
        pid=self.paper('changing_card',80,40,findings='Do not publish unstable findings',summary='Do not publish unstable summary');path=Path(self.catalog.get(pid)['card_path']);before=path.read_bytes()
        stat=path.stat();changed=SimpleNamespace(**{name:getattr(stat,name) for name in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')})
        changed.st_mtime_ns+=1
        with patch('reading.reading_library.Path.stat',side_effect=[stat,changed]):refresh_scores(self.catalog)
        with self.catalog.connect() as db:row=dict(db.execute('SELECT * FROM paper_card_scores WHERE paper_id=?',(pid,)).fetchone())
        self.assertIsNone(row['key_findings']);self.assertIsNone(row['overall_quality']);self.assertIsNone(row['direction_novelty'])
        self.assertIsNone(row['work_summary'])
        self.assertEqual(row['stat_key'],'changing');self.assertEqual(row['card_sha256'],'');self.assertEqual(path.read_bytes(),before)
        with patch('reading.reading_library.Path.stat',side_effect=[stat,OSError('File vanished during read')]):refresh_scores(self.catalog)
        with self.catalog.connect() as db:row=dict(db.execute('SELECT * FROM paper_card_scores WHERE paper_id=?',(pid,)).fetchone())
        self.assertIsNone(row['key_findings']);self.assertIsNone(row['overall_quality']);self.assertIsNone(row['direction_novelty'])
        self.assertIsNone(row['work_summary'])
        self.assertEqual(path.read_bytes(),before)

    def test_work_summary_is_exact_source_bound_searchable_and_distinct_from_findings(self):
        summary='本文建立整体解释，summary_search_50% _literal_。'
        pid=self.paper('synthesis',findings='Specific result on page 1',summary=summary)
        path=Path(self.catalog.get(pid)['card_path']);before=path.read_bytes()
        self.catalog.update(pid,assessment={'core_findings':'Old screening, not the work summary'})
        row=self.catalog.page(query='summary_search_50% _literal_')['papers'][0]
        self.assertEqual(row['id'],pid);self.assertEqual(row['card_work_summary'],summary)
        self.assertEqual(row['card_key_findings'],'Specific result on page 1');self.assertIsNone(row['overall_quality'])
        self.assertEqual(self.catalog.page(query='summary_search_50X')['total'],0)
        self.assertEqual(path.read_bytes(),before)
        self.catalog.update(pid,asset_hash='other-source')
        self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_work_summary'])
        self.assertEqual(self.catalog.page(query='summary_search_50%')['total'],0)
        self.catalog.update(pid,asset_hash=self.source_hash)
        card=json.loads(before);card['one_line_summary']='Revised overall contribution';path.write_text(json.dumps(card))
        self.assertEqual(self.catalog.page(tab='all')['papers'][0]['card_work_summary'],'Revised overall contribution')
        for meta in ({},None,{'source_original_sha256':'wrong'}):
            card['meta']=meta;path.write_text(json.dumps(card))
            self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_work_summary'])

    def test_invalid_or_missing_work_summary_does_not_invent_from_other_fields(self):
        pid=self.paper('missing_summary',findings='Specific findings are not the synthesis')
        self.catalog.update(pid,assessment={'core_findings':'Screening is not the synthesis'})
        path=Path(self.catalog.get(pid)['card_path']);card=json.loads(path.read_text())
        for value in (None,'',' \n ',[],{},True,42):
            with self.subTest(value=value):
                if value is None:card.pop('one_line_summary',None)
                else:card['one_line_summary']=value
                path.write_text(json.dumps(card));before=path.read_bytes()
                row=self.catalog.page(tab='all')['papers'][0]
                self.assertIsNone(row['card_work_summary']);self.assertEqual(row['card_key_findings'],card['key_findings'])
                self.assertEqual(path.read_bytes(),before)
        path.write_text('{corrupt card')
        self.assertIsNone(self.catalog.page(tab='all')['papers'][0]['card_work_summary'])

    def test_quality_rubric_index_uses_web_overall_score_and_keeps_legacy_scores(self):
        from cards.paper_quality import VERSION, RUBRIC
        pid=self.paper('quality_rubric',78,72);path=Path(self.catalog.get(pid)['card_path']);card=json.loads(path.read_text())
        self.assertEqual(self.catalog.page(tab='all')['papers'][0]['overall_quality'],78)
        card['meta']['paper_evaluation_version']=VERSION
        quality=card['paper_evaluation']['overall_quality']
        quality['dimensions']={key:{'score':7.8,'reason':'Synthetic strength and limitation','source_pages':[1]} for key in RUBRIC}
        path.write_text(json.dumps(card));before=path.read_bytes()
        self.assertEqual(self.catalog.page(tab='all')['papers'][0]['overall_quality'],78);self.assertEqual(path.read_bytes(),before)
        quality['score']=87;path.write_text(json.dumps(card));before=path.read_bytes()
        row=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(row['overall_quality'],87);self.assertEqual(row['direction_novelty'],72);self.assertEqual(path.read_bytes(),before)
        quality['score']=78;quality['dimensions']['contribution']['source_pages']=[];path.write_text(json.dumps(card))
        self.assertEqual(self.catalog.page(tab='all')['papers'][0]['overall_quality'],78)
        card['meta']['paper_evaluation_version']='paper-evaluation-v1';path.write_text(json.dumps(card))
        self.assertEqual(self.catalog.page(tab='all')['papers'][0]['overall_quality'],78)


if __name__=='__main__':unittest.main()
