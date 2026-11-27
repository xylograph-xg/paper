import copy
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog
from review import card_review_queue as review
from correction import card_correction_queue as corrections
from cards import web_card_queue as cards
from core.services import atomic_json
from cards.web_card_inputs import digest


QUOTE='The observation was supported by an independent control experiment.'


class ReviewQueue(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite3')
        self.config={'catalog_path':str(self.catalog.path),'studio_library_root':str(self.root/'library'),
            'card_review':{'enabled':True,'parallel_jobs':4,'max_reworks':2},
            'card_correction':{'enabled':True,'parallel_jobs':4},'web_cards':{'enabled':True}}
        review.install(self.catalog);cards.install(self.catalog)

    def card(self,title='Synthetic',quality=87,novelty=88):
        pid=self.catalog.upsert({'title':title,'doi':'10.9999/'+title})
        source=self.root/(pid+'.pdf');source.write_bytes(b'original synthetic PDF')
        folder=self.root/'library'/pid;folder.mkdir(parents=True);(folder/'source.pdf').write_bytes(b'clean synthetic PDF')
        card={'title':title,'info':{},'one_line_summary':'s','key_findings':'k','intro_summary':'i','conclusion_summary':'c',
            'warnings':[],'figures':[{'label':'Fig. 1','source_page':1,'evidence_id':'P001','evidence_quote':QUOTE,'summary':'A condition.'}],
            'equations':[],'tables':[],
            'paper_evaluation':{name:{'score':score,'reason':'Synthetic source reason','source_pages':[1]} for name,score in [('overall_quality',quality),('direction_novelty',novelty)]},
            'meta':{'producer':'web_card_service','provider':'chatgpt','source_original_sha256':digest(source),
                'source_sha256':digest(folder/'source.pdf'),'scientific_verified':False,'production_contract_complete':False}}
        path=folder/'card.json';atomic_json(path,card)
        self.catalog.update(pid,asset_path=str(source),asset_hash=digest(source),card_path=str(path),acquisition='available')
        review.enqueue(self.catalog,self.config)
        job=next(j for j in review.rows(self.catalog) if j['paper_id']==pid)
        return job,path,card

    def packet(self,job,card):
        folder=Path(job['folder']);folder.mkdir(parents=True)
        atomic_json(folder/'card-original.json',card)
        atomic_json(folder/'source-context.json',{'source_text':[{'source_page':1,'text':QUOTE}]})
        for name in ('source.pdf','visual.pdf','card-review.json','prompt.txt','prompt-actual.txt','bundle.zip'):
            (folder/name).write_text(name)
        packet={'page_count':1,'input_hashes':{n:digest(folder/n) for n in ('source.pdf','visual.pdf','source-context.json','card-original.json','card-review.json','prompt.txt')},
            'upload_bundle':{'zip_path':str(folder/'bundle.zip'),'zip_sha256':digest(folder/'bundle.zip')},
            'actual_prompt_sha256':digest(folder/'prompt-actual.txt')}
        atomic_json(folder/'packet.json',packet);return folder,packet

    def feedback(self):
        return {'sample_kind':'mixed','scores':{k:9 for k in __import__('review.card_evaluation',fromlist=['RUBRIC']).RUBRIC},
            'missing_inputs':[],'issues':[],'verdict':'pass','source_identity_checked':True,'key_findings_checked':True,
            'source_pages_reviewed':[1],'checked_items':[{'group':'figures','label':'Fig. 1','source_page':1}],'corrections':[]}

    def receipt(self,folder,packet,feedback):
        (folder/'response-raw.txt').write_text(json.dumps(feedback))
        atomic_json(folder/'attempt.json',{'state':'response_saved','raw_sha256':digest(folder/'response-raw.txt'),
            'actual_prompt_sha256':packet['actual_prompt_sha256'],'inputs':packet['input_hashes'],
            'conversation_url':'https://chatgpt.com/c/synthetic-review'})

    def test_priorities_and_idempotent_versions_with_missing_scores_last(self):
        low,_,_=self.card('low',60,99);unknown,_,_=self.card('unknown',None,None)
        high,_,_=self.card('high',95,70);tie,_,_=self.card('tie',95,88)
        self.assertEqual([j['paper_id'] for j in review.rows(self.catalog)],[tie['paper_id'],high['paper_id'],low['paper_id'],unknown['paper_id']])
        self.assertEqual(review.enqueue(self.catalog,self.config),0)
        self.assertEqual(review.rows(self.catalog)[0]['priority'],95)

    def test_user_pauses_override_review_enabled_and_concurrency(self):
        self.assertTrue(review.enabled(self.config))
        for name in ('web-card-control.json','card-review-control.json'):
            atomic_json(self.root/name,{'paused_by_user':True})
            self.assertFalse(review.enabled(self.config));(self.root/name).unlink()
        (self.root/'card-review-control.json').write_text('{')
        self.assertFalse(review.enabled(self.config))

    def test_source_card_version_and_identity_protection(self):
        job,path,card=self.card();review.current(self.catalog,job,self.config)
        path.write_text(path.read_text()+' ')
        with self.assertRaises(ValueError):review.current(self.catalog,job,self.config)

    def test_quote_locator_keeps_image_page_and_science_unverified(self):
        _,_,card=self.card();card['figures'][0]['image_path']='P001.png'
        candidate,fixes=review.locate_quotes(card,['A different original page.',QUOTE])
        self.assertEqual(len(fixes),1);item=candidate['figures'][0]
        self.assertEqual(item['source_page'],1);self.assertEqual(item['evidence_id'],'P001')
        self.assertEqual(item['image_path'],'P001.png');self.assertEqual(item['evidence_source_page'],2)
        self.assertEqual(item['evidence_quote'],QUOTE);self.assertFalse(candidate['meta']['scientific_verified'])
        self.assertEqual(review.locate_quotes(candidate,['A different original page.',QUOTE])[1],[])

    def test_repeated_or_short_quotes_do_not_get_guessed_locations(self):
        _,_,card=self.card()
        self.assertEqual(review.locate_quotes(card,['other',QUOTE,QUOTE])[1],[])
        card['figures'][0]['evidence_quote']='short'
        self.assertEqual(review.locate_quotes(card,['other','short'])[1],[])

    def test_full_pass_is_distinct_from_partial_high_scores(self):
        job,_,card=self.card();folder,_=self.packet(job,card);data=self.feedback()
        self.assertEqual(review.parse_review(json.dumps(data),folder)[1]['action'],'pass')
        for field,value in [('source_pages_reviewed',[]),('checked_items',[]),('key_findings_checked',False),('missing_inputs',['visual.pdf'])]:
            broken={**data,field:value}
            self.assertEqual(review.parse_review(json.dumps(broken),folder)[1]['action'],'needs_user')

    def test_weighted_review_score_remains_separate_from_literature_priority(self):
        job,_,card=self.card(quality=95);folder,_=self.packet(job,card);data=self.feedback()
        data['scores']=dict(zip(data['scores'],[10,8,9,7,6]))
        _,result=review.parse_review(json.dumps(data),folder)
        self.assertEqual(result['weighted_score'],84)
        self.assertEqual(result['scores'],data['scores'])
        self.assertEqual(result['action'],'needs_user')
        review.update(self.catalog,job['id'],'needs_user',result=result)
        visible=review.status(self.config)['jobs'][0]
        self.assertEqual(visible['priority'],95);self.assertEqual(visible['review_score'],84)
        self.assertEqual(visible['review_scores'],data['scores'])
        review.update(self.catalog,job['id'],'needs_user','Later local error')
        self.assertEqual(review.for_card(self.config,job['paper_id'],job['card_sha256'])['review_score'],84)
        self.assertIsNone(review.for_card(self.config,job['paper_id'],'different version'))

    def test_unreviewed_has_no_default_score(self):
        self.card(quality=95)
        row=review.status(self.config)['jobs'][0]
        self.assertIsNone(row['review_score']);self.assertEqual(row['review_scores'],{})
        for invalid in (True,101,-1,float('nan')):
            self.assertIsNone(review.public_result({'result':json.dumps({'weighted_score':invalid})})['review_score'])

    def test_status_reads_current_persisted_parallelism(self):
        atomic_json(self.root/'concurrency-control.json',{'review':10})
        self.assertEqual(review.status(self.config)['parallel_jobs'],10)

    def test_duplicate_item_coverage_is_not_full_review(self):
        job,_,card=self.card();folder,_=self.packet(job,card);data=self.feedback()
        data['checked_items']*=2
        self.assertFalse(review.parse_review(json.dumps(data),folder)[1]['full_source_checked'])

    def test_invalid_item_coverage_preserves_actual_score_without_passing(self):
        job,_,card=self.card();folder,_=self.packet(job,card);data=self.feedback()
        data['checked_items'][0]['source_page']='1'
        result=review.parse_review(json.dumps(data),folder)[1]
        self.assertEqual(result['weighted_score'],90);self.assertEqual(result['action'],'needs_user')

    def test_high_model_score_cannot_pass_damaged_math_fields(self):
        job,_,card=self.card();card['equations']=[{'label':'Eq.1','source_page':1,'latex':'\frac{x}{y}'}]
        folder,_=self.packet(job,card);data=self.feedback()
        data['checked_items'].append({'group':'equations','label':'Eq.1','source_page':1})
        result=review.parse_review(json.dumps(data),folder)[1]
        self.assertTrue(result['model_report_pass']);self.assertFalse(result['pass'])
        self.assertEqual(result['action'],'rework');self.assertEqual(result['offline_blockers'],['equations.0.latex'])
        data['missing_inputs']=['visual.pdf']
        self.assertEqual(review.parse_review(json.dumps(data),folder)[1]['action'],'needs_user')

    def test_new_card_parser_rejects_control_corruption_but_accepts_real_multiline_latex(self):
        from cards.web_card_inputs import parse_card
        _,_,card=self.card();card['figures']=[]
        eq={'label':'Eq.1','source_page':1,'evidence_id':'P001','one_line':'x','summary':'x','detail':'x','result':'x',
            'evidence_quote':QUOTE,'latex':'\\frac{x}{y}\n+z','quantities':'definitions'}
        card['equations']=[eq];packet={'page_count':1,'page_manifest':[{'image':'one.png'}]}
        self.assertEqual(parse_card(json.dumps(card),packet)['equations'][0]['latex'],eq['latex'])
        eq['latex']='\frac{x}{y}'
        with self.assertRaises(ValueError):parse_card(json.dumps(card),packet)

    def test_major_issue_needs_actual_source_quote(self):
        job,_,card=self.card();folder,_=self.packet(job,card);data=self.feedback()
        issue={'severity':'major','finding':'Numerical mismatch','evidence':'Source quote','source_page':1,'source_quote':QUOTE}
        data.update(verdict='revise',issues=[issue])
        self.assertEqual(review.parse_review(json.dumps(data),folder)[1]['action'],'rework')
        issue['source_quote']='An invented original sentence with no source support.'
        self.assertEqual(review.parse_review(json.dumps(data),folder)[1]['action'],'needs_user')

    def test_formatting_only_corrections_preserve_numbers_and_symbols(self):
        _,_,card=self.card()
        fixed=review.formatting_candidate(card,[{'path':'figures.0.summary','before':'A condition.','after':'A\ncondition.'}])
        self.assertEqual(fixed['figures'][0]['summary'],'A\ncondition.')
        for path,before,after in [('figures.0.summary','A condition.','A different condition.'),('equations.0.latex','x','y'),('meta.scientific_verified',False,True)]:
            with self.assertRaises(ValueError):review.formatting_candidate(card,[{'path':path,'before':before,'after':after}])

    def test_packet_or_zip_changes_block_review(self):
        job,_,card=self.card();folder,_=self.packet(job,card)
        (folder/'bundle.zip').write_text('changed')
        with self.assertRaises(ValueError):review.parse_review(json.dumps(self.feedback()),folder)

    def test_duplicate_review_url_blocks_attribution(self):
        job,path,card=self.card();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        other=folder.parent/'other';other.mkdir();atomic_json(other/'attempt.json',{'conversation_url':'https://chatgpt.com/c/synthetic-review'})
        with self.assertRaises(ValueError):review.apply_result(self.catalog,job,self.config)
        self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])

    def test_pass_publication_backs_up_exact_version_and_never_completes_production_contract(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        review.apply_result(self.catalog,job,self.config)
        result=json.loads(path.read_text());self.assertTrue(result['meta']['scientific_verified'])
        self.assertFalse(result['meta']['production_contract_complete']);self.assertEqual(result['paper_evaluation'],card['paper_evaluation'])
        self.assertEqual((path.parent/'history'/('source-review-'+job['id'])/'card.json').read_bytes(),before)
        self.assertEqual(review.enqueue(self.catalog,self.config),0)
        self.assertEqual({j['state'] for j in review.rows(self.catalog)},{'passed'})
        self.assertEqual(review.status(self.config)['counts'],{'passed':1})
        self.assertEqual(review.for_card(self.config,job['paper_id'],digest(path))['review_score'],90)
        self.assertEqual(result['meta']['source_review']['scores'],self.feedback()['scores'])
        listed=self.catalog.page(tab='all')['papers'][0]
        self.assertEqual(listed['review_score'],90);self.assertEqual(listed['total_score'],177)

    def test_score_survives_version_change_after_report_is_saved(self):
        job,path,card=self.card();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        path.write_text(path.read_text()+' ')
        producer=review.ReviewProducer(self.config)
        try:producer.work({**job,'state':'response_saved'})
        finally:producer.executor.shutdown()
        visible=review.status(self.config)['jobs'][0]
        self.assertEqual(visible['state'],'needs_user');self.assertEqual(visible['review_score'],90)
        self.assertIsNone(review.for_card(self.config,job['paper_id'],digest(path)))

    def test_human_card_only_receives_report_not_publication(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        self.catalog.event(job['paper_id'],'human_decision',{'decision':'keep'})
        review.apply_result(self.catalog,job,self.config)
        self.assertEqual(path.read_bytes(),before);self.assertTrue((folder/'feedback.json').exists())
        self.assertEqual(review.rows(self.catalog)[0]['state'],'needs_user')

    def test_uncertain_or_changed_receipts_never_publish(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        a=json.loads((folder/'attempt.json').read_text());a['state']='needs_inspection';atomic_json(folder/'attempt.json',a)
        with self.assertRaises(ValueError):review.apply_result(self.catalog,job,self.config)
        self.assertEqual(path.read_bytes(),before)

    def test_paused_review_does_not_publish_complete_report(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);self.receipt(folder,packet,self.feedback())
        atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
        with self.assertRaises(ValueError):review.apply_result(self.catalog,job,self.config)
        self.assertEqual(path.read_bytes(),before)

    def original_attempt(self,job,state='response_saved'):
        root=self.root/'web_cards'/job['paper_id'];folder=root/'chatgpt';folder.mkdir(parents=True)
        for name in ('source.pdf','visual.pdf','source-context.json','prompt.txt'):(root/name).write_text(name)
        packet={'input_hashes':{n:digest(root/n) for n in ('source.pdf','visual.pdf','source-context.json','prompt.txt')}}
        atomic_json(root/'packet.json',packet)
        (folder/'prompt-actual.txt').write_text((root/'prompt.txt').read_text());(folder/'response-raw.txt').write_text('Complete original answer')
        atomic_json(folder/'attempt.json',{'state':state,'raw_sha256':digest(folder/'response-raw.txt'),
            'actual_prompt_sha256':digest(folder/'prompt-actual.txt'),'inputs':packet['input_hashes'],'conversation_url':'https://chatgpt.com/c/original'})
        with self.catalog.connect() as db:
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,'{}','completed','test')",(job['paper_id'],job['source_sha256'],job['title']))
        return root

    def test_major_reset_archives_answers_keeps_old_card_and_source_only_regeneration(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);data=self.feedback()
        data.update(verdict='revise',issues=[{'severity':'major','finding':'Mismatch','evidence':'Original','source_page':1,'source_quote':QUOTE}])
        self.receipt(folder,packet,data);root=self.original_attempt(job)
        review.apply_result(self.catalog,job,self.config)
        self.assertEqual(cards.jobs(self.catalog)[0]['state'],'completed')
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue((root/'chatgpt/attempt.json').exists());self.assertTrue((root/'packet.json').exists())
        self.assertEqual(review.rows(self.catalog)[0]['state'],'correction_queued')
        correction=corrections.rows(self.catalog)[0]
        self.assertEqual(correction['kind'],'source_rework');self.assertEqual(correction['state'],'queued')
        corrections.process(self.catalog,correction,self.config)
        queued=cards.jobs(self.catalog)[0];self.assertEqual(queued['state'],'queued');self.assertGreater(queued['retry_at'],time.time())
        self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'chatgpt').exists());self.assertFalse((root/'packet.json').exists())
        history=root/'history'/('source-review-'+job['id'])
        self.assertTrue((history/'chatgpt/response-raw.txt').exists());self.assertTrue((history/'packet.json').exists())
        self.assertNotIn('Mismatch',(root/'prompt.txt').read_text())
        self.assertEqual(json.loads(queued['selection'])['rework']['kind'],'source_review')
        self.assertEqual(json.loads(queued['selection'])['rework']['correction_id'],correction['id'])
        self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])

    def test_unknown_generation_cannot_be_reset_even_after_major_review(self):
        job,path,card=self.card();folder,packet=self.packet(job,card);data=self.feedback()
        data.update(verdict='revise',issues=[{'severity':'major','finding':'Mismatch','evidence':'Original','source_page':1,'source_quote':QUOTE}])
        self.receipt(folder,packet,data);root=self.original_attempt(job,'submitted')
        review.apply_result(self.catalog,job,self.config)
        self.assertEqual(review.rows(self.catalog)[0]['state'],'correction_queued')
        correction=corrections.rows(self.catalog)[0]
        with self.assertRaises(ValueError):corrections.process(self.catalog,correction,self.config)
        self.assertTrue((root/'chatgpt/attempt.json').exists());self.assertEqual(cards.jobs(self.catalog)[0]['state'],'completed')
        self.assertEqual(digest(path),job['card_sha256']);self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])

    def test_major_reworks_are_bounded(self):
        job,path,card=self.card();folder,packet=self.packet(job,card);data=self.feedback()
        data.update(verdict='revise',issues=[{'severity':'major','finding':'Mismatch','evidence':'Original','source_page':1,'source_quote':QUOTE}])
        self.receipt(folder,packet,data);root=self.original_attempt(job)
        for _ in range(2):self.catalog.event(job['paper_id'],'card_review_rework',{})
        review.apply_result(self.catalog,job,self.config)
        self.assertEqual(review.rows(self.catalog)[0]['state'],'correction_queued')
        corrections.process(self.catalog,corrections.rows(self.catalog)[0],self.config)
        self.assertTrue((root/'chatgpt/attempt.json').exists());self.assertEqual(review.rows(self.catalog)[0]['state'],'needs_user')
        self.assertEqual(corrections.rows(self.catalog)[0]['state'],'needs_user')
        self.assertEqual(digest(path),job['card_sha256'])

    def test_minor_handoff_keeps_original_and_correction_pause_preserves_report(self):
        job,path,card=self.card();before=path.read_bytes();folder,packet=self.packet(job,card);data=self.feedback()
        data['corrections']=[{'path':'figures.0.summary','before':'A condition.','after':'A\ncondition.',
            'source_page':1,'source_quote':QUOTE}]
        self.receipt(folder,packet,data)
        atomic_json(self.root/'card-correction-control.json',{'paused_by_user':True})
        review.apply_result(self.catalog,job,self.config)
        correction=corrections.rows(self.catalog)[0]
        self.assertEqual(correction['state'],'queued');self.assertEqual(path.read_bytes(),before)
        self.assertEqual(review.rows(self.catalog)[0]['state'],'correction_queued')
        self.assertEqual(review.status(self.config)['jobs'][0]['review_score'],90)
        with self.assertRaises(corrections.CorrectionPaused):
            corrections.process(self.catalog,correction,self.config)
        self.assertEqual(path.read_bytes(),before);self.assertFalse(json.loads(path.read_text())['meta']['scientific_verified'])
        self.assertTrue((folder/'feedback.json').exists());self.assertTrue((folder/'response-raw.txt').exists())

    def test_parallel_preparation_claims_each_version_once(self):
        jobs=[self.card('parallel'+str(i),90-i,80)[0] for i in range(4)]
        gate=threading.Event();started=[];lock=threading.Lock()
        def prepare(catalog,job,config):
            with lock:started.append(job['id'])
            gate.wait(5);return True
        with patch('review.card_review_queue.prepare',side_effect=prepare):
            producer=review.ReviewProducer(self.config);producer.start()
            try:
                until=time.monotonic()+4
                while len(started)<4 and time.monotonic()<until:time.sleep(.03)
                self.assertEqual(len(started),4);self.assertEqual(len(set(started)),4)
                self.assertEqual([j['state'] for j in review.rows(self.catalog)],['preparing']*4)
            finally:gate.set();producer.stop()
        self.assertEqual([j['state'] for j in review.rows(self.catalog)],['ready']*4)

    def test_real_source_packet_quote_correction_then_preparation_with_single_zip(self):
        import pymupdf,os,sys
        from cards.web_card_inputs import prepare as prepare_source
        job,path,card=self.card();paper=self.catalog.get(job['paper_id']);source=Path(paper['asset_path'])
        doc=pymupdf.open();doc.new_page().insert_text((40,60),'Synthetic figure page.')
        doc.new_page().insert_text((40,60),QUOTE);doc.save(source);doc.close()
        self.config['web_cards']['pdf_python']=sys.executable
        self.config['card_review']['media_root']=str(self.root/'review-media')
        self.config['archive_volume']='/' # Real mounted volume for isolated local media.
        with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zip-cache')}):
            root=self.root/'web_cards'/job['paper_id']
            packet=prepare_source(source,root,job['paper_id'],card['title'],digest(source))
            card['figures'][0]['image_path']=packet['page_manifest'][0]['image']
            path.with_name('source.pdf').write_bytes((root/'source.pdf').read_bytes())
            card['meta'].update(source_original_sha256=digest(source),source_sha256=digest(root/'source.pdf'))
            atomic_json(path,card);before=path.read_bytes()
            self.catalog.update(job['paper_id'],asset_hash=digest(source))
            review.enqueue(self.catalog,self.config)
            job=next(j for j in review.rows(self.catalog) if j['card_sha256']==digest(path))
            self.assertFalse(review.prepare(self.catalog,job,self.config))
            self.assertEqual(path.read_bytes(),before)
            correction=next(j for j in corrections.rows(self.catalog) if j['review_id']==job['id'])
            self.assertEqual(correction['kind'],'quote_location');self.assertEqual(correction['state'],'queued')
            self.assertEqual(next(j for j in review.rows(self.catalog) if j['id']==job['id'])['state'],'correction_queued')
            corrections.process(self.catalog,correction,self.config)
            candidate=json.loads(path.read_text());self.assertEqual(candidate['figures'][0]['source_page'],1)
            self.assertEqual(candidate['figures'][0]['evidence_source_page'],2);self.assertFalse(candidate['meta']['scientific_verified'])
            self.assertFalse(candidate['meta']['production_contract_complete'])
            self.assertEqual((path.parent/'history'/('correction-'+correction['id'])/'card.json').read_bytes(),before)
            next_job=next(j for j in review.rows(self.catalog) if j['card_sha256']==digest(path))
            self.assertTrue(review.prepare(self.catalog,next_job,self.config))
            folder=Path(next_job['folder']);packet=review.check_packet(folder)
            frozen=(folder/'packet.json').read_bytes()
            self.assertTrue(review.prepare(self.catalog,next_job,self.config))
            self.assertEqual((folder/'packet.json').read_bytes(),frozen)
            self.assertEqual(packet['visual_encoding'],'jpeg')
            self.assertLessEqual(packet['material_bytes'],60_000_000)
            self.assertLess(packet['upload_bundle']['size'],64_000_000)
            self.assertTrue((folder/'source.pdf').is_symlink());self.assertTrue((folder/'visual.pdf').is_symlink())
            self.assertTrue((folder/'card-images.pdf').is_symlink())
            payload=json.loads((folder/'card-review.json').read_text())
            self.assertNotIn('paper_evaluation',payload);self.assertNotIn('meta',payload)
            self.assertEqual(payload['figures'][0]['review_image']['page'],1)
            self.assertEqual(payload['figures'][0]['image_path'],'card-images.pdf#page=1')
            self.assertTrue(Path(packet['upload_bundle']['zip_path']).is_file())
            self.assertFalse((folder/'attempt.json').exists())
            manifest=json.loads((folder/'review-input-manifest.json').read_text())
            self.assertEqual(manifest['original_card_sha256'],digest(path))
            self.assertEqual(manifest['review_card_sha256'],digest(folder/'card-review.json'))
            self.assertNotEqual(manifest['original_card_sha256'],manifest['review_card_sha256'])
            self.assertEqual(packet['review_materials_version'],2)
            supplement=self.root/'card_review_supplements'/job['paper_id'];supplement.mkdir(parents=True)
            doc=pymupdf.open();doc.new_page().insert_text((40,60),'Synthetic supplementary source.')
            doc.new_page().insert_text((40,60),'Independent supplementary evidence.');doc.save(supplement/'supplement.pdf');doc.close()
            atomic_json(supplement/'manifest.json',{'paper_id':job['paper_id'],'source_original_sha256':digest(source),
                'doi':'10.9999/Synthetic','file':'supplement.pdf','sha256':digest(supplement/'supplement.pdf'),
                'identity_verified':True,'publisher_link':'https://publisher.example/article'})
            supplement_job={**next_job,'id':'supplement-version','folder':str(folder.parent/'supplement-version')}
            self.assertTrue(review.prepare(self.catalog,supplement_job,self.config,locate_quote_pages=False))
            added=review.check_packet(supplement_job['folder']);self.assertEqual(added['supplement']['page_count'],2)
            context=json.loads((Path(supplement_job['folder'])/'supplement-context.json').read_text())
            self.assertIn('Independent supplementary evidence',context['source_text'][1]['text'])
            Path(card['figures'][0]['image_path']).write_bytes(b'changed image')
            with self.assertRaisesRegex(ValueError,'图像指纹'):review.check_packet(folder)


class ReviewConcurrency(unittest.TestCase):
    def test_shared_pool_limit_and_independent_desired_parallelism(self):
        from core.concurrency_control import set_limit, apply
        with tempfile.TemporaryDirectory() as tmp:
            config={'catalog_path':str(Path(tmp)/'catalog.db'),'web_cards':{'max_parallel_jobs':6,'max_total_pages':20},
                'card_review':{'enabled':True,'parallel_jobs':4}}
            self.assertEqual(apply(config)['review'],4);self.assertEqual(config['web_cards']['target_pool_pages'],10)
            set_limit(config,'review',8);self.assertEqual(config['web_cards']['max_parallel_jobs'],6)
            self.assertEqual(config['web_cards']['target_pool_pages'],14)
            set_limit(config,'cards',20);self.assertEqual(config['web_cards']['target_pool_pages'],20)
            atomic_json(Path(tmp)/'card-review-control.json',{'paused_by_user':True})
            set_limit(config,'cards',6);self.assertEqual(config['web_cards']['target_pool_pages'],6)


if __name__=='__main__':unittest.main()
