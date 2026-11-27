import json
import sqlite3
import unittest
from unittest.mock import patch
from core.workflow_priority import annotate, key, sort

CONFIG={'web_cards':{'shared_window':{'backlog':{'queue_order':'paper_score'}}}}

class ArticlePriority(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE paper_card_scores(paper_id,card_sha256,source_hash,overall_quality,direction_novelty)')
        self.db.execute('CREATE TABLE card_review_jobs(paper_id,card_sha256,source_sha256,result,updated)')
    def score(self,pid,quality,review=None,card='c'):
        self.db.execute('INSERT INTO paper_card_scores VALUES(?,?,?,?,?)',(pid,card,'s',quality,80))
        if review is not None:self.db.execute('INSERT INTO card_review_jobs VALUES(?,?,?,?,?)',(pid,'c','s',json.dumps({'weighted_score':review}),1))
    def record(self,pid,at):
        return {'paper_id':pid,'job_id':pid,'queued_at':at,'sequence':at,'lane':'review'}
    def test_manual_root_first_across_lanes_retries_and_unscored_reworks(self):
        self.db.execute('CREATE TABLE manual_seed_roots(paper_id)')
        self.db.execute("INSERT INTO manual_seed_roots VALUES('seed')")
        self.score('ordinary',100,100)
        for lane in ('cards','review','correction'):
            for config in (CONFIG,{}):
                seed={**self.record('seed',10),'lane':lane,'retry_at':9999999999,
                      'selection':json.dumps({'rework':{'kind':'source_review'}})}
                ordinary={**self.record('ordinary',1),'passed_correction_priority':True}
                rows=sort(self.db,[ordinary,seed],config)
                self.assertEqual(rows[0]['paper_id'],'seed')
                self.assertEqual(rows[0]['retry_at'],9999999999)
                self.assertEqual(rows[0]['queued_at'],10)

    def test_recovery_seed_order_retains_original_dicts_and_fifo(self):
        from core.workflow_priority import seed_first
        self.db.execute('CREATE TABLE manual_seed_roots(paper_id)')
        self.db.execute("INSERT INTO manual_seed_roots VALUES('seed')")
        ordinary=self.record('ordinary',1);seed=self.record('seed',2)
        rows=seed_first(self.db,[ordinary,seed])
        self.assertIs(rows[0],seed);self.assertIs(rows[1],ordinary)
        self.assertNotIn('seed_fast_lane',seed)

    def test_same_article_order_as_library_and_no_arrival_rewrite(self):
        self.score('top',85,90.45);self.score('second',82,92.15)
        rows=[self.record('second',1),self.record('top',2)]
        ranked=sort(self.db,rows,CONFIG)
        self.assertEqual([r['job_id'] for r in ranked],['top','second'])
        self.assertEqual([r['queued_at'] for r in rows],[1,2])
    def test_fast_lane_quality_card_precedes_a_scored_regular_card(self):
        config={**CONFIG,'web_cards':{'shared_window':{'backlog':{'queue_order':'paper_score',
            'fast_lane':{'enabled':True,'card_quality_min':80,'review_score_min':85,'total_score_min':170}}}}}
        self.score('fast',90,None);self.score('regular',60,84)
        ranked=sort(self.db,[self.record('regular',1),self.record('fast',2)],config)
        self.assertEqual([r['paper_id'] for r in ranked],['fast','regular'])
        self.assertTrue(ranked[0]['fast_lane']);self.assertFalse(ranked[1]['fast_lane'])
    def test_version_changed_score_never_borrows_old_review(self):
        self.score('changed',90,99,card='new');self.score('valid',80,85)
        ranked=sort(self.db,[self.record('changed',1),self.record('valid',2)],CONFIG)
        self.assertEqual(ranked[0]['paper_id'],'valid')
        self.assertIsNone(ranked[1]['article_review_score'])
    def test_unknowns_remain_missing_and_ties_keep_arrival(self):
        rows=sort(self.db,[self.record('later',2),self.record('earlier',1)],CONFIG)
        self.assertEqual(rows[0]['paper_id'],'earlier');self.assertIsNone(rows[0]['article_quality'])
    def test_disabled_preserves_fifo(self):
        self.score('top',85,90)
        rows=sort(self.db,[self.record('top',2),self.record('old',1)],{})
        self.assertEqual(rows[0]['paper_id'],'old')
    def test_unrelated_report_payloads_are_not_read_for_candidate_scores(self):
        self.score('wanted',80,90)
        for i in range(200):self.score('unrelated-'+str(i),1,1)
        self.db.execute("UPDATE card_review_jobs SET result=? WHERE paper_id!='wanted'",
                        (json.dumps({'weighted_score':1,'unrelated_probe':True}),))
        original=json.loads
        def read(text,*args,**kwargs):
            self.assertNotIn('unrelated_probe',text)
            return original(text,*args,**kwargs)
        with patch('core.workflow_priority.json.loads',side_effect=read):
            row=annotate(self.db,[self.record('wanted',1)],CONFIG)[0]
        self.assertEqual(row['article_total_score'],170)
    def test_empty_candidates_do_not_scan_any_database_table(self):
        self.db.set_authorizer(lambda *args:sqlite3.SQLITE_DENY)
        self.assertEqual(annotate(self.db,[],CONFIG),[])

class PassedCorrectionPriority(unittest.TestCase):
    score = ArticlePriority.score
    record = ArticlePriority.record
    def setUp(self):
        ArticlePriority.setUp(self)
        self.db.execute('CREATE TABLE papers(id,asset_hash)')
        self.db.execute('CREATE TABLE card_correction_jobs(id,paper_id,source_sha256,card_sha256,state,payload,result)')
        self.config={**CONFIG,'card_correction':{'priority_passed_first':True}}
    def correction(self,pid,cid,state='queued',after=None,source='s',full=True):
        self.db.execute('INSERT INTO papers VALUES(?,?)',(pid,'s'))
        assessment={'model_report_pass':True,'full_source_checked':full,'verdict':'pass','weighted_score':90,
                    'missing_inputs':[],'issue_counts':{'major':0,'critical':0}}
        self.db.execute('INSERT INTO card_correction_jobs VALUES(?,?,?,?,?,?,?)',
                        (cid,pid,source,'old',state,json.dumps({'assessment':assessment}),json.dumps({'after':after})))
    def test_pin_beats_higher_score_and_survives_new_sort_without_changing_arrival(self):
        self.correction('pinned','fix');self.score('top',100,100)
        fix={'paper_id':'pinned','id':'fix','kind':'formatting','source_sha256':'s','fifo_at':9}
        ranked=sort(self.db,[self.record('top',1),fix],self.config)
        self.assertEqual(ranked[0]['id'],'fix');self.assertTrue(ranked[0]['passed_correction_priority'])
        self.assertEqual(sort(self.db,ranked,self.config)[0]['fifo_at'],9)
    def test_pending_recheck_inherits_pin_and_passed_recheck_releases_it(self):
        self.correction('pinned','fix','applied',after='new')
        row={**self.record('pinned',9),'card_sha256':'new','source_sha256':'s','state':'queued'}
        self.assertTrue(annotate(self.db,[row],self.config)[0]['passed_correction_priority'])
        row['state']='passed'
        self.assertFalse(annotate(self.db,[row],self.config)[0]['passed_correction_priority'])
        row.update(state='queued',card_sha256='unrelated')
        self.assertFalse(annotate(self.db,[row],self.config)[0]['passed_correction_priority'])
    def test_incomplete_changed_source_and_disabled_policy_never_pin(self):
        for source,full in [('changed',True),('s',False)]:
            self.db.execute('DELETE FROM papers');self.db.execute('DELETE FROM card_correction_jobs')
            self.correction('p','fix',source=source,full=full)
            row={'paper_id':'p','id':'fix','kind':'formatting','source_sha256':source}
            self.assertFalse(annotate(self.db,[row],self.config)[0]['passed_correction_priority'])
        self.db.execute('DELETE FROM papers');self.db.execute('DELETE FROM card_correction_jobs')
        self.correction('p','fix');self.assertFalse(annotate(self.db,[row],CONFIG)[0]['passed_correction_priority'])
    def test_original_pass_pin_follows_reclassified_source_rework_without_fabricating_scores(self):
        self.correction('p','old','superseded')
        self.db.execute('INSERT INTO card_correction_jobs VALUES(?,?,?,?,?,?,?)',('new','p','s','old','ready','{}','{}'))
        record={'paper_id':'p','lane':'correction','job_id':'new','source_job':{'paper_id':'p','source_sha256':'s','selection':json.dumps({'rework':{'correction_id':'new'}})}}
        ranked=annotate(self.db,[record],self.config)[0]
        self.assertTrue(ranked['passed_correction_priority']);self.assertIsNone(ranked['article_total_score'])
    def test_unrelated_correction_payloads_cannot_enter_candidate_pin_read(self):
        self.correction('wanted','fix')
        self.correction('unrelated','old')
        self.db.execute("UPDATE card_correction_jobs SET payload=? WHERE paper_id='unrelated'",
                        (json.dumps({'unrelated_probe':True}),))
        original=json.loads
        def read(text,*args,**kwargs):
            self.assertNotIn('unrelated_probe',text)
            return original(text,*args,**kwargs)
        record={'paper_id':'wanted','id':'fix','kind':'formatting','source_sha256':'s'}
        with patch('core.workflow_priority.json.loads',side_effect=read):
            self.assertTrue(annotate(self.db,[record],self.config)[0]['passed_correction_priority'])
