import hashlib
import json
import unittest
from core.api import paths__WorkspacePath as Path
from reading.tests import test_reading_library as fixtures
from correction.card_correction_queue import install
from reading.reading_library import update


def mark_corrected(catalog, pid, folder, state='applied', after=None, source=None, passed=True):
    install(catalog)
    paper=catalog.get(pid)
    fingerprint=after or hashlib.sha256(Path(paper['card_path']).read_bytes()).hexdigest()
    with catalog.connect() as db:
        db.execute("INSERT OR REPLACE INTO card_correction_jobs(id,review_id,paper_id,card_sha256,source_sha256,kind,title,state,folder,payload,task_sha256,result,created,fifo_at,queued_at,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid,pid,pid,'before',source or paper['asset_hash'],'quote_location',paper['title'],state,str(folder),'{}','task',json.dumps({'after':fingerprint}),'test',1,1,'test'))

    if passed:mark_passed(catalog,pid,folder)


def mark_passed(catalog,pid,folder,patch=None):
    from review.card_review_queue import install as install_review
    install_review(catalog)
    paper=catalog.get(pid);fingerprint=hashlib.sha256(Path(paper['card_path']).read_bytes()).hexdigest()
    result={'pass':True,'full_source_checked':True,'verdict':'pass','action':'pass',
            'weighted_score':90,'missing_inputs':[],'issue_counts':{'major':0,'critical':0}}
    result.update(patch or {})
    with catalog.connect() as db:
        db.execute("INSERT OR REPLACE INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES(?,?,?,?,?,?,?,?,?)",
            (pid+fingerprint,pid,fingerprint,paper['asset_hash'],paper['title'],'passed',str(folder),json.dumps(result),'test'))


class CorrectedLibrary(unittest.TestCase):
    setUp=fixtures.ReadingLibrary.setUp
    tearDown=fixtures.ReadingLibrary.tearDown
    paper=fixtures.ReadingLibrary.paper

    def test_only_current_applied_cards_are_visible_and_counts_match_before_pagination(self):
        pending=self.paper('pending',99,99)
        high=self.paper('high',95,50);mark_corrected(self.catalog,high,self.root)
        low=self.paper('low',70,50);mark_corrected(self.catalog,low,self.root)
        for state in ('submitted','needs_user','ready'):
            pid=self.paper(state,100,100);mark_corrected(self.catalog,pid,self.root,state)
        page=self.catalog.page(1,0,tab='deep')
        self.assertEqual(page['total'],2);self.assertEqual(page['stats']['unread_deep'],2)
        self.assertEqual(page['papers'][0]['id'],high)
        self.assertEqual(self.catalog.page(1,1,tab='deep')['papers'][0]['id'],low)
        self.assertEqual(self.catalog.page(query='pending',tab='deep')['total'],0)
        self.assertEqual(self.catalog.page(tab='all')['total'],6)
        self.assertFalse(json.loads(Path(self.catalog.get(high)['card_path']).read_text())['meta']['scientific_verified'])

    def test_missing_table_or_applied_result_does_not_qualify(self):
        pid=self.paper('new')
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        mark_corrected(self.catalog,pid,self.root)
        for raw in ('{}','{broken','{"after":"wrong"}'):
            with self.catalog.connect() as db:db.execute('UPDATE card_correction_jobs SET result=?',(raw,))
            self.assertEqual(self.catalog.page(tab='deep')['total'],0)

    def test_changed_card_or_source_invalidates_old_completion(self):
        pid=self.paper('changing');mark_corrected(self.catalog,pid,self.root)
        self.assertEqual(self.catalog.page(tab='deep')['total'],1)
        path=Path(self.catalog.get(pid)['card_path']);card=json.loads(path.read_text());card['key_findings']='new';path.write_text(json.dumps(card))
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        mark_corrected(self.catalog,pid,self.root)
        self.assertEqual(self.catalog.page(tab='deep')['total'],1)
        self.catalog.update(pid,asset_hash='different')
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)

    def test_read_state_remains_independent_and_reversible(self):
        pid=self.paper('read');mark_corrected(self.catalog,pid,self.root)
        update(self.catalog,pid,{'is_read':True})
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        self.assertEqual(self.catalog.page(tab='read')['total'],1)
        update(self.catalog,pid,{'is_read':False})
        self.assertEqual(self.catalog.page(tab='deep')['total'],1)

    def test_correction_without_full_recheck_is_hidden(self):
        pid=self.paper('not_rechecked');mark_corrected(self.catalog,pid,self.root,passed=False)
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        invalid=[{'pass':False},{'full_source_checked':False},{'verdict':'revise'},
                 {'weighted_score':84},{'missing_inputs':['supplement']},
                 {'issue_counts':{'major':1,'critical':0}}, {'issue_counts':{'major':0,'critical':1}}]
        for patch in invalid:
            mark_passed(self.catalog,pid,self.root,patch)
            self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        mark_passed(self.catalog,pid,self.root)
        self.assertEqual(self.catalog.page(tab='deep')['total'],1)

    def test_pass_without_correction_does_not_enter_completed_loop(self):
        pid=self.paper('direct_pass');mark_passed(self.catalog,pid,self.root)
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)

    def test_verified_metadata_publication_preserves_correction_lineage(self):
        pid=self.paper('published');mark_corrected(self.catalog,pid,self.root)
        path=Path(self.catalog.get(pid)['card_path']);before=hashlib.sha256(path.read_bytes()).hexdigest()
        card=json.loads(path.read_text());card['meta']['scientific_verified']=True;path.write_text(json.dumps(card))
        mark_passed(self.catalog,pid,self.root,{'publication_alias':True})
        self.assertEqual(self.catalog.page(tab='deep')['total'],0)
        after=hashlib.sha256(path.read_bytes()).hexdigest()
        self.catalog.event(pid,'card_source_review',{'state':'passed','before':before,'after':after})
        self.assertEqual(self.catalog.page(tab='deep')['total'],1)

    def test_completion_updates_revision_for_live_refresh(self):
        pid=self.paper('live');mark_corrected(self.catalog,pid,self.root,'submitted')
        before=self.catalog.page(tab='deep')
        with self.catalog.connect() as db:db.execute("UPDATE card_correction_jobs SET state='applied' WHERE paper_id=?",(pid,))
        after=self.catalog.page(tab='deep')
        self.assertGreater(after['revision'],before['revision']);self.assertEqual(after['total'],1)
