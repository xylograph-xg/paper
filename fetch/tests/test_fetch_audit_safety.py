"""Synthetic regression for verified fetch audit failures; no network or live DB."""
import io,json,os,sqlite3,time,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from fetch.tests import test_fetch_pipeline as fixtures
from fetch import fetching; from core import services; from fetch import network
from core.control import Decision

class FetchAuditSafety(fixtures.FetchFixtures):
    def jobs(self,n=2):
        self.config['fetch_pipeline'].update(download_workers=1,fallback_workers=0)
        return [self.catalog.enqueue('acquire',self.catalog.upsert(self.record(i))) for i in range(n)]

    def acquired(self,catalog,config,job):
        path=self.root/(job['paper_id']+'.pdf');path.write_bytes(b'synthetic')
        catalog.update(job['paper_id'],asset_path=str(path),acquisition='available')
        return {'available':True}

    def row(self,jid):
        with self.catalog.connect() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())

    def test_invalid_control_blocks_new_claim_but_collects_existing(self):
        ids=self.jobs();calls=0;snapshots=[];write=services.atomic_json
        def stop():
            nonlocal calls
            calls+=1;return calls>=5
        def snapshot(path,data,**kw):
            if Path(path).name=='worker-fetch.json':snapshots.append(data)
            return write(path,data,**kw)
        with patch('core.concurrency_control.apply',side_effect=[{},ValueError('invalid'),ValueError('invalid'),ValueError('invalid'),ValueError('invalid')]),patch('fetch.fetching.run_acquisition',side_effect=self.acquired) as run,patch('fetch.fetching.services.atomic_json',side_effect=snapshot):
            fetching.fetch_loop(self.catalog,self.config,True,stop)
        self.assertEqual(run.call_count,1);self.assertEqual(self.row(ids[0])['state'],'done')
        self.assertEqual(self.row(ids[1])['state'],'queued');self.assertEqual(self.row(ids[1])['attempts'],0)
        self.assertTrue(any(s['control_error'] for s in snapshots))

    def test_database_busy_at_claim_waits_without_burning_attempt_or_restarting(self):
        ids=self.jobs(1);claim=self.catalog.claim;calls=0
        def locked(kinds):
            nonlocal calls
            calls+=1
            if calls==1:raise sqlite3.OperationalError('database is locked')
            return claim(kinds)
        with patch.object(self.catalog,'claim',side_effect=locked),patch('fetch.fetching.run_acquisition',side_effect=self.acquired) as run:
            fetching.fetch_loop(self.catalog,self.config,True,lambda:self.row(ids[0])['state']=='done')
        self.assertEqual(run.call_count,1);self.assertEqual(self.row(ids[0])['attempts'],1)

    def test_finished_future_survives_busy_persistence_without_another_download(self):
        ids=self.jobs(1);finish=self.catalog.finish;failed=False;snapshots=[];write=services.atomic_json
        def locked(jid,state,error=''):
            nonlocal failed
            if state=='done' and not failed:failed=True;raise sqlite3.OperationalError('database is locked')
            return finish(jid,state,error)
        def snapshot(path,data,**kw):
            if Path(path).name=='worker-fetch.json':snapshots.append(data)
            return write(path,data,**kw)
        with patch.object(self.catalog,'finish',side_effect=locked),patch('fetch.fetching.run_acquisition',side_effect=self.acquired) as run,patch('fetch.fetching.services.atomic_json',side_effect=snapshot):
            fetching.fetch_loop(self.catalog,self.config,False,lambda:False)
        self.assertTrue(failed);self.assertEqual(run.call_count,1);self.assertEqual(self.row(ids[0])['state'],'done')
        pending=[s for s in snapshots if s['completed_waiting_persistence']]
        self.assertTrue(pending);self.assertEqual(pending[0]['actual_active']['direct'],0)
        self.assertEqual(pending[0]['executor_capacity']['direct'],150)

    def test_pause_drains_existing_and_preserves_queued(self):
        ids=self.jobs();decisions=[Decision('fetch','ready','ready')]+[Decision('fetch','paused','user')]*5
        with patch('core.concurrency_control.apply',return_value={}),patch('core.control.pause_decision',side_effect=decisions),patch('fetch.fetching.run_acquisition',side_effect=self.acquired) as run:
            fetching.fetch_loop(self.catalog,self.config,True,lambda:False)
        self.assertEqual(run.call_count,1);self.assertEqual(self.row(ids[0])['state'],'done');self.assertEqual(self.row(ids[1])['state'],'queued')

    def test_policy_block_is_not_human_rejection_and_retains_target_clock(self):
        from fetch.fetch_policy import begin
        record=self.record();self.catalog.retain_discovery([record],{})
        key=self.catalog.pending_discovery()[0][0];pid=self.catalog.upsert(record)
        begin(self.catalog,self.catalog.get(pid),self.config,key)
        retry=time.time()+7200
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET state='terminal',retry_at=? WHERE paper_id=?",(retry,pid))
        jid=self.catalog.enqueue('acquire',pid,{'pending_key':key});job=self.row(jid);job['payload']=json.loads(job['payload'])
        fetching.complete_acquisition(self.catalog,self.config,job,{'skipped':True,'policy_blocked':True})
        with self.catalog.connect() as db:pending=dict(db.execute('SELECT * FROM discovery_pending WHERE key=?',(key,)).fetchone())
        self.assertEqual(pending['state'],'blocked_fetch');self.assertEqual(pending['retry_at'],retry);self.assertNotEqual(pending['error'],'人工忽略')
        self.assertEqual(self.catalog.get(pid)['decision'],'unreviewed')

    def test_future_completion_uses_original_target_retry_not_second_24h_clock(self):
        from fetch.fetch_policy import begin
        record=self.record();self.catalog.retain_discovery([record],{})
        key=self.catalog.pending_discovery()[0][0];pid=self.catalog.upsert(record)
        begin(self.catalog,self.catalog.get(pid),self.config,key)
        retry=time.time()+1800
        with self.catalog.connect() as db:db.execute('UPDATE fetch_targets SET retry_at=? WHERE paper_id=?',(retry,pid))
        jid=self.catalog.enqueue('acquire_fallback',pid,{'pending_key':key});job=self.row(jid);job['payload']=json.loads(job['payload'])
        fetching.complete_acquisition(self.catalog,self.config,job,{'available':False})
        with self.catalog.connect() as db:pending=dict(db.execute('SELECT * FROM discovery_pending WHERE key=?',(key,)).fetchone())
        self.assertEqual(pending['retry_at'],retry)

    def transport(self,*,content_type='application/pdf',concurrent_failure=False):
        provider='pdf:example.test'
        network.state_folder(self.root).joinpath('network-state.json').write_text(json.dumps({provider:{'retry_at':0,'failures':7,'updated':0,'code':403}}))
        class Response(io.BytesIO):
            headers={'Content-Type':content_type,'Content-Length':'14'}
            def geturl(self):return 'https://example.test/a.pdf'
            def read1(response,n):
                if concurrent_failure:
                    network.failed(provider,403,folder=self.root)
                return super(Response,response).read(n)
        with patch.dict(os.environ,{'PAPER_NETWORK_STATE_DIR':str(self.root)}),patch('core.services.public_url'),patch('fetch.net_limits.pace_arxiv'),patch('fetch.public_http.opener') as opener:
            opener.return_value.open.return_value=Response(b'%PDF-synthetic')
            if content_type=='text/html':
                with self.assertRaises(ValueError):services._download('https://example.test/a.pdf',self.root/'download.pdf')
            else:services._download('https://example.test/a.pdf',self.root/'download.pdf')
        return json.loads((self.root/'network-state.json').read_text())[provider]

    def test_finished_download_resets_old_failures(self):
        state=self.transport();self.assertEqual(state['failures'],0);self.assertEqual(state['retry_at'],0)

    def test_finished_download_does_not_clear_newer_concurrent_cooldown(self):
        state=self.transport(concurrent_failure=True);self.assertGreater(state['failures'],7);self.assertGreater(state['retry_at'],time.time())

    def test_html_challenge_does_not_clear_host_failures(self):
        self.assertEqual(self.transport(content_type='text/html')['failures'],7)

if __name__=='__main__':unittest.main()
