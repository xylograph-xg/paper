"""Synthetic PDF and fault tests for the generic reading and retry contracts."""
import hashlib
import io
import json
import tempfile
import threading
import time
import os
import signal
import unittest
from datetime import datetime,timezone,timedelta
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import pymupdf
from reading import reading_bridge as rb
from core.catalog import Catalog, ROOT
from reading.reading_contract import READING_CONTRACT_VERSION, verified_completion, file_digest
from review.eligibility import eligible
from core.services import maintain_jobs, screen
from read.app.generation_state import METADATA_STAGES,generation_complete


class LocalFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.db')
        self.config=json.loads((ROOT/'config/first_round.json').read_text())
        self.config['local_models_enabled']=True  # Explicit synthetic legacy-mode fixture.
        self.config.update(catalog_path=str(self.catalog.path),require_mounted_volume=False,
                           archive_volume=str(self.root),archive_root=str(self.root/'archive'))
        self.config['model']['autostart']=False
        from core.model_schedule import configure
        configure(self.config,allow_minutes=60)
        identity=patch('core.model_identity.resolve_identity',return_value='synthetic-weights-a')
        identity.start();self.addCleanup(identity.stop)
    def tearDown(self):self.temp.cleanup()
    def pdf(self):
        path=self.root/'source.pdf';doc=pymupdf.open();page=doc.new_page()
        page.insert_text((40,50),'Synthetic evidence recovery study',fontsize=16)
        for y,name in [(100,'Abstract'),(270,'Introduction'),(470,'Discussion')]:
            page.insert_text((40,y),name,fontsize=14)
            text=('This synthetic paragraph records a measurement and explains the methods and limitations. ')*4
            page.insert_textbox((40,y+20,550,y+130),text,fontsize=11)
        page.draw_rect((40,620,260,690));page.insert_text((40,730),'Fig. 1 Synthetic caption records a measured response.',fontsize=11)
        doc.save(path);doc.close();return path
    def parsed(self):
        path=self.pdf();paper=rb.parser.parse_pdf(path,rb.analyzer.load_config())
        rb.repair_sections(paper,rb.parser);return paper
    def complete_card(self):
        image=self.root/'figure.png';image.write_bytes(b'synthetic evidence image')
        return {'title':'synthetic','meta':{'reading_contract_version':READING_CONTRACT_VERSION,'evidence_coverage':{'figures':1,'equations':0},
            'metadata_generation_ok':True,'generation':{'schema_version':2,'stages':{s:{'state':'ok'} for s in METADATA_STAGES}}},
            'figures':[{'number':1,'label':'Fig. 1','caption':'Synthetic caption','status':'ok','classification_status':'not_applicable','evidence_status':'verified','evidence_quote':'Synthetic original evidence','image_path':str(image)}],'equations':[],'warnings':[]}
    def write_completion(self,card):
        from reading.reading_contract import producer_fingerprint
        card['meta']['producer_fingerprint']=producer_fingerprint();card['meta']['reading_input_hash']='synthetic-input';card['meta']['model_digest']='synthetic-weights-a'
        (self.root/'card.json').write_text(json.dumps(card));(self.root/'source.pdf').write_bytes(b'fixture')
        marker={'reading_contract_version':READING_CONTRACT_VERSION,'generation_complete':True,
                'completed_at':'2026-10-06T00:00:00+00:00','card_sha256':file_digest(self.root/'card.json'),
                'source_sha256':file_digest(self.root/'source.pdf')}
        marker.update(producer_fingerprint=producer_fingerprint(),reading_input_hash='synthetic-input',model_digest='synthetic-weights-a')
        marker['evidence_sha256']={str(Path(item['image_path']).relative_to(self.root)):file_digest(item['image_path']) for item in card.get('figures',[])+card.get('equations',[]) if item.get('image_path') and Path(item['image_path']).is_file() and Path(item['image_path']).is_relative_to(self.root)}
        (self.root/'quality-ready.json').write_text(json.dumps(marker));return marker


class FakeClient:
    model='synthetic';base_url='http://local.test'
    def __init__(self,fail=None):self.fail=set(fail or []);self.calls=[]
    def chat(self,prompt,**kwargs):
        self.calls.append(prompt)
        if prompt in self.fail:raise RuntimeError('HTTP 503 synthetic transient fault')
        return {'paper_info':'标题: Synthetic evidence recovery study\n年份: 2026',
                'key_findings':'Synthetic findings from supplied evidence.\n一句话结果\nSynthetic result.',
                'introduction':'Synthetic introduction summary.',
                'conclusion':'Synthetic discussion summary.',
                'figure':'===图面信息===\nSynthetic image.\n===正文总结===\nSynthetic figure evidence.\n===详细解释===\nSynthetic explanation.\n===结果===\nSynthetic result.\n===一句话结果===\nSynthetic.\n===原文依据===\nSynthetic caption',
                'equation':'===量清单===\nSynthetic quantity.\n===正文总结===\nSynthetic equation evidence.\n===详细解释===\nSynthetic relation.\n===结果===\nSynthetic relation.\n===一句话结果===\nSynthetic.\n===原文依据===\nx = y'}.get(prompt,'')


