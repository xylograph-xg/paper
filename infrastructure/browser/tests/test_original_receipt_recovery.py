import copy
import hashlib
import json
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch
from core.catalog import Catalog
from core.services import atomic_json
from browser import original_receipt_recovery as recovery
from browser.shared_pool_store import PoolSnapshot
from cards.web_card_inputs import digest


class OriginalReceiptRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.catalog=Catalog(self.root/'catalog.sqlite3')
        with self.catalog.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shared_page_backlog(target_id TEXT,state TEXT)')
        self.pid=self.catalog.upsert({'title':'Original source'})
        self.source=self.root/'original.pdf';self.source.write_bytes(b'original source identity')
        self.catalog.update(self.pid,asset_path=str(self.source),asset_hash=digest(self.source),acquisition='available')
        self.config={'catalog_path':str(self.catalog.path),'web_cards':{'enabled':True,'provider':'chatgpt','allowed_providers':['chatgpt']}}
        folder=self.root/'web_cards'/self.pid;self.attempt=folder/'chatgpt/attempt.json';self.attempt.parent.mkdir(parents=True)
        self.prompt='Original web-card-'+self.pid+'-abcdef source-only request'
        for name,raw in [('source.pdf',b'clean source'),('prompt.txt',self.prompt.encode())]:(folder/name).write_bytes(raw)
        packet={'paper_id':self.pid,'source_original_sha256':digest(self.source),
            'input_hashes':{n:digest(folder/n) for n in ('source.pdf','prompt.txt')}}
        atomic_json(folder/'packet.json',packet);self.attempt.with_name('prompt-actual.txt').write_text(self.prompt)
        self.original={'state':'submitted','target_id':'old','created':1234,'send_click_started':True,
            'conversation_url':'https://chatgpt.com/c/original-conversation',
            'actual_prompt_sha256':digest(self.attempt.with_name('prompt-actual.txt')),'inputs':packet['input_hashes'],
            'settings':{'model':'GPT-6','effort':'High'}}
        atomic_json(self.attempt,self.original);self.original_bytes=self.attempt.read_bytes()
        archive=self.root/'shared-page-repairs'/'retired'/'diagnostics';archive.mkdir(parents=True)
        names=('health.json','body.txt','page.html','page.png','capture.json','target-history-before.json')
        for name in names:(archive/name).write_bytes(b'full original archive')
        (archive/'ledger-before.json').write_bytes(self.original_bytes)
        (archive/'prompt-before.txt').write_text(self.prompt)
        self.journal={'state':'ready','close_authorized':True,'slot_id':'01','window_id':55,'old_target_id':'old',
            'record_hashes':{str(self.attempt):digest(self.attempt)},
            'archive_hashes':{p.name:digest(p) for p in archive.iterdir()}}
        atomic_json(archive.parent/'journal.json',self.journal)
        self.registry={'window_id':77,'slots':[{'slot_id':'01','target_id':'new',
            'replacement_history':[{'target_id':'old','diagnostics':'original archive'}]}]}
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        self.pool=PoolSnapshot({'windows':{'new':{'state':'ready_blank'}}})
        atomic_json(self.root/'gpt-window-pool.json',dict(self.pool))
        self.page=Mock();self.page.url='https://chatgpt.com/'
        self.page.goto.side_effect=lambda url,**kw:setattr(self.page,'url',url)
        self.pages={'new':self.page};self.snapshot={'inspection_complete':True,'errors':[],
            'url':'https://chatgpt.com/','composer_available':True,'streaming':False,'uploading':False,
            'user_texts':[],'answer_texts':[],'answer_element_count':0,'draft':'','attachments':0,
            'login':False,'verification':False,'quota':False}
        self.snap=patch.object(recovery,'snapshot_page',side_effect=lambda tid,page:copy.deepcopy({**self.snapshot,'url':page.url})).start()
        self.addCleanup(patch.stopall)
        self.guard=patch.object(recovery,'require_slot').start()

    def run_owner(self,**kw):
        return recovery.run_once(self.config,self.catalog,Mock(),self.pool,self.pages,
            complete=kw.pop('complete',True),stopping=lambda:False,lock_factory=lambda **k:nullcontext(),**kw)

    def review_materials(self, job_id='a'*24):
        folder=self.root/'card_reviews'/self.pid/job_id;folder.mkdir(parents=True)
        card=self.root/'current-card.json';card.write_bytes(b'current card version')
        self.catalog.update(self.pid,card_path=str(card))
        prompt='Independent source review card-review-'+job_id+'; current source evidence'
        for name,raw in [('source.pdf',b'clean source'),('prompt.txt',prompt.encode()),('card-original.json',card.read_bytes())]:
            (folder/name).write_bytes(raw)
        packet={'job_id':job_id,'card_sha256':digest(card),'source_original_sha256':digest(self.source),
                'input_hashes':{name:digest(folder/name) for name in ('source.pdf','prompt.txt','card-original.json')}}
        atomic_json(folder/'packet.json',packet);(folder/'prompt-actual.txt').write_text(prompt)
        saved={**self.original,'review_id':job_id,'inputs':packet['input_hashes'],
               'actual_prompt_sha256':digest(folder/'prompt-actual.txt')}
        atomic_json(folder/'attempt.json',saved)
        return (folder/'attempt.json').resolve(),saved,(folder/'packet.json').resolve(),card.resolve()

    def test_review_recovery_uses_its_version_packet(self):
        source,saved,packet,_=self.review_materials()
        self.assertEqual(recovery._source(self.catalog,source,saved),digest(packet))
        self.page.goto.assert_not_called()

    def test_review_automatic_successor_keeps_full_material_identity(self):
        source,saved,packet,_=self.review_materials('b'*24+'-auto-1792616961')
        self.assertEqual(recovery._source(self.catalog,source,saved),digest(packet))

    def test_review_missing_version_packet_never_falls_back_to_parent(self):
        source,saved,packet,_=self.review_materials()
        packet.rename(packet.parent.parent/'packet.json')
        with self.assertRaises(FileNotFoundError):recovery._source(self.catalog,source,saved)

    def test_review_source_card_job_and_frozen_material_guards_remain(self):
        source,saved,packet,card=self.review_materials();original=packet.read_bytes()
        for field,value in [('job_id','c'*24),('source_original_sha256','changed'),('card_sha256','changed')]:
            data=json.loads(original);data[field]=value;atomic_json(packet,data)
            with self.subTest(field=field),self.assertRaises(ValueError):recovery._source(self.catalog,source,saved)
        packet.write_bytes(original)
        for path in (self.source,card,packet.with_name('source.pdf'),source.with_name('prompt-actual.txt')):
            raw=path.read_bytes();path.write_bytes(raw+b' changed')
            with self.subTest(path=path.name),self.assertRaises(ValueError):recovery._source(self.catalog,source,saved)
            path.write_bytes(raw)

    def test_health_inventory_uses_validated_collection_target_and_preserves_original(self):
        rid=self.run_owner()['started'][0]
        from browser.shared_page_repair import _records
        records,latest=_records(self.root)
        self.assertEqual(latest['new']['_ledger_path'],str((self.root/'original-receipts'/rid/'attempt.json').resolve()))
        self.assertEqual(latest['new']['target_id'],'new')
        self.assertEqual(latest['old']['target_id'],'old')
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)
        side=self.root/'original-receipts'/rid/'attempt.json';value=json.loads(side.read_text())
        value['settings']['model']='changed';atomic_json(side,value)
        self.assertNotIn('new',_records(self.root)[1])

    def test_collection_empty_terminal_uses_existing_age_and_two_round_guards(self):
        self.run_owner()
        from browser.shared_page_repair import _records,_terminal_empty_restart
        from browser.shared_page_health import classify
        record=_records(self.root)[1]['new']
        config={'web_cards':{'shared_window':{'health_repair':{'hard_restart_after_seconds':3600}}}}
        snapshot={**self.snapshot,'target_id':'new','url':self.original['conversation_url'],
                  'checked_at':5000,'user_texts':[self.prompt],'terminal_complete':True}
        def health(value,previous=None):
            return classify(value,self.pool['windows']['new'],record,urls=[value['url']],
                previous=previous,record_paths=[record['_ledger_path']],history_roots=(),target_history_complete=True)
        first=health(snapshot);self.assertEqual(first['health'],'terminal_empty',first)
        self.assertFalse(_terminal_empty_restart(config,first,record,at=5000))
        self.assertFalse(_terminal_empty_restart(config,first,record,first,at=5029))
        second=health({**snapshot,'checked_at':5030},first)
        self.assertTrue(_terminal_empty_restart(config,second,record,first,at=5030))
        self.assertFalse(_terminal_empty_restart(config,second,{**record,'created':4500},first,at=5030))
        for key,value in [('streaming',True),('uploading',True),('quota',True),('login',True),
                          ('verification',True),('draft','new draft'),('attachments',1)]:
            h=health({**snapshot,key:value,'checked_at':5060},second)
            with self.subTest(key=key):self.assertFalse(_terminal_empty_restart(config,h,record,second,at=5060))
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def closed_empty_read(self):
        rid=self.run_owner()['started'][0];proof_path=self.root/'original-receipts'/rid/'proof.json'
        side=proof_path.with_name('attempt.json');directory=self.root/'shared-page-repairs'/'retired-read'
        archive=directory/'diagnostics';archive.mkdir(parents=True)
        for name in ('health.json','body.txt','page.html','page.png','capture.json'):(archive/name).write_bytes(b'original empty terminal evidence')
        (archive/'ledger-before.json').write_bytes(side.read_bytes());(archive/'prompt-before.txt').write_text(self.prompt)
        journal={**self.journal,'id':'retired-read','old_target_id':'new','requeue_allowed':False,
            'terminal_empty_restart':True,'health':{'health':'terminal_empty','terminal_empty_check':{'rounds':2}},
            'record_hashes':{str(side.resolve()):digest(side)},'archive_hashes':{p.name:digest(p) for p in archive.iterdir()}}
        atomic_json(directory/'journal.json',journal)
        self.registry['slots'][0].update(target_id='replacement',replacement_history=[{'target_id':'new','repair_id':'retired-read'}])
        atomic_json(self.root/'shared-gpt-window.json',self.registry);self.pages={}
        return rid,proof_path,side,archive

    def test_closed_empty_read_is_retired_without_answer_or_original_mutation_or_replay(self):
        rid,path,side,archive=self.closed_empty_read();side_bytes=side.read_bytes()
        original_retirement=json.loads(path.read_text())['retirement_journal']
        result=self.run_owner();self.assertEqual(result['retired_empty'],[rid],result)
        self.assertFalse(result['collected']);self.assertFalse(result['started'])
        value=json.loads(path.read_text());self.assertEqual(value['state'],'retired_empty')
        self.assertEqual(value['retirement_journal'],original_retirement)
        self.assertFalse(value['answer_collected']);self.assertFalse(value['resubmission_allowed'])
        self.assertEqual(side.read_bytes(),side_bytes);self.assertEqual(self.attempt.read_bytes(),self.original_bytes)
        self.assertFalse(recovery.collection_ledgers(self.root))
        self.assertFalse(self.run_owner()['started']);self.page.goto.assert_called_once()

    def test_damaged_closed_empty_archive_cannot_retire_or_resend_original(self):
        rid,path,side,archive=self.closed_empty_read();(archive/'body.txt').write_text('changed')
        result=self.run_owner();self.assertTrue(result['blocked']);self.assertFalse(result['retired_empty'])
        self.assertEqual(json.loads(path.read_text())['state'],'observing')
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes);self.page.goto.assert_called_once()

    def mhtml_closed_archive(self,archive):
        from email.message import EmailMessage
        (archive/'page.png').unlink()
        message=EmailMessage();message.set_type('multipart/related')
        message['Snapshot-Content-Location']=self.original['conversation_url']
        html=EmailMessage();html.set_content('<html>Complete original page</html>',subtype='html')
        html['Content-Location']=self.original['conversation_url'];message.attach(html)
        (archive/'page.mhtml').write_bytes(message.as_bytes())
        atomic_json(archive/'capture.json',{'method':'resident_cdp_mhtml','screenshot_available':False,
                                         'foreground_changed':False})
        self.bind_archive(archive)

    def bind_archive(self,archive):
        path=archive.parent/'journal.json';journal=json.loads(path.read_text())
        journal['archive_hashes']={p.name:digest(p) for p in archive.iterdir() if p.name!='archive-manifest.json'}
        atomic_json(path,journal)
        atomic_json(archive/'archive-manifest.json',{'complete':True,'files':journal['archive_hashes']})

    def test_closed_empty_mhtml_retirement_preserves_original_and_side_ledger(self):
        rid,path,side,archive=self.closed_empty_read();self.mhtml_closed_archive(archive)
        side_bytes=side.read_bytes();result=self.run_owner()
        self.assertEqual(result['retired_empty'],[rid],result)
        self.assertFalse(result['collected']);self.assertFalse(result['started'])
        proof=json.loads(path.read_text());self.assertFalse(proof['resubmission_allowed'])
        self.assertFalse(proof['answer_collected']);self.assertEqual(side.read_bytes(),side_bytes)
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes);self.page.goto.assert_called_once()

    def test_mhtml_retirement_requires_complete_capture_and_same_formal_url(self):
        _,_,side,archive=self.closed_empty_read();self.mhtml_closed_archive(archive)
        valid={p.name:p.read_bytes() for p in archive.iterdir()}
        journal=archive.parent/'journal.json';journal_bytes=journal.read_bytes()
        changes=(
            ('capture.json',lambda v:{**v,'method':'unknown'}),
            ('capture.json',lambda v:{**v,'screenshot_available':True}),
            ('capture.json',lambda v:{**v,'foreground_changed':True}),
            ('archive-manifest.json',lambda v:{**v,'complete':False}),
            ('archive-manifest.json',lambda v:{**v,'files':{}}),
        )
        for filename,change in changes:
            for name,raw in valid.items():(archive/name).write_bytes(raw)
            journal.write_bytes(journal_bytes)
            atomic_json(archive/filename,change(json.loads((archive/filename).read_text())))
            if filename=='capture.json':self.bind_archive(archive)
            with self.subTest(filename=filename,change=change):
                self.assertIsNone(recovery._retirement(self.root,recovery.read_attempt(side)))
        for name,raw in valid.items():(archive/name).write_bytes(raw)
        raw=valid['page.mhtml']
        for changed in (raw.replace(self.original['conversation_url'].encode(),b'https://chatgpt.com/c/another'),
                        raw.replace(b'multipart/related',b'multipart/mixed'),
                        raw.replace(b'Content-Location: https:',b'Content-Location: http:')):
            (archive/'page.mhtml').write_bytes(changed);self.bind_archive(archive)
            with self.subTest(mhtml=changed[:70]):
                self.assertIsNone(recovery._retirement(self.root,recovery.read_attempt(side)))

    def test_tampered_mhtml_archive_never_retires_or_resends_original(self):
        _,path,_,archive=self.closed_empty_read();self.mhtml_closed_archive(archive)
        (archive/'page.mhtml').write_bytes(b'changed')
        result=self.run_owner();self.assertTrue(result['blocked']);self.assertFalse(result['retired_empty'])
        self.assertEqual(json.loads(path.read_text())['state'],'observing')
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes);self.page.goto.assert_called_once()

    def test_missing_all_page_captures_keeps_original_retirement_protected(self):
        _,_,side,archive=self.closed_empty_read();(archive/'page.png').unlink();self.bind_archive(archive)
        self.assertIsNone(recovery._retirement(self.root,recovery.read_attempt(side)))
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes);self.page.goto.assert_called_once()

    def test_opens_only_original_url_in_replacement_slot_without_changing_original_submit(self):
        result=self.run_owner();self.assertEqual(len(result['started']),1,result)
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)
        self.page.goto.assert_called_once_with(self.original['conversation_url'],wait_until='domcontentloaded',timeout=10000)
        ledgers=recovery.collection_ledgers(self.root);self.assertEqual(set(ledgers),{'new'})
        self.assertEqual(ledgers['new'][1],{**self.original,'target_id':'new'})
        self.page.click.assert_not_called();self.page.fill.assert_not_called()

    def test_full_answer_promotes_original_with_original_target_and_no_new_submit(self):
        result=self.run_owner();rid=result['started'][0];folder=self.root/'original-receipts'/rid
        side=json.loads((folder/'attempt.json').read_text());raw='{"answer":"Complete original source evidence"}'
        (folder/'response-raw.txt').write_text(raw)
        side.update(state='response_saved',raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),observed_complete_at=time.time())
        atomic_json(folder/'attempt.json',side)
        self.snapshot.update(user_texts=[self.prompt],answer_texts=[raw],answer_element_count=1,draft='\n')
        with patch('web_gpt.core._message_text',return_value=raw):report=self.run_owner()
        self.assertEqual(report['collected'],[rid],report)
        promoted=json.loads(self.attempt.read_text())
        for k,v in self.original.items():
            if k!='state':self.assertEqual(promoted[k],v)
        self.assertEqual(promoted['state'],'response_saved');self.assertEqual(promoted['collection_target_id'],'new')
        self.assertEqual(self.attempt.with_name('response-raw.txt').read_text(),raw)
        self.assertEqual(self.pool['windows']['new']['state'],'ready')
        self.page.goto.assert_called_once();self.assertFalse(recovery.collection_ledgers(self.root))

    def test_unknown_navigation_is_never_replayed_on_next_owner_pass(self):
        self.page.goto.side_effect=TimeoutError('navigation result unknown')
        self.assertEqual(len(self.run_owner()['started']),1)
        self.assertFalse(self.run_owner()['started']);self.page.goto.assert_called_once()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_paused_lane_and_incomplete_inventory_never_navigate(self):
        pause=self.root/'web-card-control.json';pause.write_text('{"paused_by_user":true}')
        before=pause.read_bytes();self.assertFalse(self.run_owner()['started'])
        self.assertEqual(pause.read_bytes(),before);self.assertFalse(self.run_owner(complete=False)['started'])
        self.page.goto.assert_not_called();self.snap.assert_not_called()

    def test_drafts_generation_uploads_and_unavailable_leases_are_preserved(self):
        for field,value in [('draft','new user draft'),('streaming',True),('uploading',True),('quota',True),('attachments',1)]:
            with self.subTest(field=field):
                old=self.snapshot[field];self.snapshot[field]=value
                self.assertFalse(self.run_owner()['started']);self.snapshot[field]=old
        self.assertFalse(self.run_owner(target_lease=lambda tid:nullcontext(False))['started'])
        self.page.goto.assert_not_called();self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_source_change_and_same_slot_cas_change_refuse_recovery(self):
        self.source.write_bytes(b'changed original')
        report=self.run_owner();self.assertFalse(report['started']);self.assertTrue(report['blocked'])
        self.page.goto.assert_not_called();self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_unregistered_original_and_nonformal_url_do_not_gain_navigation_authority(self):
        self.journal['close_authorized']=False
        atomic_json(self.root/'shared-page-repairs/retired/journal.json',self.journal)
        self.assertFalse(self.run_owner()['started']);self.page.goto.assert_not_called()

    def test_modified_collection_copy_cannot_overwrite_original_receipt(self):
        rid=self.run_owner()['started'][0];side=self.root/'original-receipts'/rid/'attempt.json'
        value=json.loads(side.read_text());value['settings']['model']='Other';atomic_json(side,value)
        self.assertFalse(recovery.collection_ledgers(self.root))
        error=json.loads((self.root/'original-receipt-collection-errors.json').read_text())
        self.assertIn('副本身份',error['errors'][0]['error'])
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_one_damaged_recovery_proof_does_not_hide_other_original_receipts(self):
        self.run_owner()
        bad=self.root/'original-receipts/bad/proof.json';bad.parent.mkdir();bad.write_text('{broken JSON')
        for content in ('{broken JSON','[]','{}'):
            bad.write_text(content)
            ledgers=recovery.collection_ledgers(self.root)
            self.assertEqual(set(ledgers),{'new'})
            self.assertEqual(len(json.loads((self.root/'original-receipt-collection-errors.json').read_text())['errors']),1)
            report=self.run_owner();self.assertTrue(report['blocked'])
        self.page.goto.assert_called_once()

    def test_legacy_archive_without_target_history_keeps_exact_original_identity(self):
        self.journal['record_hashes']={}
        self.journal['record']={**self.original,'_ledger_path':str(self.attempt),'_ledger_sha256':digest(self.attempt)}
        atomic_json(self.root/'shared-page-repairs/retired/journal.json',self.journal)
        self.assertEqual(len(self.run_owner()['started']),1)
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_older_sent_receipt_is_bound_by_complete_history_despite_new_unsent_ledger(self):
        archive=self.root/'shared-page-repairs/retired/diagnostics'
        atomic_json(archive/'target-history-before.json',[{'path':str(self.attempt),'sha256':digest(self.attempt),'record':self.original}])
        (archive/'ledger-before.json').write_text('{"state":"not_sent","send_click_started":false}')
        (archive/'prompt-before.txt').write_text('different unsent prompt')
        self.journal['archive_hashes']={p.name:digest(p) for p in archive.iterdir()}
        atomic_json(archive.parent/'journal.json',self.journal)
        self.assertEqual(len(self.run_owner()['started']),1)
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_pre_navigation_crash_resumes_prepared_proof_once(self):
        with patch.object(recovery,'_navigate',side_effect=ValueError('crash before navigation')):
            result=self.run_owner();self.assertTrue(result['blocked'])
        self.page.goto.assert_not_called()
        self.run_owner();self.page.goto.assert_called_once()
        self.assertEqual(set(recovery.collection_ledgers(self.root)),{'new'})

    def test_claimed_origin_slot_uses_only_another_compatible_blank_fixed_slot(self):
        page=Mock();page.url='https://chatgpt.com/'
        page.goto.side_effect=lambda url,**kw:setattr(page,'url',url)
        self.pages['spare']=page;self.pool['windows']['spare']={'state':'ready_blank'}
        atomic_json(self.root/'gpt-window-pool.json',dict(self.pool))
        from browser.shared_pool_store import load_pool
        self.pool=load_pool(self.root/'gpt-window-pool.json')
        self.registry['slots'].append({'slot_id':'02','target_id':'spare'})
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        with self.catalog.connect() as db:db.execute("INSERT INTO shared_page_backlog VALUES('new','claimed')")
        report=self.run_owner();self.assertEqual(len(report['started']),1,report)
        self.page.goto.assert_not_called();page.goto.assert_called_once()

    def test_native_empty_composer_newline_is_not_a_user_draft(self):
        self.snapshot['draft']=' \n\t '
        report=self.run_owner()
        self.assertEqual(len(report['started']),1,report)
        self.page.goto.assert_called_once()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_unreadable_composer_value_remains_protected(self):
        self.snapshot['draft']=0
        report=self.run_owner()
        self.assertEqual(report['started'],[])
        self.page.goto.assert_not_called()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def _spare_collection_page(self):
        from browser.shared_pool_store import load_pool
        page=Mock();page.url='https://chatgpt.com/'
        page.goto.side_effect=lambda url,**kw:setattr(page,'url',url)
        self.pages['spare']=page;self.pool['windows']['spare']={'state':'ready_blank'}
        atomic_json(self.root/'gpt-window-pool.json',dict(self.pool))
        self.pool=load_pool(self.root/'gpt-window-pool.json')
        self.registry['slots'].append({'slot_id':'02','target_id':'spare'})
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        return page

    def test_protected_first_candidate_does_not_starve_other_safe_fixed_slot(self):
        spare=self._spare_collection_page()
        self.snap.side_effect=lambda tid,page:copy.deepcopy({**self.snapshot,'url':page.url,
            'draft':'protected unrelated draft' if tid=='new' else ''})
        result=self.run_owner()
        self.assertEqual(len(result['started']),1,result)
        self.page.goto.assert_not_called();spare.goto.assert_called_once()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_failed_first_candidate_inspection_does_not_hide_other_safe_slot(self):
        spare=self._spare_collection_page()
        self.snap.side_effect=lambda tid,page:copy.deepcopy({**self.snapshot,'url':page.url,
            'inspection_complete':tid!='new','inspection_error':'read timeout' if tid=='new' else ''})
        result=self.run_owner()
        self.assertEqual(len(result['started']),1,result)
        self.page.goto.assert_not_called();spare.goto.assert_called_once()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_leased_first_candidate_does_not_starve_other_safe_fixed_slot(self):
        spare=self._spare_collection_page()
        result=self.run_owner(target_lease=lambda tid:nullcontext(tid!='new'))
        self.assertEqual(len(result['started']),1,result)
        self.page.goto.assert_not_called();spare.goto.assert_called_once()
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)

    def test_same_slot_cas_change_never_navigates(self):
        def changed(*args):
            self.registry['slots'][0]['target_id']='someone-else'
            atomic_json(self.root/'shared-gpt-window.json',self.registry)
        self.guard.side_effect=changed
        result=self.run_owner();self.assertTrue(result['blocked']);self.page.goto.assert_not_called()

    def test_original_target_or_same_conversation_in_another_window_is_never_taken_over(self):
        self.assertFalse(self.run_owner(present_targets={'old','new'})['started'])
        self.assertFalse(self.run_owner(known_urls=['https://chatgpt.com/',self.original['conversation_url']])['started'])
        self.page.goto.assert_not_called();self.snap.assert_not_called()

    def test_completed_saved_page_can_be_reused_without_losing_its_prior_receipt(self):
        from browser.shared_pool_store import load_pool
        raw=self.root/'previous-raw.txt';raw.write_text('Complete saved previous answer')
        previous={'state':'ready','conversation_url':'https://chatgpt.com/c/previous-owned',
            'raw_path':str(raw),'raw_sha256':digest(raw),'kind':'cards','paper_id':'previous'}
        self.pool['windows']['new']=previous
        atomic_json(self.root/'gpt-window-pool.json',dict(self.pool))
        self.pool=load_pool(self.root/'gpt-window-pool.json')
        self.page.url=previous['conversation_url']
        self.snapshot.update(user_texts=['Previous complete request'],answer_texts=[raw.read_text()],answer_element_count=1,draft='\n')
        with patch.object(recovery,'require_reusable',return_value=True) as guard:
            result=self.run_owner()
        self.assertEqual(len(result['started']),1,result);self.assertGreaterEqual(guard.call_count,2)
        self.assertEqual(self.pool['windows']['new']['previous_saved_response']['raw_sha256'],previous['raw_sha256'])
        self.assertEqual(raw.read_text(),'Complete saved previous answer')


    def closed_browser(self, *, reused_start=False):
        rid=self.run_owner()['started'][0]
        path=self.root/'original-receipts'/rid/'proof.json'
        old=copy.deepcopy(self.registry);old['startup_request_id']='window-created' if reused_start else 'old-request';old['endpoint']='http://127.0.0.1:9222'
        self.registry={'window_id':88,'created':200,'startup_request_id':'new-request','endpoint':old['endpoint'],
                       'slots':[{'slot_id':'01','target_id':'next'}]}
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        archive=self.root/'browser-start-archives/new-request'
        atomic_json(archive/'registry.json',old)
        atomic_json(archive/'request.json',{'id':'old-request'})
        identity=hashlib.sha256(json.dumps({'request_id':'old-request','registry':old,'profile':'owned-profile','endpoint':old['endpoint']},sort_keys=True).encode()).hexdigest()
        atomic_json(archive/'closed-browser-evidence.json',{'identity':identity,'profile':'owned-profile','endpoint':old['endpoint'],'checks':[100,135],'checked_at':135,
            'previous_request_id':'old-request','process_absent':True,'endpoint_unavailable':True})
        atomic_json(self.root/'browser-start-request.json',{'id':'new-request','state':'ready',
            'origin':'closed_browser_recovery','previous_request_id':'old-request'})
        self.pool=PoolSnapshot({'windows':{'next':{'state':'ready_blank'}}})
        atomic_json(self.root/'gpt-window-pool.json',dict(self.pool))
        self.page.url='https://chatgpt.com/';self.pages={'next':self.page};self.page.goto.reset_mock()
        return path

    def test_closed_browser_resumes_original_url_without_resending_or_changing_original(self):
        path=self.closed_browser();before=path.read_bytes()
        report=self.run_owner()
        self.assertEqual(len(report['retired_closed_browser']),1)
        self.assertEqual(len(report['started']),1)
        self.page.goto.assert_called_once_with(self.original['conversation_url'],wait_until='domcontentloaded',timeout=10000)
        proof=json.loads(path.read_text())
        self.assertEqual((Path(proof['collection_epoch_archive'])/'proof.json').read_bytes(),before)
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)
        self.page.goto.reset_mock();self.run_owner();self.page.goto.assert_not_called()

    def test_closed_browser_after_reused_start_preserves_evidence_and_resumes_once(self):
        path=self.closed_browser(reused_start=True)
        before=path.read_bytes()
        archive=self.root/'browser-start-archives/new-request'
        evidence={p.name:p.read_bytes() for p in archive.iterdir()}
        result=self.run_owner()
        self.assertEqual(len(result.get('retired_closed_browser',[])),1,result)
        self.assertEqual(len(result['started']),1,result)
        self.page.goto.assert_called_once_with(self.original['conversation_url'],wait_until='domcontentloaded',timeout=10000)
        proof=json.loads(path.read_text())
        self.assertEqual((Path(proof['collection_epoch_archive'])/'proof.json').read_bytes(),before)
        self.assertEqual(evidence,{p.name:p.read_bytes() for p in archive.iterdir()})
        self.assertEqual(self.attempt.read_bytes(),self.original_bytes)
        self.page.goto.reset_mock();self.run_owner();self.page.goto.assert_not_called()

    def test_reused_start_requires_the_actual_archived_request_identity(self):
        path=self.closed_browser(reused_start=True)
        archive=self.root/'browser-start-archives/new-request'
        request=archive/'request.json'
        original=request.read_bytes()
        for replacement in ({'id':'unrelated'}, {'id':'window-created'}, {}):
            atomic_json(request,replacement)
            result=self.run_owner()
            self.assertFalse(result['started'],result)
            self.page.goto.assert_not_called()
            self.assertEqual(json.loads(path.read_text())['state'],'observing')
        request.write_bytes(original)

    def test_absence_or_new_epoch_alone_never_replays_uncertain_navigation(self):
        path=self.closed_browser();d=json.loads(path.read_text());d['state']='navigation_unknown';atomic_json(path,d)
        archive=self.root/'browser-start-archives/new-request/closed-browser-evidence.json'
        for change in ({'process_absent':False},{'endpoint_unavailable':False},{'checks':[100,110]},
                       {'previous_request_id':'unrelated'},{'identity':'changed'},{'endpoint':'http://unrelated'}):
            original=archive.read_bytes();value=json.loads(original);value.update(change);atomic_json(archive,value)
            with self.subTest(change=change):
                self.run_owner();self.page.goto.assert_not_called()
                self.assertEqual(json.loads(path.read_text())['state'],'navigation_unknown')
            archive.write_bytes(original)

    def test_saved_answer_or_changed_side_ledger_remains_protected(self):
        path=self.closed_browser();side=path.with_name('attempt.json');original=side.read_bytes()
        value=json.loads(original);value['settings']['model']='changed';atomic_json(side,value)
        self.run_owner();self.page.goto.assert_not_called()
        side.write_bytes(original);path.with_name('response-raw.txt').write_text('saved answer must not be lost')
        self.run_owner();self.page.goto.assert_not_called()
