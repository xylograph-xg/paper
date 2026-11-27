# Regression invariants retained from test_audit_0310.py; historical audit reports remain unchanged.
"""Independent synthetic boundaries for the 03:10 audit, no production inference."""
import gzip
import io
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
import pymupdf
from core.catalog import Catalog, ROOT, load_config
from core import services; from review import web_feedback as feedback
from reading.reading_contract import file_digest, verified_completion
from review.review_protection import protection
from review.card_evaluation import RUBRIC, contact_sheets
from fetch.public_http import dial_public
from read.app.generation_state import generation_complete,METADATA_STAGES
from reading.tests.test_reading_safety import LocalFixture,FakeClient,rb


def compete(database,output):
    catalog=Catalog(database)
    for i in range(12):catalog.upsert({'title':f'Synthetic identity {i}','doi':f'10.1000/concurrent{i}'},candidate=True)
    claimed=[]
    while (job:=catalog.claim(('screen',))):
        claimed.append(job['id']);catalog.finish(job['id'],'done')
    output.put(claimed)


class GenerationAudit(LocalFixture):
    def test_zero_evidence_and_coverage_mismatch_never_complete(self):
        card=self.complete_card();card['figures']=[]
        self.assertFalse(generation_complete(card))
        card=self.complete_card();card['meta']['evidence_coverage']['figures']=2
        self.assertFalse(generation_complete(card))
        card=self.complete_card();card['equations']=[dict(card['figures'][0])]
        self.assertFalse(generation_complete(card))

    def test_completed_cache_and_changed_weights_use_real_bridge_contract(self):
        self.pdf();client=FakeClient();request={'out_dir':str(self.root),'model':self.config['model']}
        with (patch.object(rb.analyzer,'OllamaClient',return_value=client),
              patch.object(rb,'render_review_prompt',side_effect=lambda name,*a,**kw:name),
              patch.object(rb,'supplement_quantities',return_value=[])):
            rb.process(request);self.assertIsNotNone(verified_completion(self.root))
            first=(self.root/'card.json').read_bytes();client.calls.clear()
            self.assertTrue(rb.process(request)['cached']);self.assertEqual(client.calls,[])
            self.assertEqual(first,(self.root/'card.json').read_bytes())
            with patch('core.model_identity.resolve_identity',return_value='changed-weights'):
                rb.process(request)
            self.assertIn('figure',client.calls);self.assertIn('paper_info',client.calls)

    def test_same_number_on_same_page_has_different_export_paths(self):
        paper=self.parsed()
        equations=[rb.parser.Equation(label='Eq. 2',number=2,page=0,bbox=[40,y,200,y+20],text='x = y',group_numbers=[2]) for y in (610,680)]
        self.assertNotEqual(equations[0].folder_name,equations[1].folder_name)
        self.assertEqual(equations[0].folder_name,rb.analyzer._equation_card(paper,equations[0]).folder_name)

    def test_short_report_fallback_preserves_real_source_scope(self):
        paper=self.parsed();paper.sections=[];client=FakeClient()
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**kw:name):
            card=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client)
        self.assertIn('未识别',card.meta['metadata_source_scope']['conclusion'])
        self.assertEqual(card.meta['generation']['stages']['conclusion']['state'],'ok')

    def test_corrupted_screenshot_invalidates_marker(self):
        card=self.complete_card();self.write_completion(card)
        self.assertIsNotNone(verified_completion(self.root))
        Path(card['figures'][0]['image_path']).write_bytes(b'changed')
        self.assertIsNone(verified_completion(self.root))