class StageRecovery(LocalFixture):
    def test_model_change_does_not_reuse_successful_stages_of_partial_card(self):
        self.pdf();client=FakeClient(['paper_info']);request={'out_dir':str(self.root),'model':dict(self.config['model'])}
        with (patch.object(rb.analyzer,'OllamaClient',return_value=client),
              patch.object(rb,'render_review_prompt',side_effect=lambda name,*a,**k:name),
              patch.object(rb,'supplement_quantities',return_value=[])):
            self.assertEqual(rb.process(request)['state'],'partial')
            client.fail.clear();client.calls.clear();request['model']['name']='different synthetic model'
            rb.process(request)
        self.assertEqual(client.calls,['paper_info','key_findings','introduction','conclusion','figure'])

    def test_metadata_failure_and_figure_failure_retry_independently(self):
        paper=self.parsed();paper.figures=[rb.parser.Figure(1,'Fig. 1',None,'Synthetic caption',0,[40,620,200,640],crop_bbox=[40,580,200,615])]
        client=FakeClient(['paper_info','figure'])
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**k:name):
            card=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client)
            self.assertFalse(card.meta['metadata_generation_ok']);self.assertEqual(card.figures[0].status,'failed')
            client.fail.clear();client.calls.clear()
            repaired=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client,base_card=card,only_figures=[1])
        self.assertEqual(client.calls,['paper_info','figure'])
        self.assertTrue(generation_complete(repaired.to_dict()))
        self.assertEqual(repaired.key_findings,card.key_findings)

    def test_intro_exception_and_missing_source_are_not_complete(self):
        paper=self.parsed();client=FakeClient(['introduction'])
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**k:name):
            card=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client)
            self.assertFalse(generation_complete(card.to_dict()))
            client.fail.clear();client.calls.clear()
            card=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client,base_card=card,only_figures=[])
            self.assertEqual(client.calls,['introduction']);self.assertTrue(generation_complete(card.to_dict()))
            paper.sections=[];paper.paragraphs=[]
            missing=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client)
        self.assertEqual(missing.meta['generation']['stages']['conclusion']['state'],'missing_source')
        self.assertFalse(generation_complete(missing.to_dict()))

    def test_real_bridge_regenerates_failed_stage_before_publishing_marker(self):
        self.pdf();client=FakeClient(['paper_info'])
        request={'out_dir':str(self.root),'model':self.config['model']}
        with (patch.object(rb.analyzer,'OllamaClient',return_value=client),
              patch.object(rb,'render_review_prompt',side_effect=lambda name,*a,**k:name),
              patch.object(rb,'supplement_quantities',return_value=[])):
            result=rb.process(request)
            self.assertEqual(result['state'],'partial');self.assertFalse((self.root/'quality-ready.json').exists())
            client.fail.clear();client.calls.clear();result=rb.process(request)
        self.assertEqual(client.calls,['paper_info'])
        self.assertNotEqual(result['state'],'partial');self.assertIsNotNone(eligible(self.root))
        self.assertEqual(json.loads((self.root/'card.json').read_text())['meta']['reading_contract_version'],READING_CONTRACT_VERSION)

    def test_reviewed_legacy_card_is_preserved_byte_for_byte(self):
        self.pdf();card=self.complete_card();card['meta'].update(reading_contract_version=2,quality_review={'source_sha256':file_digest(self.root/'source.pdf')})
        path=self.root/'card.json';path.write_text(json.dumps(card));before=path.read_bytes()
        with patch.object(rb.analyzer,'OllamaClient') as model:
            result=rb.process({'out_dir':str(self.root),'model':self.config['model']})
        model.assert_not_called();self.assertTrue(result['cached']);self.assertEqual(before,path.read_bytes())


