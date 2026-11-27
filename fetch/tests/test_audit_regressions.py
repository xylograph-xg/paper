"""Fault injection for the external fetch audit. Temporary files only."""
import gzip
import io
import threading
import time
import unittest
from unittest.mock import patch

from fetch.tests import test_seed_expansion as seed_fixtures
from fetch.tests import test_manual_seed_lineage as lineage_fixtures
from fetch import fetchpdf_bridge as bridge
from fetch.seed_expansion import expand_when_idle
from core.api import paths__WorkspacePath as Path


class SeedAudit(unittest.TestCase):
    setUp=seed_fixtures.SeedExpansion.setUp
    paper=seed_fixtures.SeedExpansion.paper
    def test_slow_file_io_allows_other_writer_and_detects_changed_decision(self):
        pid=self.paper(90)
        original=Path.read_bytes
        observed=[]
        def slow_read(path):
            if str(path).endswith('.pdf'):
                def writer():
                    with self.catalog.connect() as db:
                        db.execute("UPDATE papers SET decision='reject' WHERE id=?",(pid,))
                    observed.append(True)
                worker=threading.Thread(target=writer);worker.start();worker.join(2)
                self.assertFalse(worker.is_alive(), 'file read holds a DB write lock')
            return original(path)
        with patch.object(Path,'read_bytes',slow_read):
            result=expand_when_idle(self.catalog,self.config)
        self.assertTrue(observed)
        self.assertEqual(result['state'],'candidate_changed')
        self.assertFalse(self.catalog.get(pid)['seed'])


class LineageAudit(unittest.TestCase):
    setUp=lineage_fixtures.ManualLineageTests.setUp
    tearDown=lineage_fixtures.ManualLineageTests.tearDown
    paper=lineage_fixtures.ManualLineageTests.paper
    register=lineage_fixtures.ManualLineageTests.register
    def test_retraction_removes_stale_lineage_and_no_roots_clears(self):
        from fetch import manual_seed_lineage as lineage
        root=self.paper('root');self.register(root)
        child=self.catalog.upsert({'title':'child','doi':'10.1000/child','discovered_from_seed_dois':['10.1000/root']})
        self.assertEqual(lineage.reconcile(self.catalog)['derived'],1)
        with self.catalog.connect() as db:db.execute('DELETE FROM seed_discovery_origins WHERE paper_id=?',(child,))
        self.assertEqual(lineage.reconcile(self.catalog)['derived'],0)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO manual_seed_lineage VALUES(?,?,?)',(child,root,time.time()))
            db.execute('DELETE FROM manual_seed_roots')
        self.assertEqual(lineage.reconcile(self.catalog)['derived'],0)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM manual_seed_lineage').fetchone()[0],0)