class OutputAudit(unittest.TestCase):
    def test_enriched_metadata_prompt_fits_budget_and_records_real_scope(self):
        from types import SimpleNamespace
        from reading.prompt_overlays import render_review_prompt
        parsed=SimpleNamespace(figures=[SimpleNamespace(caption_page=0,label='Fig. 1',caption='真实图注与适用条件。'*1800,candidates=[])],page_texts=['Table 1\n'+'measured condition '*600])
        values={'abstract':'measurement '*500,'introduction':'实验限制条件。'*900,'conclusion':'Author conclusions '*500}
        original=values.copy();scopes={}
        prompt=render_review_prompt('key_findings',values,rb.analyzer.PROMPT_DIR,rb.analyzer._render_prompt,parsed,input_budget=7500,scopes=scopes)
        from read.app.context_budget import estimate_tokens
        self.assertLessEqual(estimate_tokens(prompt),7500)
        self.assertEqual(scopes['key_findings'][0]['budget_unit'],'estimated_tokens')
        self.assertIn('仅提供原文片段',prompt)
        self.assertTrue(scopes['key_findings'][0]['truncated'])
        self.assertGreater(scopes['key_findings'][0]['source_bytes'],7500)
        self.assertEqual(values,original)
        self.assertEqual(parsed.figures[0].caption,'真实图注与适用条件。'*1800)

    def test_format_and_quote_are_both_required(self):
        with self.assertRaises(ValueError):rb.analyzer.split_marked('An unrelated confident summary.')
        text='===正文总结===\nSummary\n===详细解释===\nDetails\n**结果**\nStill detail\n===结果===\nA result'
        self.assertIn('Still detail',rb.analyzer.split_marked(text)['详细解释'])
        parts={k:'supplied source observation' for k in ('图面信息','正文总结','详细解释','结果','一句话结果','原文依据')}
        self.assertEqual(rb.analyzer.validate_parts(parts,'A supplied source observation.','图面信息'),'supplied source observation')
        parts['原文依据']='a fabricated scientific observation'
        with self.assertRaises(ValueError):rb.analyzer.validate_parts(parts,'A supplied source observation.','图面信息')
        with self.assertRaises(ValueError):rb.analyzer.split_marked('===结果===\nfirst\n===结果===\nsecond')

    def test_classification_spaces_and_duplicate_indices(self):
        self.assertEqual(rb.analyzer.parse_classification('C1: direct result - quoted observation',1)[1][0],'direct_result')
        for raw in ('C1: background\nC1: interpretation','C2: background','C1: invented_label'):
            with self.assertRaises(ValueError):rb.analyzer.parse_classification(raw,1)

    def test_reformat_cannot_drop_critical_or_missing_inputs(self):
        original={'sample_kind':'mixed','scores':{k:9 for k in RUBRIC},'missing_inputs':['unreadable panel'],
                  'issues':[{'severity':'critical','finding':'Wrong source','evidence':'Page 1'}],'verdict':'revise'}
        corrected={**original,'issues':[],'missing_inputs':[]}
        class Locator:
            def count(self):return 0
        class Page:
            def locator(self,*args):return Locator()
        class GPT:
            page=Page()
            def ask(self,*args,**kwargs):return json.dumps(corrected)
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td)
            with self.assertRaisesRegex(ValueError,'改变了'):
                feedback.parse_or_reformat(GPT(),json.dumps(original)[:-1]+',}','mixed',directory,{},directory/'attempt.json',1)

    def test_model_tag_resolves_digest_and_rejects_unknown_weights(self):
        from core.model_identity import resolve_identity
        def response(digest):return io.BytesIO(json.dumps({'models':[{'name':'synthetic:latest','digest':digest}]}).encode())
        with patch('core.model_identity.urllib.request.urlopen',side_effect=lambda *a,**kw:response('a')):
            self.assertEqual(resolve_identity({'name':'synthetic','base_url':'http://local.test'}),'a')
        with patch('core.model_identity.urllib.request.urlopen',side_effect=lambda *a,**kw:response(None)):
            with self.assertRaises(ValueError):resolve_identity({'name':'synthetic','base_url':'http://local.test'})

    def test_xml_entity_and_payload_limits_are_rejected(self):
        from fetch.preprints import safe_xml
        for raw in (b'<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>',b'x'*(8*1024*1024+1)):
            with self.assertRaises(ValueError):safe_xml(raw)


