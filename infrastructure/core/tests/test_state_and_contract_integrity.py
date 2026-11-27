# Regression invariants retained from test_audit_1246.py; historical audit reports remain unchanged.
"""Independent local integration boundaries for the 12:46 audit."""
import io,json,os,sqlite3,subprocess,sys,tempfile,time,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
import pymupdf
from PIL import Image
from fetch import fetch_policy; from core import services; from review import web_feedback
from core.catalog import Catalog
from core.runtime import alive
from review.review_ledger import authorized, reserve
from reading.reading_contract import verified_completion, producer_fingerprint
from read.app import parser,analyzer
from read.app.context_budget import image_tokens
from read.app.evidence_quotes import verify_quotes
from read.app.atomic_io import atomic_json
from read.app.generation_state import generation_complete
from reading.tests.test_reading_safety import LocalFixture

class AuditBoundaries(LocalFixture):
    def target(self):
        record={'title':'OLED synthetic retry evidence','doi':'10.1000/retry','pdf_urls':['https://example.test/a.pdf']}
        self.catalog.retain_discovery([record],{});pid=self.catalog.upsert(record)
        with self.catalog.connect() as db:key=db.execute('SELECT key FROM discovery_pending').fetchone()[0]
        return pid,key

    def test_parent_lease_loss_bounds_native_sqlite_busy_wait(self):
        database=self.root/'blocked-native.db'
        lock=sqlite3.connect(database);lock.execute('CREATE TABLE ready(value INTEGER)');lock.commit();lock.execute('BEGIN EXCLUSIVE')
        read_fd,write_fd=os.pipe();process=None
        try:
            code="from core.runtime import watch_supervisor; import sqlite3,sys; watch_supervisor(int(sys.argv[1])); print('ready',flush=True); sqlite3.connect(sys.argv[2],timeout=30).execute('INSERT INTO ready VALUES(1)')"
            process=subprocess.Popen([sys.executable,'-c',code,str(read_fd),str(database)],cwd=Path.cwd(),pass_fds=(read_fd,),start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            os.close(read_fd);read_fd=None
            self.assertEqual(process.stdout.readline().strip(),b'ready')
            time.sleep(.2);started=time.monotonic();os.close(write_fd);write_fd=None
            process.wait(timeout=8)
            self.assertLess(time.monotonic()-started,7)
            self.assertNotEqual(process.returncode,0)
        finally:
            if read_fd is not None:os.close(read_fd)
            if write_fd is not None:os.close(write_fd)
            if process:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close();process.stderr.close()
            lock.rollback();lock.close()

    def test_periodic_recovery_obeys_batch_and_existing_queue_capacity(self):
        source=self.root/'original-evidence.pdf';source.write_bytes(b'original evidence')
        ids=[]
        for i in range(5):
            pid=self.catalog.upsert({'title':f'Synthetic periodic recovery {i}'})
            self.catalog.update(pid,asset_path=str(source),acquisition='available')
            job=self.catalog.enqueue('screen',pid);self.catalog.finish(job,'failed','temporary connection lost')
            with self.catalog.connect() as db:db.execute("UPDATE jobs SET updated='2000-01-01T00:00:00+00:00' WHERE id=?",(job,))
            ids.append(job)
        self.config.update(reading_recovery_batch_size=2,reading_queue_limit=3)
        for expected in (2,3,3):
            services.maintain_jobs(self.catalog,self.config,kinds=('screen',),audit_assets=False)
            with self.catalog.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE kind='screen' AND state='queued'").fetchone()[0],expected)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE state='failed'").fetchone()[0],2)

    def test_workflow_held_job_remains_unique_and_blocks_retry(self):
        pid=self.catalog.upsert({'title':'Synthetic queue hold'})
        original=self.catalog.enqueue('deep_read',pid,{'force':True})
        with self.catalog.connect() as db:db.execute("UPDATE jobs SET state='waiting_workflow' WHERE id=?",(original,))
        self.assertEqual(self.catalog.enqueue('deep_read',pid),original)
        with self.catalog.connect() as db:
            rows=list(db.execute("SELECT id FROM jobs WHERE paper_id=? AND kind='deep_read'",(pid,)))
            self.assertEqual(len(rows),1)
            db.execute("INSERT INTO jobs(id,kind,paper_id,payload,state,created,updated) VALUES('old-failure','deep_read',?,'{}','failed','old','old')",(pid,))
        with self.assertRaisesRegex(ValueError,'已经排队'):self.catalog.retry('old-failure')

    def test_recovery_policy_number_cannot_reopen_same_input_truncation(self):
        from reading import reading_recovery as recovery
        from reading.reading_bridge import reading_config, reading_input_hash
        from reading.reading_contract import file_digest
        source=self.root/'retry-source.pdf';source.write_bytes(b'original evidence')
        pid=self.catalog.upsert({'title':'Synthetic recovery boundary'})
        self.catalog.decide(pid,'deep_read')
        card_path=self.root/'retry-card.json'
        input_hash=reading_input_hash(file_digest(source),reading_config(self.config['model'],self.config.get('reading_domain_prompt'),model_digest='synthetic-weights-a'))
        card={'meta':{'reading_input_hash':input_hash,'evidence_coverage':{'truncated':True}}}
        card_path.write_text(json.dumps(card));self.catalog.update(pid,asset_path=str(source),card_path=str(card_path))
        failed=self.catalog.enqueue('deep_read',pid);self.catalog.finish(failed,'partial','输入截断')
        for revision in ('synthetic-A','synthetic-B'):
            with patch.object(recovery,'READING_POLICY',revision):
                result=recovery.activate(self.catalog,self.config)
            self.assertEqual(result['jobs'],[])
            self.assertEqual(result['skipped']['same_input_deterministic_failure'],1)
        card['meta']['reading_input_hash']='older-workflow-input';card_path.write_text(json.dumps(card))
        with patch.object(recovery,'READING_POLICY','synthetic-C'):
            result=recovery.activate(self.catalog,self.config)
            self.assertEqual(len(result['jobs']),1)
            self.assertTrue(recovery.activate(self.catalog,self.config)['already_activated'])
        self.assertEqual(self.catalog.get(pid)['card_path'],str(card_path))

    def test_target_retry_count_survives_new_job_ids_and_legacy_writes(self):
        pid,key=self.target();paper=self.catalog.get(pid)
        for i in range(6):
            self.assertTrue(fetch_policy.begin(self.catalog,paper,self.config,key))
            self.catalog.event(pid,'acquisition_pending',{'attempts':[{'kind':'timeout','error':'timeout'}]})
            fetch_policy.finish(self.catalog,pid,False,'fallback',self.config)
            with self.catalog.connect() as db:
                db.execute("UPDATE discovery_pending SET state='pending',retry_at=0 WHERE key=?",(key,))
                self.assertGreater(db.execute('SELECT retry_at FROM discovery_pending WHERE key=?',(key,)).fetchone()[0],time.time())
                if i<5:db.execute('UPDATE fetch_targets SET retry_at=0 WHERE paper_id=?',(pid,))
        self.assertFalse(fetch_policy.begin(self.catalog,paper,self.config,key))
        job=self.catalog.enqueue('acquire',pid)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT attempts FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()[0],6)
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0],'cancelled')
            self.assertEqual(db.execute('SELECT state FROM discovery_pending WHERE key=?',(key,)).fetchone()[0],'blocked_fetch')
        self.assertTrue(fetch_policy.begin(self.catalog,paper,self.config,key,manual=True))

    def test_new_url_recovers_target_and_failed_url_is_not_selected(self):
        pid,key=self.target();paper=self.catalog.get(pid)
        fetch_policy.begin(self.catalog,paper,self.config,key)
        a='https://example.test/a.pdf';b='https://example.test/b.pdf'
        fetch_policy.record_url(self.catalog,pid,a,ValueError('identity mismatch'))
        self.assertEqual(fetch_policy.select_urls(self.catalog,pid,[a,b],2),[b])
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET state='terminal' WHERE paper_id=?",(pid,))
        self.catalog.retain_discovery([{**paper['metadata'],'pdf_urls':[a,b]}],{})
        self.catalog.upsert({**paper['metadata'],'pdf_urls':[a,b]})
        self.assertTrue(fetch_policy.begin(self.catalog,self.catalog.get(pid),self.config,key))
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT attempts FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()[0],1)

    def test_legacy_done_without_pdf_cannot_be_reported_as_success(self):
        pid,key=self.target();fetch_policy.install(self.catalog)
        job=self.catalog.enqueue('acquire',pid);self.catalog.finish(job,'done')
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0],'deferred')

    def test_queue_prioritizes_auto_selection_and_revision_is_monotonic(self):
        first=self.catalog.enqueue('screen',self.catalog.upsert({'title':'OLED queue'}));auto=self.catalog.enqueue('auto_select')
        before=self.catalog.page()['revision']
        self.assertEqual(self.catalog.claim(('screen','auto_select'))['id'],auto)
        self.assertGreater(self.catalog.page()['revision'],before)
        self.assertEqual(self.catalog.claim(('screen',))['id'],first)

    def test_server_pagination_filters_entire_collection(self):
        for i in range(205):self.catalog.upsert({'title':f'OLED spectrum evidence {i}','channels':['arxiv']},candidate=True)
        page=self.catalog.page(100,100,'OLED spectrum',channel='arxiv')
        self.assertEqual(page['total'],205);self.assertEqual(len(page['papers']),100)
        self.assertEqual(self.catalog.page(query='spectrum nonexistent')['total'],0)
        self.assertEqual(self.catalog.page(tab='candidates',pdf_only=True)['total'],0)
        with self.assertRaises(ValueError):self.catalog.page(201)

    def test_abstract_and_identity_merge_preserves_better_evidence(self):
        pid=self.catalog.upsert({'title':'OLED identity evidence','abstract':'Detailed full abstract with conditions'})
        self.catalog.upsert({'title':'OLED identity evidence','abstract':'Short'})
        self.assertEqual(self.catalog.get(pid)['metadata']['abstract'],'Detailed full abstract with conditions')
        self.catalog.retain_discovery([{'title':'OLED no DOI identity','openalex_id':'W1'}],{})
        self.catalog.retain_discovery([{'title':'OLED no DOI identity','semantic_scholar_id':'S1'}],{})
        with self.catalog.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM discovery_pending WHERE state='quarantined'").fetchone()[0],0)
        self.catalog.retain_discovery([{'title':'OLED no DOI identity','openalex_id':'W2'}],{})
        with self.catalog.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM discovery_pending WHERE state='quarantined'").fetchone()[0],1)

    def test_actual_long_caption_and_independent_inventory_are_preserved(self):
        path=self.root/'long.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=900)
        page.insert_text((40,60),'OLED measurement title')
        page.draw_rect((40,120,500,260))
        caption='Fig. 1 (a) Measured OLED response and measurement conditions. '+('Panel labels identify excitation and emission spectra. '*15)
        self.assertGreater(len(caption),500)
        self.assertGreater(page.insert_textbox((40,290,550,650),caption,fontsize=10),0)
        doc.save(path);doc.close()
        paper=parser.parse_pdf(path,{'max_figures':20})
        self.assertEqual([f.number for f in paper.figures],[1]);self.assertGreater(len(paper.figures[0].caption),500)
        self.assertEqual(paper.extraction_audit['caption_candidates'][0]['number'],1)

    def test_png_jpeg_large_images_have_same_uncapped_budget(self):
        for name in ('image.png','image.jpg'):Image.new('RGB',(3840,3840),'white').save(self.root/name)
        self.assertEqual(image_tokens([self.root/'image.png']),25*1024)
        self.assertEqual(image_tokens([self.root/'image.jpg']),25*1024)

    def test_exact_sent_evidence_and_all_quotes_are_required(self):
        original='Measured emission was obtained at 77 K. The response increased at 300 K.'
        self.assertTrue(verify_quotes('Measured emission was obtained at 77 K.',original,original)[1])
        self.assertFalse(verify_quotes('1. Measured emission was obtained at 77 K.\n2. Invented response increased at 900 K.',original,original)[1])
        self.assertFalse(verify_quotes('The response increased at 300 K.',original,'Measured emission was obtained at 77 K.')[1])

    def test_complete_marker_changes_with_actual_producer_and_card_scope(self):
        card=self.complete_card();self.write_completion(card);self.assertIsNotNone(verified_completion(self.root))
        with patch('reading.reading_contract.producer_fingerprint',return_value='changed-workflow'):self.assertIsNone(verified_completion(self.root))
        card['meta']['input_budget_scope']=[{'truncated_fields':['related_text']}];self.assertFalse(generation_complete(card))
        card=self.complete_card();card['figures'][0]['evidence_quote']='';self.assertFalse(generation_complete(card))

    def test_actual_ollama_client_rejects_server_token_overflow(self):
        cfg=analyzer.load_config();cfg['schedule_config']=self.config;cfg['ollama_options']={'num_ctx':8192,'num_predict':2048}
        client=analyzer.OllamaClient(cfg)
        with patch('read.app.ollama_transport.chat',return_value={'prompt_eval_count':8000,'message':{'content':'confident output'}}):
            with self.assertRaises(ValueError):client.chat('A local synthetic prompt',retries=0)
        self.assertEqual(client.telemetry[0]['prompt_eval_count'],8000)

    def test_actual_screen_wiring_preserves_fulltext_over_18000_chars(self):
        doc=pymupdf.open()
        for i in range(13):
            page=doc.new_page();page.insert_textbox((40,40,550,760),'OLED synthetic original emission evidence. '*110,fontsize=10)
        path=self.root/'screen.pdf';doc.save(path);doc.close()
        pid=self.catalog.upsert({'title':'OLED synthetic emission evidence','venue':'Synthetic Journal'})
        self.catalog.update(pid,asset_path=str(path),acquisition='available')
        text,scope=services.evidence_input(self.catalog.get(pid));self.assertGreater(len(text),18000);self.assertEqual(text.basis,'fulltext')
        answer={'core_findings':'Synthetic finding','recommendation_reason':'Synthetic reason','relevance':5,'tags':[],'novelty':'Synthetic novelty','novelty_high':True,'evidence_quote':'OLED synthetic original emission evidence.'}
        def response(request,**kwargs):
            self.sent=json.loads(request.data)
            return io.BytesIO(json.dumps({'prompt_eval_count':18000,'message':{'content':json.dumps(answer)}}).encode())
        with patch('urllib.request.urlopen',side_effect=response):services.screen(self.catalog,self.config,pid)
        a=self.catalog.get(pid)['assessment'];self.assertEqual(a['evidence_basis'],'fulltext');self.assertFalse(a['evidence_unverified'])
        self.assertEqual(json.loads(self.sent['messages'][1]['content'])['evidence'],str(text))

    def test_external_gate_requires_receipt_and_direct_entry_is_blocked(self):
        manifest=self.root/'continuous-loop.json'
        for state in ({},{'external_submission_blocked':False,'state':'generating_and_reviewing'},{'external_submission_blocked':False,'state':'reviewing'}):
            self.assertFalse(authorized(state,self.catalog,manifest))
        with patch.object(web_feedback,'ROOT',self.root):
            with self.assertRaises(PermissionError):web_feedback.run_reviews(self.root)
        self.assertTrue(reserve(self.catalog,'synthetic','card-hash',self.root));self.assertFalse(reserve(self.catalog,'synthetic','card-hash',self.root))

    def test_atomic_write_failure_preserves_existing_json(self):
        path=self.root/'durable.json';atomic_json(path,{'version':1})
        with patch('read.app.atomic_io.os.replace',side_effect=OSError('synthetic disk fault')):
            with self.assertRaises(OSError):atomic_json(path,{'version':2})
        self.assertEqual(json.loads(path.read_text()),{'version':1});self.assertEqual(list(self.root.glob('.durable.json.*')),[])

    def test_alive_permission_denied_means_exists_but_invalid_pid_is_false(self):
        with patch('core.runtime.os.kill',side_effect=PermissionError):self.assertTrue(alive(123))
        for pid in (0,-1,None,'bad'):self.assertFalse(alive(pid))


    def test_child_process_group_timeout_terminates_grandchild(self):
        from core.process_runner import run
        file=self.root/'grandchild.pid'
        script="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);open(sys.argv[1],'w').write(str(p.pid));time.sleep(30)"
        with self.assertRaises(subprocess.TimeoutExpired):run([sys.executable,'-c',script,str(file)],timeout=.6,capture_output=True)
        pid=int(file.read_text());time.sleep(.1)
        self.assertFalse(alive(pid))

    def test_real_templates_transport_and_source_gate_are_wired(self):
        paper=self.parsed();paper.equations=[]
        cfg=analyzer.load_config();cfg['schedule_config']=self.config;cfg['render_dpi']=72;cfg['ollama_options']={'num_ctx':32768,'num_predict':2048}
        client=analyzer.OllamaClient(cfg);seen=[]
        def reply(url,payload,timeout,schedule):
            prompt=payload['messages'][1]['content'];seen.append(str(prompt))
            if '===图面信息===' in prompt:
                quote='Synthetic caption records a measured response.'
                content='\n'.join('==='+k+'===\n'+(quote if k=='原文依据' else 'Synthetic supplied observation') for k in ('图面信息','正文总结','详细解释','结果','一句话结果','原文依据'))
            elif 'C1 [' in prompt:
                import re
                ids=set(re.findall(r'C(\d+) \[',prompt));content='\n'.join(f'C{i}: direct_result - Original observation' for i in sorted(ids,key=int))
            elif 'DOI：' in prompt and '作者：' in prompt:content='标题: Synthetic evidence recovery study\n年份: 2026'
            else:content='Synthetic summary based on provided original evidence.'
            return {'message':{'content':content},'prompt_eval_count':1000,'done_reason':'stop'}
        with patch('read.app.ollama_transport.chat',side_effect=reply):card=analyzer.analyze_paper(paper,cfg,out_dir=self.root,client=client)
        self.assertEqual(card.figures[0].status,'ok');self.assertEqual(card.figures[0].evidence_status,'verified')
        self.assertTrue(any('Synthetic caption records' in p for p in seen))
        self.assertEqual(len(client.telemetry),len(seen))

    def test_channel_callback_failure_does_not_poison_other_channel(self):
        from fetch.discovery_bridge import discover
        def pages(config,on_page):
            on_page({'channel':'arxiv','pool':[],'warnings':['synthetic arxiv failure'],'positions':{},'raw':[]})
            on_page({'channel':'chemrxiv','pool':[{'title':'OLED synthetic channel','doi':'10.26434/chemrxiv-fixture-v1','channels':['chemrxiv']}],'warnings':[],'positions':{},'raw':[]})
        with patch('fetch.preprints.discover',side_effect=pages):result=discover({'state_dir':str(self.root),'topics':[],'seeds':[],'discovery_channels':['arxiv','chemrxiv']})
        self.assertEqual(result['channels']['arxiv']['state'],'failed');self.assertEqual(result['channels']['chemrxiv']['state'],'ok')
        self.assertEqual(result['warnings'].count('synthetic arxiv failure'),1)

    def test_interrupted_history_copy_does_not_become_valid_cache(self):
        from maintenance.history import preserve
        card=self.complete_card();(self.root/'card.json').write_text(json.dumps(card));(self.root/'source.pdf').write_bytes(b'original-source')
        with patch('maintenance.history.shutil.copyfile',side_effect=OSError('copy interrupted')):
            with self.assertRaises(OSError):preserve(self.root,'source')
        self.assertFalse(any(p.name[0]!='.' for p in (self.root/'history').iterdir()))
        snapshot=preserve(self.root,'source');proof=json.loads((snapshot/'snapshot-complete.json').read_text())
        self.assertIn('card.json',proof['files']);self.assertEqual(preserve(self.root,'source'),snapshot)

    def test_source_version_preserved_and_data_backup_disabled(self):
        from core.workflow_versions import capture, backup_state
        root=self.root/'project';(root/'pipeline').mkdir(parents=True);(root/'pipeline/example.py').write_text('VALUE=1\n')
        version=capture(self.config,root=root);self.assertEqual(capture(self.config,root=root),version)
        self.assertEqual((version/'pipeline/example.py').read_text(),'VALUE=1\n')
        self.catalog.upsert({'title':'OLED backup evidence'})
        with self.assertRaisesRegex(RuntimeError,'禁用数据备份'):
            backup_state(self.config,root=root)
        self.assertFalse((Path(self.config['catalog_path']).parent/'backups').exists())

    def test_structured_truncation_blocks_same_input_automatic_retry(self):
        from reading.reading_failures import diagnostics
        card=self.complete_card();card['meta']['evidence_coverage']['truncated']=True
        self.assertFalse(generation_complete(card));self.assertTrue(diagnostics(card)['automatic_retry_blocked'])

    def test_resume_cannot_discard_earlier_input_truncation(self):
        from reading.tests.test_reading_safety import FakeClient
        paper=self.parsed();paper.equations=[];client=FakeClient()
        with patch.object(analyzer,'_render_prompt',side_effect=lambda name,*args,**kwargs:name):
            first=analyzer.analyze_paper(paper,out_dir=self.root,client=client)
            first.meta['input_budget_scope']=[{'stage':'key_findings','truncated_fields':['conclusion']}]
            resumed=analyzer.analyze_paper(paper,out_dir=self.root,client=client,base_card=first)
        self.assertTrue(any(r.get('truncated_fields') for r in resumed.meta['input_budget_scope']))
        self.assertFalse(generation_complete(resumed.to_dict()))
