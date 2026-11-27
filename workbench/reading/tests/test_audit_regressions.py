import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from reading.completed_literature_archive import move_verified,digest
from reading.manual_literature import inspect_file

class ArchiveAudit(unittest.TestCase):
    def test_final_guard_atomic_replacement_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'old');calls=[]
            def guard():
                calls.append(1)
                if len(calls)==2:
                    replacement=root/'new';replacement.write_bytes(b'new');replacement.replace(source)
            with self.assertRaises(ValueError):move_verified(source,root/'library',digest(source),guard)
            self.assertEqual(source.read_bytes(),b'new')
            self.assertEqual(list((root/'library').iterdir()),[])
    def test_final_guard_exception_leaves_no_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'old');calls=[]
            def guard():
                calls.append(1)
                if len(calls)==2:raise ValueError('changed')
            with self.assertRaises(ValueError):move_verified(source,root/'library',digest(source),guard)
            self.assertEqual(source.read_bytes(),b'old');self.assertEqual(list((root/'library').iterdir()),[])
    def test_archive_does_not_share_source_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'old')
            with source.open('r+b') as original:
                target=Path(move_verified(source,root/'library',digest(source),lambda:None))
                original.write(b'new');original.flush()
            self.assertEqual(target.read_bytes(),b'old')

class DocxAudit(unittest.TestCase):
    def test_decompression_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bomb.docx'
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('word/document.xml',b'x'*(9*1024*1024))
            with self.assertRaisesRegex(ValueError,'展开额度'):inspect_file(path)
    def test_xml_entities_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'entities.docx'
            with zipfile.ZipFile(path,'w') as z:z.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY x "text">]><x>&x;</x>')
            with self.assertRaisesRegex(ValueError,'实体'):inspect_file(path)

class RecoveryAudit(unittest.TestCase):
    from reading.tests.test_reading_safety import DurableRecovery
    setUp=DurableRecovery.setUp
    tearDown=DurableRecovery.tearDown
    def test_enqueue_failure_leaves_ledger_retryable(self):
        from reading.reading_recovery import activate
        source=self.root/'source.pdf';source.write_bytes(b'fixture')
        pid=self.catalog.upsert({'title':'retryable'});self.catalog.update(pid,asset_path=str(source),acquisition='available')
        failed=self.catalog.enqueue('screen',pid);self.catalog.finish(failed,'failed','old')
        with patch.object(self.catalog,'enqueue',side_effect=OSError('disk')):
            with self.assertRaises(OSError):activate(self.catalog,self.config)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM reading_recovery_processed').fetchone()[0],0)
        self.assertEqual(len(activate(self.catalog,self.config)['jobs']),1)

class FingerprintAudit(unittest.TestCase):
    def test_real_source_changes_fingerprint(self):
        from reading import reading_contract as rc
        with patch.object(rc,'file_digest',return_value='a'):first=rc.producer_fingerprint()
        with patch.object(rc,'file_digest',side_effect=lambda p:'b' if str(p).endswith('reading_bridge.py') else 'a'):second=rc.producer_fingerprint()
        self.assertNotEqual(first,second)

class SourceCacheAudit(unittest.TestCase):
    def test_missing_archive_cannot_reuse_available(self):
        from reading.source_media import prepare_source
        from reading.tests.test_source_media import SourceMedia
        with tempfile.TemporaryDirectory() as folder,patch('reading.source_media.pdf_version',return_value='2406.02703v2'):
            root=Path(folder)
            def fetch(url,path,**kwargs):Path(path).write_bytes(SourceMedia().archive('main.tex',b'\\documentclass{article}\\begin{document}ok\\end{document}'))
            status=prepare_source(root,fetch);self.assertEqual(status['state'],'available')
            (root/status['archive']).unlink()
            status=prepare_source(root,lambda *a,**kw:self.fail('must retain damaged evidence'))
            self.assertEqual(status['state'],'needs_rebuild')
            self.assertEqual(prepare_source(root,lambda *a,**kw:self.fail('must not overwrite'))['state'],'needs_rebuild')

class ArchiveFailureAudit(unittest.TestCase):
    def test_publish_failure_restores_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'old');real_link=os.link
            def link(a,b,**kw):
                if Path(a).parent==root/'library':raise OSError('publish failure')
                return real_link(a,b,**kw)
            with patch('reading.completed_literature_archive.os.link',side_effect=link):
                with self.assertRaises(OSError):move_verified(source,root/'library',digest(source),lambda:None)
            self.assertEqual(source.read_bytes(),b'old');self.assertEqual(list((root/'library').iterdir()),[])
    def test_final_directory_sync_failure_preserves_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'old');real_sync=os.fsync;calls=[]
            def sync(fd):
                calls.append(fd)
                if len(calls)==4:raise OSError('directory sync')
                return real_sync(fd)
            with patch('reading.completed_literature_archive.os.fsync',side_effect=sync):
                with self.assertRaises(OSError):move_verified(source,root/'library',digest(source),lambda:None)
            self.assertEqual((root/'library/source.pdf').read_bytes(),b'old')

class RecoveryReceiptAudit(unittest.TestCase):
    from reading.tests.test_reading_safety import DurableRecovery
    setUp=DurableRecovery.setUp
    tearDown=DurableRecovery.tearDown
    def test_finished_recovery_job_before_ledger_is_not_reenqueued(self):
        from reading.reading_recovery import activate
        source=self.root/'source.pdf';source.write_bytes(b'fixture')
        pid=self.catalog.upsert({'title':'receipt'});self.catalog.update(pid,asset_path=str(source),acquisition='available')
        failed=self.catalog.enqueue('screen',pid);self.catalog.finish(failed,'failed','old')
        with patch.object(self.catalog,'event',side_effect=OSError('event failure')):
            with self.assertRaises(OSError):activate(self.catalog,self.config)
        with self.catalog.connect() as db:
            recovery=db.execute("SELECT id FROM jobs WHERE json_extract(payload,'$.trigger')='reading_policy_recovery'").fetchone()[0]
        self.catalog.finish(recovery,'done')
        result=activate(self.catalog,self.config)
        self.assertEqual(result['jobs'],[]);self.assertEqual(result['skipped']['recovery_receipt_exists'],1)

class DocxEncodingAudit(unittest.TestCase):
    def test_utf16_cannot_bypass_entity_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'utf16.docx'
            with zipfile.ZipFile(path,'w') as z:z.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY x "text">]><x>&x;</x>'.encode('utf-16'))
            with self.assertRaisesRegex(ValueError,'UTF-16'):inspect_file(path)