class RealBoundaries(LocalFixture):
    def test_standalone_model_transport_cancels_at_window_boundary(self):
        from read.app.ollama_transport import chat
        from core.model_schedule import ModelWindowClosed
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));time.sleep(2)
                try:self.send_response(200);self.end_headers();self.wfile.write(b'{"message":{"content":"synthetic"}}')
                except OSError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        started=time.monotonic()
        def require(*args):
            if time.monotonic()-started>.2:raise ModelWindowClosed('synthetic midnight')
        try:
            with patch('core.model_schedule.require_allowed',side_effect=require):
                with self.assertRaises(ModelWindowClosed):chat(f'http://127.0.0.1:{server.server_port}',{},10,self.config)
            self.assertLess(time.monotonic()-started,1.5)
        finally:server.shutdown();server.server_close();thread.join()

    def test_separate_processes_upsert_and_claim_atomically(self):
        for i in range(20):self.catalog.enqueue('screen',self.catalog.upsert({'title':f'Screen target {i}'}))
        context=multiprocessing.get_context('spawn');output=context.Queue()
        workers=[context.Process(target=compete,args=(str(self.catalog.path),output)) for _ in range(3)]
        try:
            # Browser adapters may prepend another repository with a tests package.
            # Spawned workers must import this repository's synthetic fixture.
            with patch.object(sys,'path',[str(ROOT),*[p for p in sys.path if p!=str(ROOT)]]):
                for worker in workers:worker.start()
            results=[output.get(timeout=20) for worker in workers]
            for worker in workers:worker.join(10);self.assertEqual(worker.exitcode,0)
        finally:
            for worker in workers:
                if worker.is_alive():worker.terminate();worker.join()
        claimed=[value for batch in results for value in batch]
        self.assertEqual(len(claimed),20);self.assertEqual(len(set(claimed)),20)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM papers WHERE candidate_order IS NOT NULL').fetchone()[0],12)

    def test_real_acquisition_and_discovery_subprocess_boundaries(self):
        from fetch.fetching import run_acquisition
        self.config.update(require_mounted_volume=False)
        source=self.pdf();pid=self.catalog.upsert({'title':'Synthetic evidence recovery study'})
        job={'id':'synthetic-acquisition','kind':'import','paper_id':pid,'payload':{'source':str(source),'manual':True}}
        result=run_acquisition(self.catalog,self.config,job)
        self.assertTrue(result['available']);self.assertTrue(Path(self.catalog.get(pid)['asset_path']).exists())
        discovered=services.bridge('fetch.discovery_bridge',{'state_dir':str(self.root),'queries':[],'seeds':[],'preprints':{}},timeout=10)
        self.assertEqual(discovered['pool'],[]);self.assertIn('positions',discovered)

    def test_storage_disappears_and_write_failure_never_falls_back(self):
        from core.storage_health import status
        self.config['archive_volume']=str(self.root/'missing-volume')
        self.config['archive_root']=str(self.root/'missing-volume/archive')
        self.assertEqual(status(self.config)['state'],'waiting_storage')
        with self.assertRaises(services.StorageUnavailable):services.store_asset(self.pdf(),self.config)
        self.config.update(archive_volume=str(self.root),archive_root=str(self.root/'archive'),require_mounted_volume=False)
        with patch('core.services.os.replace',side_effect=OSError(28,'No space left')):
            with self.assertRaises(OSError):services.store_asset(self.root/'source.pdf',self.config)
        self.assertEqual(list((self.root/'archive').glob('assets/*/source.pdf')),[])

    def test_dns_rebinding_is_checked_at_connect_without_global_dns_patch(self):
        with patch('fetch.public_http.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]),patch('fetch.public_http.socket.socket') as sockets:
            with self.assertRaises(ValueError):dial_public(('public.example',80))
            sockets.assert_not_called()

    def test_real_slow_http_body_obeys_shared_deadline(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','application/pdf');self.end_headers()
                try:
                    for _ in range(100):self.wfile.write(b'x'*100);self.wfile.flush();time.sleep(.03)
                except OSError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            started=time.monotonic()
            with (patch('core.services.public_url'),patch('fetch.public_http.opener',return_value=urllib.request.build_opener()),
                  patch.dict(os.environ,{'PAPER_ACQUISITION_DEADLINE':str(started+12.35),'PAPER_NETWORK_STATE_DIR':str(self.root)})):
                with self.assertRaises((TimeoutError,OSError)):services.download(f'http://127.0.0.1:{server.server_port}/paper',self.root/'slow.pdf')
            self.assertLess(time.monotonic()-started,1.5)
        finally:server.shutdown();server.server_close();thread.join()

    def test_first_window_quota_remains_one_after_more_than_ten_candidates(self):
        ids=[self.catalog.upsert({'title':f'Candidate {i}','doi':f'10.1000/quota{i}'},candidate=True) for i in range(201)]
        self.assertTrue(self.catalog.reserve_auto(ids[0],{},1,3))
        self.assertFalse(self.catalog.reserve_auto(ids[11],{},1,3))
        for index in (100,101,102):self.assertTrue(self.catalog.reserve_auto(ids[index],{},1,3))
        self.assertFalse(self.catalog.reserve_auto(ids[103],{},1,3))

    def test_auto_select_failure_recovers_on_its_own_lane(self):
        from datetime import datetime,timezone,timedelta
        jid=self.catalog.enqueue('auto_select');self.catalog.claim(('auto_select',));self.catalog.finish(jid,'failed','Synthetic fault')
        with self.catalog.connect() as db:db.execute('UPDATE jobs SET updated=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),jid))
        services.maintain_jobs(self.catalog,self.config,kinds=('auto_select',),audit_assets=False)
        self.assertEqual(next(x for x in self.catalog.jobs() if x['id']==jid)['state'],'queued')

    def test_bad_provider_shape_is_normalized_or_quarantined_individually(self):
        from core.record_contract import normalize
        self.assertEqual(normalize({'title':'OLED study','abstract':['measured','OLED response']})['abstract'],'measured OLED response')
        for row in ({'title':'study','abstract':{'bad':'shape'}},{'title':'study','channels':7},{'title':False}):
            with self.assertRaises(ValueError):normalize(row)

    def test_many_visuals_fit_attachment_budget_without_shrinking_pages(self):
        from PIL import Image
        source=self.root/'synthetic.png';Image.new('RGB',(80,80),'white').save(source)
        names=contact_sheets({'figures':[{'label':str(i),'image_path':str(source)} for i in range(61)]},self.root)
        self.assertEqual(names,['card-visuals.pdf'])
        with pymupdf.open(self.root/names[0]) as pdf:self.assertEqual(len(pdf),11);self.assertEqual(pdf[0].rect.width,2000)

    def test_diagnostic_retention_preserves_failed_and_active_evidence(self):
        from maintenance.artifact_retention import maintain
        completed=self.catalog.enqueue('screen');self.catalog.finish(completed,'done')
        failed=self.catalog.enqueue('screen');self.catalog.finish(failed,'failed','fault')
        logs=self.root/'logs';logs.mkdir();old=time.time()-9*86400
        for jid in (completed,failed):p=logs/('acquire-'+jid+'.log');p.write_bytes(b'original diagnosis');os.utime(p,(old,old))
        archived=maintain(self.catalog);self.assertEqual(len(archived),1)
        with gzip.open(archived[0]['archive'],'rb') as stream:self.assertEqual(stream.read(),b'original diagnosis')
        self.assertTrue((logs/('acquire-'+failed+'.log')).exists())

    def test_raw_retention_preserves_bytes_and_updates_run_reference(self):
        from maintenance.artifact_retention import maintain, read_raw
        raw=self.root/'archive/raw/synthetic.json';raw.parent.mkdir(parents=True);raw.write_text('{"records": [1, 2, 3]}')
        digest=file_digest(raw);old=time.time()-9*86400;os.utime(raw,(old,old))
        with self.catalog.connect() as db:db.execute('INSERT INTO runs VALUES(?,?,?)',('synthetic','2026-01-01',json.dumps({'raw_file':str(raw)})))
        maintain(self.catalog,config=self.config)
        self.assertEqual(read_raw(raw),{'records':[1,2,3]})
        with self.catalog.connect() as db:result=json.loads(db.execute('SELECT result FROM runs').fetchone()[0])
        self.assertTrue(result['raw_file'].endswith('.json.gz'))
        manifest=json.loads(Path(result['raw_file']).with_suffix('.sha256.json').read_text());self.assertEqual(manifest['sha256'],digest)


class ReviewProtection(LocalFixture):
    def test_actual_review_receipt_protects_card_without_stamping_scientific_metadata(self):
        self.pdf();card=self.complete_card();card.pop('figures');card['figures']=[]
        card_path=self.root/'card.json';card_path.write_text(json.dumps(card));before=card_path.read_bytes()
        run=self.root/'data/quality_reviews/synthetic';directory=run/'mixed';directory.mkdir(parents=True)
        (directory/'prompt.txt').write_text('synthetic independent review');(directory/'paper-review.pdf').write_bytes(b'review copy')
        sample={'kind':'mixed','paper_id':'synthetic','card_sha256':file_digest(card_path),'source_sha256':file_digest(self.root/'source.pdf'),
                'packet_files':['paper-review.pdf'],'review_pdf_sha256':file_digest(directory/'paper-review.pdf'),
                'input_hashes':{n:file_digest(directory/n) for n in ('paper-review.pdf','prompt.txt')}}
        manifest=self.root/'review-authorization.json'
        feedback.save_json(manifest,{'state':'authorized_review','external_submission_blocked':False,'samples':{'mixed':'synthetic'}})
        feedback.save_json(run/'run.json',{'samples':[sample]})
        answer={'sample_kind':'mixed','scores':{key:9 for key in RUBRIC},'issues':[],'missing_inputs':[],'verdict':'pass'}
        class Locator:
            def count(self):return 0
        class Page:
            url='https://chatgpt.com/c/synthetic-review'
            def locator(self,*args):return Locator()
            def screenshot(self,**kwargs):pass
        class GPT:
            page=Page()
            def verify_settings(self):return {'model':'synthetic reviewer'}
            def ask(self,*args,**kwargs):return json.dumps(answer)
        @contextmanager
        def factory():yield GPT()
        with patch.object(feedback,'ROOT',self.root), patch.object(feedback,'require_current_legacy_control'), patch('review.review_ledger.authorized',return_value=True), patch('review.review_ledger.catalog_for',return_value=self.catalog):
            feedback.run_reviews(run,factory=factory,manifest_path=manifest)
        with patch('review.review_protection.REVIEWS_ROOT',run.parent):
            self.assertTrue(protection(self.root)['pass'])
            with patch.object(rb.analyzer,'OllamaClient') as model:
                result=rb.process({'out_dir':str(self.root),'model':self.config['model']})
            self.assertTrue(result['cached']);model.assert_not_called()
            (self.root/'source.pdf').write_bytes(b'changed source')
            self.assertTrue(protection(self.root)['source_changed'])
            self.assertFalse(protection(self.root)['pass'])
        self.assertEqual(card_path.read_bytes(),before);self.assertNotIn('quality_review',json.loads(before)['meta'])
