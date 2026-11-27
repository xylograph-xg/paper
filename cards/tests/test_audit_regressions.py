"""Real Catalog/PDF regressions for the October 14 cards audit."""
import copy
import json
import threading
import unittest
from unittest.mock import patch
from cards import web_card_inputs as inputs, web_card_service as service, web_card_queue as queue
from cards.tests import test_web_card_publication_protection as protection


class AuditRegressions(unittest.TestCase):
    setUp=protection.PublicationProtection.setUp

    def ordinary(self):
        self.old.unlink()
        self.catalog.update(self.pid,card_path=None)
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET selection='{}' WHERE paper_id=?",(self.pid,))
        self.job=queue.jobs(self.catalog)[0]

    def test_missing_or_invalid_hash_cannot_enter_queue(self):
        self.ordinary()
        with self.catalog.connect() as db:db.execute('DELETE FROM web_card_jobs')
        for value in (None,'','abc','g'*64):
            self.catalog.update(self.pid,asset_hash=value)
            result=queue.select(self.catalog,{**self.config,'web_cards':{'selection_fraction':1}})
            self.assertEqual(result['added'],[])
        (self.provider/'attempt.json').unlink()
        self.catalog.update(self.pid,asset_hash=inputs.digest(self.source))
        self.assertEqual(queue.select(self.catalog,{**self.config,'web_cards':{'selection_fraction':1}})['added'],[self.pid])

    def test_preparation_requires_hash(self):
        with self.assertRaisesRegex(ValueError,'身份待修复'):
            inputs.prepare(self.source,self.root/'no-hash',self.pid,'test','')
        self.assertFalse((self.root/'no-hash/packet.json').exists())

    def test_ordinary_publication_blocks_changed_source_and_identity(self):
        self.ordinary()
        self.catalog.update(self.pid,asset_hash='a'*64)
        service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertIsNone(self.catalog.get(self.pid)['card_path'])
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'needs_inspection')
        self.assertTrue((self.folder/'card-candidate.json').exists())
        self.assertFalse(self.old.exists())

    def test_current_contract_rejects_missing_fields_and_wrong_types(self):
        card=json.loads(self.raw)
        for field in ('number','caption','figure_info'):
            invalid=copy.deepcopy(card);invalid['figures'][0].pop(field)
            with self.assertRaisesRegex(ValueError,field):inputs.parse_card(json.dumps(invalid),self.packet)
        invalid=copy.deepcopy(card);invalid['info'].pop('DOI')
        with self.assertRaisesRegex(ValueError,'DOI'):inputs.parse_card(json.dumps(invalid),self.packet)
        equation={**card['figures'][0],'latex':r'x=\nu','quantities':[],'related_labels':'Fig. 1'}
        card['equations']=[equation]
        with self.assertRaisesRegex(ValueError,'quantities|related_labels'):inputs.parse_card(json.dumps(card),self.packet)

    def test_damaged_nrightarrow_rejected_but_multiline_preserved(self):
        self.assertTrue(inputs.damaged_latex('\nrightarrow'))
        self.assertFalse(inputs.damaged_latex('x=y\nz=w'))
        card=json.loads(self.raw)
        card['equations']=[{**card['figures'][0],'latex':'\nrightarrow','quantities':'x defined in source','related_labels':[]}]
        with self.assertRaisesRegex(ValueError,'损坏JSON'):inputs.parse_card(json.dumps(card),self.packet)
        card['equations'][0]['latex']=r'\nrightarrow'
        inputs.parse_card(json.dumps(card),self.packet)

    def test_nonconversation_url_rejected(self):
        from cards.web_card_retry import finished_response
        from core.api import services__atomic_json as atomic_json
        (self.provider/'prompt-actual.txt').write_text((self.folder/'prompt.txt').read_text())
        attempt={**self.attempt,'actual_prompt_sha256':inputs.digest(self.provider/'prompt-actual.txt'),
                 'conversation_url':'https://chatgpt.com/settings'}
        atomic_json(self.provider/'attempt.json',attempt)
        with self.assertRaisesRegex(ValueError,'会话归属'):
            finished_response(self.provider/'attempt.json',attempt,self.packet)

    def test_failure_before_metadata_switch_does_not_register_card(self):
        self.ordinary()
        real=service.atomic_json
        def fail(path,value,**kw):
            if path.name=='web-evidence-verification.json':raise OSError('simulated disk failure')
            return real(path,value,**kw)
        with patch.object(service,'atomic_json',side_effect=fail),self.assertRaises(OSError):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertIsNone(self.catalog.get(self.pid)['card_path'])
        self.assertFalse(self.old.exists())
        self.assertEqual(json.loads((self.folder/'publication-intent.json').read_text())['state'],'writing')
        service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'needs_inspection')
        self.assertIsNone(self.catalog.get(self.pid)['card_path'])

    def test_changed_staged_image_cannot_become_an_official_card(self):
        self.ordinary()
        from cards import publication_materials
        original=publication_materials.copy
        def corrupt(folder,output):
            original(folder,output)
            if output.name.startswith('.publication-stage-'):
                (output/'pages/P001.png').write_bytes(b'changed staged evidence')
        with patch.object(publication_materials,'copy',side_effect=corrupt),self.assertRaisesRegex(ValueError,'暂存页图'):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertFalse(self.old.exists())
        self.assertIsNone(self.catalog.get(self.pid)['card_path'])
        self.assertEqual(inputs.digest(self.provider/'response-raw.txt'),self.before['raw'])

    def test_database_serializes_human_decision_with_publication(self):
        self.ordinary();started=threading.Event();finished=threading.Event();errors=[]
        def decide():
            started.set()
            try:self.catalog.decide(self.pid,'keep')
            except Exception as exc:errors.append(exc)
            finally:finished.set()
        from cards import publication_materials
        original=publication_materials.copy;threads=[]
        def concurrent_copy(folder,output):
            if not threads:
                thread=threading.Thread(target=decide);threads.append(thread);thread.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.wait(.1))
            return original(folder,output)
        with patch.object(publication_materials,'copy',side_effect=concurrent_copy):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        threads[0].join(3)
        self.assertTrue(finished.is_set());self.assertEqual(errors,[])
        self.assertEqual(self.catalog.get(self.pid)['decision'],'keep')
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')

    def test_code_fingerprint_includes_physical_cards_sources(self):
        hashes=service.code_version()['module_sha256']
        for name in ('web_card_inputs.py','web_card_retry.py','web_card_service.py'):
            self.assertEqual(hashes['cards/'+name],inputs.digest(inputs.Path(inputs.__file__).parent/name))

    def test_local_pixel_budget_fails_and_cleans_pages(self):
        import pymupdf
        pages=self.root/'render-pages';pages.mkdir()
        with pymupdf.open(self.source) as doc,patch.object(inputs,'MAX_PAGE_PIXELS',1):
            with self.assertRaisesRegex(ValueError,'像素'):
                inputs.render_visual(doc,self.root/'over.pdf',pages,220)
        self.assertEqual(list(pages.glob('P*.png')),[])
        self.assertFalse((self.root/'over.pdf').exists())

    def test_sqlite_abort_after_file_switch_preserves_intent_and_blocks_resend(self):
        self.ordinary()
        with self.catalog.connect() as db:
            db.execute("CREATE TRIGGER reject_publication BEFORE UPDATE OF card_path ON papers BEGIN SELECT RAISE(ABORT,'simulated commit failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertIsNone(self.catalog.get(self.pid)['card_path'])
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'collecting')
        self.assertTrue(self.old.exists())
        with self.catalog.connect() as db:db.execute('DROP TRIGGER reject_publication')
        service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')
        self.assertEqual(self.catalog.get(self.pid)['card_path'],str(self.old))

    def test_owner_retry_scan_finishes_local_publication_without_external_retry(self):
        import sqlite3
        from cards.web_card_retry import run_once
        self.ordinary()
        (self.provider/'prompt-actual.txt').write_text((self.folder/'prompt.txt').read_text())
        attempt={**self.attempt,'provider':'chatgpt','actual_prompt_sha256':inputs.digest(self.provider/'prompt-actual.txt')}
        (self.provider/'attempt.json').write_text(json.dumps(attempt))
        with self.catalog.connect() as db:
            db.execute("CREATE TRIGGER reject_publication BEFORE UPDATE OF card_path ON papers BEGIN SELECT RAISE(ABORT,'simulated commit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            service.publish_saved(self.config,self.job,self.raw,attempt,'chatgpt')
        with self.catalog.connect() as db:
            db.execute('DROP TRIGGER reject_publication')
        queue.update(self.catalog,self.pid,state='needs_inspection',error='Interrupted publication')
        config={**self.config,'web_cards':{'enabled':True,'retry':{'enabled':True}}}
        result=run_once(config)
        self.assertEqual(result['published'],[self.pid])
        self.assertEqual(result['requeued'],[])
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')
        self.assertFalse((self.folder/'retry.json').exists())
        self.assertEqual(inputs.digest(self.provider/'response-raw.txt'),self.before['raw'])

    def test_rework_sqlite_failure_never_changes_the_previous_card(self):
        import sqlite3
        with self.catalog.connect() as db:
            db.execute("CREATE TRIGGER reject_rework BEFORE UPDATE OF card_path ON papers BEGIN SELECT RAISE(ABORT,'simulated rework commit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertEqual(self.old.read_bytes(),self.before['card'])
        self.assertEqual(self.catalog.get(self.pid)['card_path'],str(self.old))
        intent=json.loads((self.folder/'publication-intent.json').read_text())
        self.assertEqual(intent['state'],'files_written')
        self.assertTrue((inputs.Path(intent['output'])/'card.json').exists())

    def test_committed_event_recovers_a_failed_final_intent_write(self):
        self.ordinary();real=service.atomic_json
        def fail_marker(path,value,**kw):
            if path.name=='publication-intent.json' and value.get('state')=='committed':raise OSError('simulated final marker failure')
            return real(path,value,**kw)
        with patch.object(service,'atomic_json',side_effect=fail_marker),self.assertRaises(OSError):
            service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        before=self.old.read_bytes()
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')
        service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        self.assertEqual(self.old.read_bytes(),before)
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')
        self.assertEqual(json.loads((self.folder/'publication-intent.json').read_text())['state'],'committed')

    def test_followup_authorized_rework_uses_current_version_and_retains_both(self):
        import shutil
        service.publish_saved(self.config,self.job,self.raw,self.attempt,'chatgpt')
        first=inputs.Path(self.catalog.get(self.pid)['card_path']);before=first.read_bytes()
        backup=self.root/'next-authorized-history';backup.mkdir();shutil.copy2(first,backup/'card.json')
        record={**self.record,'old_card_path':str(first),'old_sha256':inputs.digest(first),
                'backup':str(backup),'correction_id':'next-correction'}
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET selection=?,state='collecting' WHERE paper_id=?",(json.dumps({'rework':record}),self.pid))
        job=queue.jobs(self.catalog)[0]
        service.publish_saved(self.config,job,self.raw,self.attempt,'chatgpt')
        second=inputs.Path(self.catalog.get(self.pid)['card_path'])
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),before)
        self.assertEqual(self.old.read_bytes(),self.before['card'])
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'completed')

    def test_retry_archive_rollback_restores_receipt_and_keeps_budget(self):
        from cards.web_card_retry import _recover_archive
        archive=self.folder/'history'/'interrupted';archive.mkdir(parents=True)
        archived=archive/'chatgpt';fingerprint=inputs.digest(self.provider/'attempt.json')
        self.provider.rename(archived)
        ledger={'state':'archive_in_progress','external_retries':1,'retry_at':1000,
            'archive_moves':[{'original':str(self.provider),'archived':str(archived),'attempt_sha256':fingerprint}]}
        ledger_path=self.folder/'retry.json'
        _recover_archive(self.catalog,self.job,self.folder,ledger_path,ledger)
        self.assertEqual(inputs.digest(self.provider/'attempt.json'),fingerprint)
        self.assertFalse(archived.exists())
        self.assertEqual(json.loads(ledger_path.read_text())['external_retries'],1)
        self.assertEqual(json.loads(ledger_path.read_text())['state'],'archive_rolled_back')

    def test_recycled_pid_is_not_reused(self):
        with patch.object(service,'alive',return_value=True),patch.object(service.subprocess,'check_output',return_value='sleep 1000'):
            self.assertFalse(service._owner_process_confirmed({'pid':123,'token':'old'},self.root,self.config))


if __name__=='__main__':unittest.main()
