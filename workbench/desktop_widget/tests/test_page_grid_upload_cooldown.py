"""The 20-page grid keeps a cooling review slot and marks it not due."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from core.api import paths__WorkspacePath as Path

from desktop_widget.page_grid import page_grid
from cards.web_card_inputs import digest
from browser import upload_retry_policy as policy


class PageGridUploadCooldownTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name); self.data = self.root/'data'; self.data.mkdir()
        (self.root/'config').mkdir()
        self.at = 1000.0; self.pid = os.getpid()
        self.config = {'catalog_path':str(self.data/'catalog.sqlite3'),
            'web_cards':{'enabled':True,'shared_window':{'enabled':True}},
            'card_review':{'enabled':True,'upload_retry':{'enabled':True}},
            'card_correction':{'enabled':True}}
        self.write(self.root/'config/first_round.json',self.config)
        slots = [{'slot_id':f'{column:02d}','target_id':f'T{column:02d}','state':'present'}
                 for column in range(1,21)]
        registry = {'schema_version':1,'window_id':7,'slots':slots}
        self.write(self.data/'shared-gpt-window.json',registry)
        self.write(self.data/'shared-gpt-window-status.json',{**registry,'updated':self.at,'owner_pid':self.pid})
        self.write(self.data/'web-card-service.json',{'pid':self.pid,'state':'running','updated':self.at})
        self.write(self.data/'gpt-window-pool.json',{'observed_at':self.at,'shared_window_id':7,
            'windows':{slot['target_id']:{'state':'ready_blank'} for slot in slots}})
        self.write(self.data/'web-page-observer.json',{'updated':self.at,'owner_pid':self.pid,
            'activity_schema_version':1,'pages':[{'target_id':slot['target_id'],'checked_at':self.at,
                'url':'https://chatgpt.com/','state':'idle','streaming':False} for slot in slots]})
        with self.db() as db:
            db.executescript('''CREATE TABLE card_review_jobs(id TEXT PRIMARY KEY,paper_id TEXT,title TEXT,
                state TEXT,folder TEXT);
                CREATE TABLE shared_page_backlog(lane TEXT,job_id TEXT,paper_id TEXT,target_id TEXT,
                    assigned REAL,state TEXT,PRIMARY KEY(lane,job_id));
                CREATE TABLE shared_workflow_arrivals(sequence INTEGER PRIMARY KEY,lane TEXT,job_id TEXT,
                    queued_at REAL,basis TEXT,UNIQUE(lane,job_id));
                CREATE TABLE shared_page_backlog_meta(id INTEGER PRIMARY KEY,enabled INTEGER,
                    last_reconciled REAL,low_watermark INTEGER,target_tasks INTEGER,queue_depth INTEGER,
                    triggered INTEGER,total_tasks INTEGER,queued_tasks INTEGER,current_tasks INTEGER,
                    eligible_pages INTEGER,reserved_targets TEXT,status TEXT,paused_queued_count INTEGER);''')
            db.execute('INSERT INTO shared_page_backlog_meta VALUES(1,1,?,70,100,4,1,2,2,0,20,?,\'ready\',0)',
                       (self.at,json.dumps([slot['target_id'] for slot in slots[:8]])))
            policy._ddl(db)
            for sequence,(job_id,target) in enumerate((('cooling','T01'),('healthy','T01')),1):
                db.execute('INSERT INTO card_review_jobs VALUES(?,?,?,?,?)',
                           (job_id,job_id,'Article '+job_id,'ready',str(self.data/'reviews'/job_id)))
                db.execute('INSERT INTO shared_page_backlog VALUES(?,?,?,?,?,?)',
                           ('review',job_id,job_id,target,1.0,'queued'))
                db.execute('INSERT INTO shared_workflow_arrivals VALUES(?,?,?,?,?)',
                           (sequence,'review',job_id,float(sequence),'enqueue'))

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.data/'catalog.sqlite3')) as handle:
            handle.row_factory = sqlite3.Row
            with handle:
                yield handle

    def freeze_packet(self, job_id):
        """Write a real packet and return the exact material key it implies."""
        folder = self.data/'reviews'/job_id; folder.mkdir(parents=True, exist_ok=True)
        (folder/'source.pdf').write_bytes(b'synthetic frozen source')
        (folder/'bundle.zip').write_bytes(b'synthetic zip')
        packet = {'input_hashes':{'source.pdf':digest(folder/'source.pdf')},
            'upload_bundle':{'zip_path':str(folder/'bundle.zip'),'zip_sha256':digest(folder/'bundle.zip')}}
        self.write(folder/'packet.json',packet)
        return policy.material_identity(packet)

    def cool(self, job_id, *, next_eligible=None):
        inputs_digest, zip_sha256 = self.freeze_packet(job_id)
        with self.db() as db:
            db.execute('INSERT INTO upload_retry_policy VALUES(?,?,?,?,?,?,?,?,?)',
                ('review',job_id,inputs_digest,zip_sha256,1,1,900.0,
                 self.at+300 if next_eligible is None else next_eligible,900.0))

    def cells(self):
        return {cell['id']:cell for cell in self.grid()['cells']}

    def grid(self):
        return page_grid(self.root, at=self.at, owner_live=True)

    def test_cooling_slot_stays_and_only_the_due_label_changes(self):
        self.cool('cooling')
        cells = self.cells()
        self.assertEqual(cells['01-2']['lane'],'review');self.assertEqual(cells['01-2']['jobID'],'cooling')
        self.assertIs(cells['01-2']['runnable'],False)
        self.assertIn('上传失败退避中',cells['01-2']['detail'])
        self.assertEqual(cells['01-3']['jobID'],'healthy');self.assertIs(cells['01-3']['runnable'],True)
        self.assertIn('上传失败退避 1 项',self.grid()['legend'])
        self.assertEqual(self.grid()['backlog']['uploadCooldownQueuedTasks'],1)

    def test_expired_wait_returns_to_the_original_cell_without_reordering(self):
        self.cool('cooling',next_eligible=self.at)
        cells = self.cells()
        self.assertEqual(cells['01-2']['jobID'],'cooling')
        self.assertIs(cells['01-2']['runnable'],True)
        self.assertNotIn('退避',self.grid()['legend'])

    def test_unreadable_evidence_still_shows_the_slot_but_refuses_new_work(self):
        self.cool('cooling')
        (self.data/'reviews'/'cooling'/'packet.json').write_text('{')
        cells = self.cells()
        self.assertEqual(cells['01-2']['jobID'],'cooling')
        self.assertIs(cells['01-2']['runnable'],False)
        self.assertIn('待核对',cells['01-2']['detail'])

    def test_disabled_policy_marks_every_slot_due_again(self):
        self.cool('cooling')
        self.config['card_review'].pop('upload_retry')
        self.write(self.root/'config/first_round.json',self.config)
        self.assertIs(self.cells()['01-2']['runnable'],True)

    def test_fresh_login_ui_is_named_even_when_pool_health_is_stale(self):
        path=self.data/'web-page-observer.json';observer=json.loads(path.read_text())
        observer['pages'][1].update(login=True,state='login_required')
        self.write(path,observer)
        pool_path=self.data/'gpt-window-pool.json';pool=json.loads(pool_path.read_text())
        pool['observed_at']=1;self.write(pool_path,pool)
        cell=self.cells()['02-1']
        self.assertTrue(cell['loginRequired']);self.assertIn('等待手动登录',cell['detail'])
        observer['updated']=1;observer['pages'][1]['checked_at']=1;self.write(path,observer)
        self.assertNotIn('loginRequired',self.cells()['02-1'])


if __name__ == '__main__':
    unittest.main()
