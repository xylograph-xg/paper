import json
import shutil
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from review.tests import test_card_review_queue as fixtures
from review import card_review_queue as queue; from review import card_review_repair as repair
from core.services import atomic_json
from cards.web_card_inputs import digest


class MaterialRepair(unittest.TestCase):
    def test_failed_state_does_not_bypass_cycle_or_scientific_evidence_gate(self):
        for cycle,kind in ((False,'scientific'),(True,'technical'),(True,None)):
            with self.subTest(cycle=cycle,kind=kind):
                queue.update(self.catalog,self.job['id'],'failed','retained',{'failure_kind':kind})
                job=queue.rows(self.catalog)[0]
                with patch.object(queue,'prepare') as prepare:
                    with self.assertRaises(ValueError):repair.repair(self.catalog,job,self.config,cycle=cycle)
                prepare.assert_not_called();self.assertEqual(queue.rows(self.catalog)[0],job)

    def test_failed_scientific_state_still_blocks_unknown_or_paused_receipts(self):
        queue.update(self.catalog,self.job['id'],'failed','retained',{'failure_kind':'scientific'})
        job=queue.rows(self.catalog)[0];path=self.folder/'attempt.json';before=path.read_bytes()
        receipt=json.loads(before);receipt['state']='needs_inspection';atomic_json(path,receipt)
        with patch.object(queue,'prepare') as prepare:
            with self.assertRaisesRegex(ValueError,'尚未完整收取'):
                repair.repair(self.catalog,job,self.config,cycle=True)
            prepare.assert_not_called()
        path.write_bytes(before)
        atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
        with patch.object(queue,'prepare') as prepare:
            with self.assertRaisesRegex(ValueError,'暂停'):
                repair.repair(self.catalog,job,self.config,cycle=True)
            prepare.assert_not_called()
        self.assertEqual(queue.rows(self.catalog)[0],job)

    def test_failed_scientific_cycle_prepares_directly_and_preserves_old_evidence(self):
        data=self.fixture.feedback();data['verdict']='revise'
        data['issues']=[{'severity':'major','finding':'Card defect','evidence':'Source evidence','source_page':1,
                        'source_quote':'The observation was supported by an independent control experiment.'}]
        self.fixture.receipt(self.folder,self.packet,data)
        receipt=json.loads((self.folder/'attempt.json').read_text());receipt['finished']=1
        atomic_json(self.folder/'attempt.json',receipt)
        _,result=queue.parse_review(json.dumps(data),self.folder)
        self.assertEqual(result['failure_kind'],'scientific')
        queue.update(self.catalog,self.job['id'],'failed','自动终止：科学核验未通过',result)
        self.job=queue.rows(self.catalog)[0]
        before={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        card_before=self.path.read_bytes()
        with patch.object(queue,'prepare',side_effect=self.prepare):
            changed=repair.repair(self.catalog,self.job,self.config,cycle=True)
        current=queue.rows(self.catalog)[0]
        self.assertEqual(current['state'],'ready');self.assertEqual(current['id'],changed['new_review_id'])
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()},before)
        self.assertEqual(self.path.read_bytes(),card_before)
        self.assertFalse((Path(current['folder'])/'attempt.json').exists())
        intent=json.loads((Path(current['folder'])/'repair-intent.json').read_text())
        self.assertEqual(intent['old_job'],self.job)

    def archived_source_fixture(self,*,repair_intent):
        root=self.root/'web_cards'/self.job['paper_id'];archive=root/'history/source-review-old';archive.mkdir(parents=True)
        pages=self.path.parent/'pages';pages.mkdir();image=pages/'P001.png';image.write_bytes(b'original frozen page')
        packet={'paper_id':self.job['paper_id'],'source_original_sha256':self.job['source_sha256'],
                'page_count':1,'page_manifest':[{'source_page':1,'sha256':digest(image)}],
                'input_hashes':{'source.pdf':digest(self.path.with_name('source.pdf')),
                               'source-context.json':digest(self.folder/'source-context.json')}}
        atomic_json(archive/'packet.json',packet)
        atomic_json(archive/'reset-intent.json',{'job':{'paper_id':self.job['paper_id'],'source_sha256':self.job['source_sha256']}})
        shutil.copy2(self.folder/'source-context.json',archive/'source-context.json')
        candidate=self.folder.parent/'candidate';candidate.mkdir()
        if repair_intent:
            atomic_json(candidate/'repair-intent.json',{'old_job':self.job})
            original={**self.packet,'input_hashes':{**self.packet['input_hashes'],**packet['input_hashes']}}
        else:
            provider=archive/'chatgpt';provider.mkdir()
            (provider/'response-raw.txt').write_text('Original formal answer.')
            (provider/'prompt-actual.txt').write_text('Original source request.')
            meta=self.card['meta'];meta.update(raw_sha256=digest(provider/'response-raw.txt'),
                actual_prompt_sha256=digest(provider/'prompt-actual.txt'),conversation_url='https://chatgpt.com/c/original-source')
            atomic_json(provider/'attempt.json',{'provider':'chatgpt','state':'response_saved','finished':1,
                'raw_sha256':meta['raw_sha256'],'actual_prompt_sha256':meta['actual_prompt_sha256'],
                'conversation_url':meta['conversation_url'],'inputs':packet['input_hashes']})
            original=None
        return root,archive,{**self.job,'folder':str(candidate)},packet,original

    def test_retired_active_packet_uses_bound_review_archive_without_restoring_it(self):
        root,archive,job,packet,original=self.archived_source_fixture(repair_intent=True)
        with patch.object(repair,'collected',return_value=original):
            resolved,files,images=queue.source_inputs(self.catalog,job,self.path,self.card)
        self.assertEqual(resolved,packet);self.assertEqual(files['source.pdf'],self.path.with_name('source.pdf'))
        self.assertEqual(files['source-context.json'],archive/'source-context.json')
        self.assertEqual(images,self.path.parent);self.assertFalse((root/'packet.json').exists())
        (archive/'source-context.json').write_text('tampered')
        with patch.object(repair,'collected',return_value=original):
            with self.assertRaisesRegex(ValueError,'文字层变化'):queue.source_inputs(self.catalog,job,self.path,self.card)

    def test_initial_review_archive_requires_unique_formal_publication_receipt(self):
        root,archive,job,packet,_=self.archived_source_fixture(repair_intent=False)
        self.assertEqual(queue.source_inputs(self.catalog,job,self.path,self.card)[0],packet)
        receipt=archive/'chatgpt/attempt.json';old=receipt.read_bytes();value=json.loads(old)
        value['state']='needs_inspection';atomic_json(receipt,value)
        with self.assertRaises(ValueError):queue.source_inputs(self.catalog,job,self.path,self.card)
        receipt.write_bytes(old);(archive/'chatgpt/prompt-actual.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'提示归档变化'):queue.source_inputs(self.catalog,job,self.path,self.card)
        self.assertFalse((root/'packet.json').exists())

    def test_new_active_normalization_does_not_replace_original_card_source(self):
        root,archive,job,packet,original=self.archived_source_fixture(repair_intent=True)
        changed={**packet,'input_hashes':{**packet['input_hashes'],'source.pdf':'new-normalization'}}
        atomic_json(root/'packet.json',changed);before=(root/'packet.json').read_bytes()
        with patch.object(repair,'collected',return_value=original):
            resolved,files,_=queue.source_inputs(self.catalog,job,self.path,self.card)
        self.assertEqual(resolved,packet)
        self.assertEqual(files['source.pdf'],self.path.with_name('source.pdf'))
        self.assertEqual((root/'packet.json').read_bytes(),before)

    def test_completed_review_context_can_describe_new_render_without_web_archive(self):
        root,archive,job,packet,original=self.archived_source_fixture(repair_intent=True)
        (archive/'packet.json').unlink()
        with patch.object(repair,'collected',return_value=original):
            descriptor,files,_=queue.source_inputs(self.catalog,job,self.path,self.card)
        self.assertTrue(descriptor['render_from_verified_source'])
        self.assertEqual(descriptor['source_binding']['review_id'],self.job['id'])
        self.assertEqual(files['source-context.json'],self.folder/'source-context.json')
        self.assertFalse((root/'packet.json').exists())

    def test_direct_render_reads_verified_pdf_and_checks_actual_text(self):
        import pymupdf
        folder=self.root/'direct-render';folder.mkdir()
        with pymupdf.open() as document:
            document.new_page().insert_text((30,40),'Original source observation.')
            document.save(folder/'source.pdf')
        with pymupdf.open(folder/'source.pdf') as source:text=source[0].get_text()
        atomic_json(folder/'source-context.json',{'source_text':[{'source_page':1,'text':text}]})
        atomic_json(folder/'card-review.json',{'figures':[],'equations':[],'tables':[]})
        atomic_json(folder/'request.json',{'input_folder':str(folder),'output_folder':str(folder),'image_roots':[str(folder)],
            'packet':{'page_count':1,'page_manifest':[],'render_from_verified_source':True}})
        before=(folder/'source.pdf').read_bytes();queue.visual(folder/'request.json')
        with pymupdf.open(folder/'visual.pdf') as visual:
            self.assertEqual(len(visual),1);self.assertTrue(visual[0].get_images())
        self.assertEqual((folder/'source.pdf').read_bytes(),before)
        atomic_json(folder/'source-context.json',{'source_text':[{'source_page':1,'text':'changed'}]})
        with self.assertRaisesRegex(ValueError,'文字层'):queue.visual(folder/'request.json')

    def setUp(self):
        self.fixture=fixtures.ReviewQueue();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.catalog=self.fixture.catalog;self.config=self.fixture.config;self.root=self.fixture.root
        job,self.path,self.card=self.fixture.card()
        self.folder,self.packet=self.fixture.packet(job,self.card)
        shutil.copy2(self.path.with_name('source.pdf'),self.folder/'source.pdf')
        self.packet['input_hashes']['source.pdf']=digest(self.folder/'source.pdf')
        atomic_json(self.folder/'packet.json',self.packet)
        feedback=self.fixture.feedback();feedback['missing_inputs']=['Actual card images missing']
        self.fixture.receipt(self.folder,self.packet,feedback)
        receipt=json.loads((self.folder/'attempt.json').read_text());receipt['finished']=1
        atomic_json(self.folder/'attempt.json',receipt)
        _,result=queue.parse_review(json.dumps(feedback),self.folder)
        queue.update(self.catalog,job['id'],'needs_user',result=result)
        self.job=queue.rows(self.catalog)[0]

    def prepare(self,catalog,job,config,**options):
        self.assertFalse(options['locate_quote_pages'])
        folder=Path(job['folder'])
        for name in self.packet['input_hashes']:shutil.copy2(self.folder/name,folder/name)
        for name in ('bundle.zip','prompt-actual.txt'):shutil.copy2(self.folder/name,folder/name)
        atomic_json(folder/'card-image-manifest.json',{'images':[]})
        packet={**self.packet,'job_id':job['id'],'card_sha256':job['card_sha256'],
                'source_original_sha256':job['source_sha256'],'review_images_version':1,'review_materials_version':2}
        atomic_json(folder/'packet.json',packet);return True

    def test_complete_old_report_is_preserved_and_new_packet_is_queued_once(self):
        before=self.path.read_bytes();old={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        with patch.object(queue,'prepare',side_effect=self.prepare):
            result=repair.repair(self.catalog,self.job,self.config)
        current=queue.rows(self.catalog)[0]
        self.assertEqual(current['state'],'ready');self.assertNotEqual(current['id'],self.job['id'])
        self.assertEqual(current['id'],result['new_review_id']);self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()},old)
        self.assertFalse((Path(current['folder'])/'attempt.json').exists())
        self.assertEqual(json.loads(current['result'])['weighted_score'],90)
        self.assertTrue(queue.public_result(dict(current))['material_recheck_pending'])
        with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
        new_folder=Path(current['folder']);new_packet=json.loads((new_folder/'packet.json').read_text())
        self.fixture.receipt(new_folder,new_packet,self.fixture.feedback())
        receipt=json.loads((new_folder/'attempt.json').read_text())
        receipt.update(finished=2,conversation_url='https://chatgpt.com/c/new-material-review')
        atomic_json(new_folder/'attempt.json',receipt)
        queue.update(self.catalog,current['id'],'needs_user')
        with self.assertRaisesRegex(ValueError,'没有新增'):
            repair.repair(self.catalog,queue.rows(self.catalog)[0],self.config)

    def test_unknown_or_corrupted_receipt_never_gets_new_materials(self):
        for change in ('unknown','raw','inputs','prompt','unfinished'):
            with self.subTest(change=change):
                original=(self.folder/'attempt.json').read_bytes();raw=(self.folder/'response-raw.txt').read_bytes()
                receipt=json.loads(original)
                if change=='unknown':receipt['state']='needs_inspection'
                elif change=='raw':(self.folder/'response-raw.txt').write_text('changed')
                elif change=='inputs':receipt['inputs']={}
                elif change=='prompt':receipt['actual_prompt_sha256']='wrong'
                else:receipt.pop('finished')
                atomic_json(self.folder/'attempt.json',receipt)
                with patch.object(queue,'prepare') as prepare:
                    with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
                    prepare.assert_not_called()
                (self.folder/'attempt.json').write_bytes(original);(self.folder/'response-raw.txt').write_bytes(raw)

    def test_paused_protected_or_changed_cards_are_not_requeued(self):
        atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
        with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
        (self.root/'card-review-control.json').unlink()
        self.catalog.event(self.job['paper_id'],'human_decision',{})
        with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
        self.path.write_text(self.path.read_text()+' ')
        with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)

    def test_source_ambiguity_is_kept_and_bounded_repairs_are_enforced(self):
        queue.update(self.catalog,self.job['id'],'needs_user',result={'full_source_checked':True,'weighted_score':90})
        with self.assertRaisesRegex(ValueError,'材料检查未完成'):
            repair.repair(self.catalog,queue.rows(self.catalog)[0],self.config)
        queue.update(self.catalog,self.job['id'],'needs_user',result=json.loads(self.job['result']))
        for _ in range(2):self.catalog.event(self.job['paper_id'],'card_review_material_repair',{'card_sha256':self.job['card_sha256']})
        with self.assertRaisesRegex(ValueError,'两次上限'):repair.repair(self.catalog,queue.rows(self.catalog)[0],self.config)

    def test_interrupted_empty_candidate_resumes_once_without_changing_old_report(self):
        old=(self.folder/'response-raw.txt').read_bytes()
        with patch.object(queue,'prepare',side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
        self.assertEqual(queue.rows(self.catalog)[0],self.job)
        with patch.object(queue,'prepare',side_effect=self.prepare):
            result=repair.repair(self.catalog,self.job,self.config)
        self.assertEqual(queue.rows(self.catalog)[0]['id'],result['new_review_id'])
        self.assertEqual((self.folder/'response-raw.txt').read_bytes(),old)
        with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)

    def test_deterministic_local_prepare_failure_does_not_repeat_same_version(self):
        with patch.object(queue,'prepare',side_effect=ValueError('ZIP too large')) as prepare:
            with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
            with self.assertRaisesRegex(ValueError,'同版本'):repair.repair(self.catalog,self.job,self.config)
            self.assertEqual(prepare.call_count,1)

    def test_newer_partial_normalization_is_archived_only_with_original_input_proof(self):
        with patch.object(queue,'prepare',side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
        candidate=next(self.folder.parent.glob('*/repair-intent.json')).parent
        (candidate/'source.pdf').write_bytes(b'new normalized version')
        (candidate/'source-context.json').write_bytes(b'new normalized context')
        web=self.root/'web_cards'/self.job['paper_id'];web.mkdir(parents=True)
        atomic_json(web/'packet.json',{'paper_id':self.job['paper_id'],'source_original_sha256':self.job['source_sha256'],
            'input_hashes':{n:digest(candidate/n) for n in ('source.pdf','source-context.json')}})
        descriptor={'input_hashes':{'source.pdf':digest(self.path.with_name('source.pdf'))}}
        with patch.object(queue,'source_inputs',return_value=(descriptor,{},self.path.parent)), \
                patch.object(queue,'prepare',side_effect=self.prepare):
            result=repair.repair(self.catalog,self.job,self.config)
        archive=next(self.folder.parent.glob(candidate.name+'-partial-*'))
        self.assertEqual((archive/'source.pdf').read_bytes(),b'new normalized version')
        self.assertEqual((candidate/'source.pdf').read_bytes(),self.path.with_name('source.pdf').read_bytes())
        self.assertEqual(queue.rows(self.catalog)[0]['id'],result['new_review_id'])

    def test_interrupted_partial_keeps_old_bytes_in_archive_and_uses_separate_media(self):
        with patch.object(queue,'prepare',side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
        candidate=next(self.folder.parent.glob('*/repair-intent.json')).parent
        web=self.root/'web_cards'/self.job['paper_id'];web.mkdir(parents=True)
        source=web/'source.pdf';source.write_bytes((self.folder/'source.pdf').read_bytes())
        atomic_json(web/'packet.json',{'input_hashes':{'source.pdf':digest(source)}})
        (candidate/'source.pdf').write_bytes(source.read_bytes())
        (candidate/'card-original.json').write_bytes(self.path.read_bytes())
        self.config['card_review']['media_root']=str(self.root/'ssd')
        target=self.root/'ssd/partial.pdf';target.parent.mkdir();target.write_bytes(b'partial immutable visual')
        (candidate/'visual.pdf').symlink_to(target)
        def prepare(catalog,job,config,**options):
            self.assertNotEqual(config['card_review']['media_root'],self.config['card_review']['media_root'])
            return self.prepare(catalog,job,config,**options)
        with patch.object(queue,'prepare',side_effect=prepare):result=repair.repair(self.catalog,self.job,self.config)
        archive=next(self.folder.parent.glob(candidate.name+'-partial-*'))
        self.assertEqual((archive/'visual.pdf').read_bytes(),b'partial immutable visual')
        self.assertEqual(target.read_bytes(),b'partial immutable visual')
        self.assertEqual((archive/'card-original.json').read_bytes(),self.path.read_bytes())
        self.assertEqual(queue.rows(self.catalog)[0]['id'],result['new_review_id'])

    def test_crash_between_partial_move_and_new_intent_resumes_separate_storage(self):
        with patch.object(queue,'prepare',side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
        candidate=next(self.folder.parent.glob('*/repair-intent.json')).parent
        web=self.root/'web_cards'/self.job['paper_id'];web.mkdir(parents=True)
        atomic_json(web/'packet.json',{'input_hashes':{'source.pdf':digest(self.folder/'source.pdf')}})
        (candidate/'source.pdf').write_bytes((self.folder/'source.pdf').read_bytes())
        self.config['card_review']['media_root']=str(self.root/'ssd')
        write=repair.atomic_json
        def interrupt(path,value):
            if Path(path)==candidate/'repair-intent.json' and 'partial_archive' in value:
                raise OSError('Interrupted after directory move')
            return write(path,value)
        with patch.object(repair,'atomic_json',side_effect=interrupt),patch.object(queue,'prepare') as prepare:
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
            prepare.assert_not_called()
        self.assertTrue(candidate.with_name('.'+candidate.name+'.partial-recovery.json').exists())
        def prepare(catalog,job,config,**options):
            self.assertNotEqual(config['card_review']['media_root'],self.config['card_review']['media_root'])
            return self.prepare(catalog,job,config,**options)
        with patch.object(queue,'prepare',side_effect=prepare):result=repair.repair(self.catalog,self.job,self.config)
        self.assertEqual(queue.rows(self.catalog)[0]['id'],result['new_review_id'])
        self.assertFalse(candidate.with_name('.'+candidate.name+'.partial-recovery.json').exists())

    def test_interrupted_candidate_with_changed_intent_or_unknown_request_stays_protected(self):
        with patch.object(queue,'prepare',side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):repair.repair(self.catalog,self.job,self.config)
        candidate=next(self.folder.parent.glob('*/repair-intent.json'));original=candidate.read_bytes()
        web=self.root/'web_cards'/self.job['paper_id'];web.mkdir(parents=True)
        atomic_json(web/'packet.json',{'input_hashes':{'source.pdf':digest(self.folder/'source.pdf')}})
        for kind in ('intent','attempt','actual_material'):
            with self.subTest(kind=kind):
                if kind=='intent':
                    value=json.loads(original);value['old_raw_sha256']='changed';atomic_json(candidate,value)
                elif kind=='attempt':atomic_json(candidate.parent/'attempt.json',{'state':'needs_inspection'})
                else:(candidate.parent/'source.pdf').write_bytes(b'partial source')
                with patch.object(queue,'prepare') as prepare:
                    with self.assertRaises(ValueError):repair.repair(self.catalog,self.job,self.config)
                    prepare.assert_not_called()
                candidate.write_bytes(original)
                (candidate.parent/'attempt.json').unlink(missing_ok=True)
                (candidate.parent/'source.pdf').unlink(missing_ok=True)

    def test_pause_during_preparation_preserves_candidate_without_queue_change(self):
        def prepare(*args,**options):
            result=self.prepare(*args,**options)
            atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
            return result
        with patch.object(queue,'prepare',side_effect=prepare):
            with self.assertRaisesRegex(ValueError,'暂停'):repair.repair(self.catalog,self.job,self.config)
        self.assertEqual(queue.rows(self.catalog)[0],self.job)

    def test_supplement_coverage_is_required_without_inventing_pass_or_scores(self):
        packet={**self.packet,'supplement':{'page_count':2}}
        atomic_json(self.folder/'packet.json',packet)
        feedback=self.fixture.feedback()
        result=queue.parse_review(json.dumps(feedback),self.folder)[1]
        self.assertFalse(result['full_source_checked']);self.assertEqual(result['weighted_score'],90)
        self.assertEqual(result['action'],'needs_user')
        feedback['supplement_pages_reviewed']=[1,2]
        self.assertEqual(queue.parse_review(json.dumps(feedback),self.folder)[1]['action'],'pass')
        feedback['supplement_pages_reviewed']=[True,2]
        self.assertFalse(queue.parse_review(json.dumps(feedback),self.folder)[1]['full_source_checked'])

    def test_supplement_provenance_and_original_version_must_match(self):
        folder=self.root/'card_review_supplements'/self.job['paper_id'];folder.mkdir(parents=True)
        (folder/'supplement.pdf').write_bytes(b'PDF')
        record={'paper_id':self.job['paper_id'],'source_original_sha256':self.job['source_sha256'],
                'doi':'10.9999/Synthetic','identity_verified':True,'file':'supplement.pdf','sha256':digest(folder/'supplement.pdf'),
                'publisher_link':'https://publisher.example/article'}
        for field,value in [('source_original_sha256','wrong'),('doi','10.other'),('identity_verified',False),('sha256','wrong'),('file','../outside.pdf')]:
            atomic_json(folder/'manifest.json',{**record,field:value})
            with self.assertRaises((ValueError,OSError)):repair.supplement_packet(self.catalog,self.job,self.config,self.folder)

    def test_metadata_changes_without_new_supplement_bytes_do_not_retry(self):
        folder=self.root/'card_review_supplements'/self.job['paper_id'];folder.mkdir(parents=True)
        atomic_json(folder/'manifest.json',{'sha256':'same-pdf','captured_at':'different-time'})
        packet={**self.packet,'review_materials_version':2,'supplement':{'source_sha256':'same-pdf','registry_sha256':'old-registry'}}
        with patch.object(repair,'collected',return_value=packet),patch.object(queue,'prepare') as prepare:
            with self.assertRaisesRegex(ValueError,'没有新增'):repair.repair(self.catalog,self.job,self.config)
            prepare.assert_not_called()


if __name__=='__main__':unittest.main()