class EvidenceIdentity(LocalFixture):
    def test_group_with_unnumbered_head_and_numbered_member_shares_directory(self):
        paper=self.parsed();eq=self.eq();eq.group_numbers=[5,6]
        card=rb.analyzer._equation_card(paper,eq)
        self.assertEqual(eq.folder_name,card.folder_name);self.assertTrue(eq.folder_name.startswith('Eq_5_p1_'))
    def eq(self,page=0,y=100,number=None):
        e=rb.parser.Equation(label='member',number=number,page=page,bbox=[40,y,240,y+25],text='x = y',group_label='group',group_numbers=[number] if number else [])
        e.members=[{'label':e.label,'number':number,'page':page+1,'source_note':'synthetic','confidence':'high','text':e.text}]
        return e
    def test_same_coordinates_on_different_pages_are_not_deduplicated(self):
        block={'bbox':[40,100,200,125],'text':'x = y + z'}
        equations=rb.parser._find_display_equations([[block],[dict(block)]])
        self.assertEqual(len(equations),2);self.assertNotEqual(equations[0].evidence_id,equations[1].evidence_id)
    def test_parser_card_and_export_use_one_unique_path_per_equation(self):
        paper=self.parsed();paper.equations=[self.eq(y=620),self.eq(y=690)]
        rb.parser.render_figures(paper,self.root)
        cards=[rb.analyzer._equation_card(paper,e) for e in paper.equations]
        self.assertNotEqual(cards[0].folder_name,cards[1].folder_name)
        for equation,card in zip(paper.equations,cards):self.assertEqual(equation.folder_name,card.folder_name)
        rb.exporter.export_card(rb.analyzer.PaperCard(title='synthetic',equations=cards),self.root)
        self.assertEqual(len(list(self.root.rglob('equation.png'))),2)
    def test_refresh_group_identity_does_not_append_duplicate_or_lose_image(self):
        paper=self.parsed();equation=self.eq(number=4);equation.group_label='Eq. (4)–(5)';paper.equations=[equation]
        card=rb.analyzer.PaperCard(title='synthetic',equations=[rb.analyzer._equation_card(paper,equation)])
        card.equations[0].status='failed'
        equation.image_path=str(self.root/'new.png')
        for _ in range(2):rb.analyzer._refresh_evidence(card,paper,FakeClient())
        self.assertEqual(len(card.equations),1);self.assertEqual(card.equations[0].image_path,equation.image_path)
    def test_section_repair_preserves_discussion_and_consumer_uses_it(self):
        paper=self.parsed();self.assertIn('Discussion',[s.name for s in paper.sections])
        self.assertNotIn('Conclusion',[s.name for s in paper.sections]);self.assertTrue(rb.analyzer.closing_text(paper))
    def test_adjacent_definitions_cannot_expand_context_beyond_budget(self):
        paper=self.parsed();e=self.eq();paper.equations=[e]
        paper.paragraphs=[rb.parser.Paragraph(i,0,[40,20+i*35,240,45+i*35],('Here x denotes the measured quantity. '*8)) for i in range(12)]
        e.context=[];rb.include_adjacent_definitions(paper,1000)
        text=rb.analyzer._equation_evidence(paper,rb.analyzer._equation_card(paper,e))
        self.assertLessEqual(len(text),1000);self.assertTrue(e.context);self.assertTrue(any('预算' in w for w in paper.warnings))


class CompletionGate(LocalFixture):
    def test_ok_status_without_local_evidence_image_cannot_trigger_review(self):
        card=self.complete_card();card['equations']=[{'status':'ok','error':None,'image_path':str(self.root/'missing.png')}]
        self.write_completion(card);self.assertIsNone(eligible(self.root))
    def test_contract_inventory_reports_legacy_without_rewriting_it(self):
        from reading.reading_contract import inventory
        for name,version in [('old',2),('current',READING_CONTRACT_VERSION),('unknown',None)]:
            folder=self.root/name;folder.mkdir();card=self.complete_card();card['meta']['reading_contract_version']=version
            (folder/'card.json').write_text(json.dumps(card))
        before={str(p):p.read_bytes() for p in self.root.glob('*/card.json')}
        report=inventory(self.root);self.assertEqual(report['versions'],{'2':1,str(READING_CONTRACT_VERSION):1,'missing':1})
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.glob('*/card.json')})
    def test_failed_metadata_is_blocked_even_if_marker_and_hash_match(self):
        card=self.complete_card();card['meta']['generation']['stages']['introduction']={'state':'failed','error':'HTTP 500'}
        self.write_completion(card);self.assertIsNone(eligible(self.root))
    def test_legacy_untyped_cards_and_pending_figures_cannot_pass(self):
        for card in ({'meta':{'reading_contract_version':READING_CONTRACT_VERSION}},
                     {**self.complete_card(),'figures':[{'status':'pending','error':None}]}):
            self.write_completion(card);self.assertIsNone(eligible(self.root))
    def test_warning_prose_does_not_control_completion(self):
        card=self.complete_card();card['warnings']=['Quoted upstream message: 502 Server Error; retained as audit history.']
        self.write_completion(card);self.assertIsNotNone(eligible(self.root))
        marker=json.loads((self.root/'quality-ready.json').read_text());marker['reading_contract_version']=READING_CONTRACT_VERSION+1
        (self.root/'quality-ready.json').write_text(json.dumps(marker));self.assertIsNone(verified_completion(self.root))