class StreamingAudit(unittest.TestCase):
    def guarded(self,response,limit=1024):
        import requests
        from contextlib import ExitStack
        with ExitStack() as stack:
            transport=stack.enter_context(patch('requests.sessions.Session.send',**({'side_effect':response} if isinstance(response,list) else {'return_value':response})))
            for name in ('core.services.public_url','fetch.public_http.requests_adapter','fetch.network.ready',
                         'fetch.network.succeeded','fetch.network.pace','fetch.net_limits.pace_arxiv'):
                stack.enter_context(patch(name))
            stack.enter_context(patch('fetch.acquisition_budget.remaining',return_value=120))
            stack.enter_context(patch.object(bridge,'RESPONSE_LIMIT',limit))
            stack.enter_context(patch.object(bridge,'METADATA_LIMIT',limit))
            original=bridge.install_http_guards()
            try:
                return requests.Session().send(requests.Request('GET','https://example.test/paper').prepare()),transport
            finally:requests.sessions.Session.send=original

    def response(self,data,headers=None):
        import requests
        from urllib3.response import HTTPResponse
        response=requests.Response();response.request=requests.Request('GET','https://example.test/paper').prepare();response.status_code=200;response.headers=requests.structures.CaseInsensitiveDict(headers or {})
        response.raw=HTTPResponse(body=io.BytesIO(data),headers=headers or {},preload_content=False,enforce_content_length=False)
        return response

    def test_unknown_or_false_length_is_bounded(self):
        for headers in ({},{'Content-Length':'1'},{'Transfer-Encoding':'chunked'}):
            response=self.response(b'x'*2000,headers)
            with self.assertRaises(ValueError):self.guarded(response)
            self.assertTrue(response.raw.closed)

    def test_real_session_bounds_redirect_before_preparing_next_request(self):
        import requests
        from contextlib import ExitStack
        first=self.response(b'x'*2000,{'Location':'https://example.test/final'})
        first.status_code=302;first.url='https://example.test/paper'
        calls=[]
        class Adapter(requests.adapters.BaseAdapter):
            def send(self,request,**kwargs):
                calls.append(request.url)
                first.request=request
                return first
            def close(self):pass
        with ExitStack() as stack:
            for name in ('core.services.public_url','fetch.network.ready','fetch.network.succeeded',
                         'fetch.net_limits.pace_arxiv'):
                stack.enter_context(patch(name))
            stack.enter_context(patch('fetch.public_http.requests_adapter',return_value=Adapter()))
            stack.enter_context(patch('fetch.acquisition_budget.remaining',return_value=120))
            stack.enter_context(patch.object(bridge,'RESPONSE_LIMIT',1024))
            original=bridge.install_http_guards()
            try:
                with self.assertRaises(ValueError):requests.Session().get('https://example.test/paper')
            finally:requests.sessions.Session.send=original
        self.assertEqual(calls,['https://example.test/paper'])
        self.assertTrue(first.raw.closed)

    def test_redirect_hops_are_read_with_limits_before_following(self):
        first=self.response(b'redirect',{'Location':'https://example.test/final'})
        first.status_code=302;first.url='https://example.test/paper'
        final=self.response(b'%PDF-final')
        result,transport=self.guarded([first,final])
        self.assertEqual(result.content,b'%PDF-final')
        self.assertEqual(len(result.history),1)
        self.assertEqual(transport.call_count,2)
        first=self.response(b'x'*2000,{'Location':'https://example.test/final'})
        first.status_code=302;first.url='https://example.test/paper'
        with self.assertRaises(ValueError):self.guarded([first,final])

    def test_decoded_gzip_is_bounded_and_small_pdf_json_work(self):
        response=self.response(gzip.compress(b'x'*2000),{'Content-Encoding':'gzip'})
        with self.assertRaises(ValueError):self.guarded(response)
        for data,headers in [(b'%PDF-small',{}),(b'{"a":1}',{'Content-Type':'application/json'})]:
            result,transport=self.guarded(self.response(data,headers))
            self.assertEqual(result.content,data)
            self.assertTrue(transport.call_args.kwargs['stream'])
            self.assertFalse(transport.call_args.kwargs['allow_redirects'])


class LaunchAudit(unittest.TestCase):
    def test_two_start_callers_share_one_confirmed_keeper(self):
        import tempfile
        from fetch import fetch_service
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            config={'catalog_path':str(Path(folder)/'catalog.sqlite')}
            running=threading.Event();barrier=threading.Barrier(2);results=[];errors=[]
            process=Mock();process.poll.return_value=None
            def spawn(*args,**kwargs):
                running.set()
                return process
            def state(_):return {'state':'running' if running.is_set() else 'stopped'}
            def caller():
                barrier.wait()
                try:results.append(fetch_service.start(config))
                except Exception as error:errors.append(error)
            with patch('fetch.fetch_service.paused',return_value=False),patch('fetch.fetch_service.status',side_effect=state),patch('fetch.fetch_service.subprocess.Popen',side_effect=spawn) as popen:
                workers=[threading.Thread(target=caller) for _ in range(2)]
                for worker in workers:worker.start()
                for worker in workers:worker.join(3)
                self.assertFalse(any(worker.is_alive() for worker in workers))
                self.assertEqual(errors,[]);self.assertEqual(len(results),2)
                self.assertEqual(popen.call_count,1)