class DurableRecovery(LocalFixture):
    def test_policy_recovery_reopens_exhausted_failures_once_and_preserves_reviewed_cards(self):
        from reading.reading_recovery import activate
        source=self.root/'original.pdf';source.write_bytes(b'fixture')
        pid=self.catalog.upsert({'title':'synthetic'});self.catalog.update(pid,asset_path=str(source),acquisition='available')
        failed=self.catalog.enqueue('screen',pid);self.catalog.finish(failed,'failed','old validation')
        with self.catalog.connect() as db:db.execute('UPDATE jobs SET attempts=3 WHERE id=?',(failed,))
        protected=self.catalog.upsert({'title':'reviewed'});self.catalog.decide(protected,'deep_read')
        card=self.root/'reviewed.json';card.write_text(json.dumps({'meta':{'quality_review':{'source_sha256':'original'}}}))
        self.catalog.update(protected,asset_path=str(source),card_path=str(card))
        job=self.catalog.enqueue('deep_read',protected);self.catalog.finish(job,'partial')
        preview=activate(self.catalog,self.config,True);self.assertEqual(len(preview['jobs']),1)
        result=activate(self.catalog,self.config);self.assertEqual(len(result['jobs']),1)
        self.assertEqual(result['skipped']['reviewed_card_protected'],1)
        self.assertTrue(activate(self.catalog,self.config)['already_activated'])
        jobs={j['id']:j for j in self.catalog.jobs()};self.assertEqual(jobs[failed]['error'],'old validation')
        self.assertEqual(jobs[result['jobs'][0]['job_id']]['attempts'],0)
        replacement=result['jobs'][0]['job_id'];self.catalog.finish(replacement,'done')
        maintain_jobs(self.catalog,self.config,kinds=('screen','deep_read'),audit_assets=False)
        jobs={j['id']:j for j in self.catalog.jobs()}
        self.assertEqual(jobs[failed]['state'],'failed');self.assertEqual(jobs[failed]['recovered_by'],replacement)

    def test_reviewed_card_with_replaced_source_is_not_silently_regenerated(self):
        source=self.pdf();card=self.complete_card();card['meta']['quality_review']={'source_sha256':'different original'}
        path=self.root/'card.json';path.write_text(json.dumps(card));before=path.read_bytes()
        with patch.object(rb.analyzer,'OllamaClient') as model:
            result=rb.process({'out_dir':str(self.root),'model':self.config['model']})
        model.assert_not_called();self.assertTrue(result['source_changed']);self.assertEqual(result['state'],'needs_review');self.assertEqual(path.read_bytes(),before)

    def test_partial_read_retry_obeys_attempts_delay_lane_and_human_rejection(self):
        p=self.catalog.upsert({'title':'synthetic'});self.catalog.decide(p,'deep_read')
        job=self.catalog.enqueue('deep_read',p);self.catalog.claim(('deep_read',));self.catalog.finish(job,'partial')
        rejected=self.catalog.upsert({'title':'rejected'});self.catalog.decide(rejected,'reject')
        reject_job=self.catalog.enqueue('deep_read',rejected);self.catalog.finish(reject_job,'partial')
        other=self.catalog.enqueue('acquire',p);self.catalog.finish(other,'failed')
        past=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        with self.catalog.connect() as db:db.execute('UPDATE jobs SET updated=?',(past,))
        maintain_jobs(self.catalog,self.config,kinds=('screen','deep_read'),audit_assets=False)
        jobs={j['id']:j for j in self.catalog.jobs()}
        self.assertEqual(jobs[job]['state'],'queued');self.assertEqual(jobs[reject_job]['state'],'partial');self.assertEqual(jobs[other]['state'],'failed')
        with self.catalog.connect() as db:db.execute("UPDATE jobs SET state='partial',attempts=3,updated=? WHERE id=?",(past,job))
        maintain_jobs(self.catalog,self.config,kinds=('deep_read',),audit_assets=False)
        self.assertEqual(next(j for j in self.catalog.jobs() if j['id']==job)['state'],'partial')
    def test_old_failure_stays_visible_after_hundreds_of_completed_jobs(self):
        failure=self.catalog.enqueue('screen');self.catalog.finish(failure,'failed','synthetic')
        for _ in range(240):job=self.catalog.enqueue('screen');self.catalog.finish(job,'done')
        self.assertIn(failure,{j['id'] for j in self.catalog.jobs()})
    def test_screen_cache_tracks_prompt_text_and_seed_abstract(self):
        pid=self.catalog.upsert({'title':'synthetic candidate'});seed=self.catalog.upsert({'title':'seed','abstract':'old background'},seed=True)
        self.config['pdf_only']=False
        raw={'core_findings':'synthetic','recommendation_reason':'synthetic','novelty':'synthetic','relevance':3,'tags':[],'novelty_high':False,'evidence_quote':''}
        def response(*a,**k):return io.BytesIO(json.dumps({'message':{'content':json.dumps(raw)}}).encode())
        with (patch('core.services.evidence_input',return_value=('Synthetic measured evidence.','仅标题与摘要')),
              patch('core.services.urllib.request.urlopen',side_effect=response) as calls):
            screen(self.catalog,self.config,pid);screen(self.catalog,self.config,pid);self.assertEqual(calls.call_count,1)
            self.catalog.upsert({'title':'seed','abstract':'changed background'},seed=True)
            screen(self.catalog,self.config,pid);self.assertEqual(calls.call_count,2)
            with patch('core.services.SCREEN_SYSTEM_PROMPT','Changed synthetic prompt'):
                screen(self.catalog,self.config,pid)
            self.assertEqual(calls.call_count,3)


class AttachedWorkbench(LocalFixture):
    def test_ui_attaches_read_supervision_and_closing_ui_keeps_fetch_alive(self):
        from fetch.fetch_service import start, status, request_stop
        from core.runtime import alive
        from workbench import web
        self.config.update(automatic_schedule_enabled=False,tailscale_enabled=False,
                           studio_library_root=str(self.root/'library'),seed_input_dir=str(self.root/'seeds'))
        self.config['fetch_pipeline']['prevent_idle_sleep']=False
        # This fixture explicitly tests the retired local-mode UI lifecycle.
        self.config['web_cards']['enabled']=False
        path=self.root/'config.json';path.write_text(json.dumps(self.config))
        servers=[];errors=[];thread=None;factory=web.create_http_server
        def capture(*args):
            server=factory(*args);servers.append(server);return server
        def launch():
            try:web.serve(self.config,path,0,False)
            except Exception as exc:errors.append(exc)
        def wait_for(predicate,timeout=15):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if predicate():return
                time.sleep(.1)
            self.fail('Isolated attached workbench condition timed out: '+str(errors))
        try:
            keeper=start(self.config,path)
            wait_for(lambda:status(self.config)['runtime'].get('lanes',{}).get('fetch',{}).get('alive'))
            before=status(self.config)['runtime'];fetch_pid=before['lanes']['fetch']['pid'];supervisor=before['pid']
            with (patch.object(web,'init_seeds'),patch.object(web,'create_http_server',side_effect=capture),patch('sys.stdout',new=io.StringIO())):
                thread=threading.Thread(target=launch,daemon=True);thread.start()
                wait_for(lambda:status(self.config)['runtime'].get('lanes',{}).get('read',{}).get('alive'))
                read_pid=status(self.config)['runtime']['lanes']['read']['pid'];os.kill(read_pid,signal.SIGKILL)
                # Supervisor backoff alone is 10s; allow subprocess startup under
                # full-suite load while still requiring a different live PID.
                wait_for(lambda:status(self.config)['runtime'].get('lanes',{}).get('read',{}).get('alive') and status(self.config)['runtime']['lanes']['read']['pid']!=read_pid,timeout=30)
                restarted=status(self.config)['runtime']['lanes']['read']['pid']
                servers[0].shutdown();thread.join(12)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            wait_for(lambda:not alive(restarted))
            after=status(self.config)
            self.assertEqual(after['pid'],keeper['pid']);self.assertEqual(after['state'],'running')
            self.assertEqual(after['runtime']['pid'],supervisor);self.assertEqual(after['runtime']['lanes']['fetch']['pid'],fetch_pid)
            self.assertTrue(alive(fetch_pid))
        finally:
            if thread and thread.is_alive() and servers:servers[0].shutdown();thread.join(12)
            request_stop(self.config)
            wait_for(lambda:status(self.config)['state']=='stopped')

if __name__=='__main__':unittest.main()
