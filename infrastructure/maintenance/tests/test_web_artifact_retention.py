import json
import sqlite3
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from maintenance.web_artifact_retention import compact_completed
from reading.reading_contract import file_digest


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root/'web_cards'/'paper'
        self.target = self.root/'deep_read'/'paper'
        for p in (self.folder/'pages', self.folder/'chatgpt', self.target/'pages'):
            p.mkdir(parents=True)
        for p in (self.folder/'source.pdf', self.target/'source.pdf'):
            p.write_bytes(b'source')
        for p in (self.folder/'pages/P001.png', self.target/'pages/P001.png'):
            p.write_bytes(b'image')
        (self.folder/'visual.pdf').write_bytes(b'visual')
        (self.folder/'chatgpt/response-raw.txt').write_text('original answer')
        (self.target/'card.json').write_text('{}')
        self.save(self.folder/'packet.json', {'input_hashes': {n:file_digest(self.folder/n) for n in ('source.pdf','visual.pdf')}})
        self.save(self.folder/'source-context.json', {'page_manifest':[{'image': str(self.folder/'pages/P001.png'), 'sha256':file_digest(self.folder/'pages/P001.png')}]})
        self.save(self.target/'web-provenance.json', {'packet': str(self.folder/'packet.json'),
          'card_sha256': file_digest(self.target/'card.json'), 'attempt': {'state':'response_saved','provider':'chatgpt',
          'raw_sha256': file_digest(self.folder/'chatgpt/response-raw.txt')}})
        self.db = sqlite3.connect(self.root/'catalog.sqlite3')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE web_card_jobs(paper_id TEXT, state TEXT)')
        self.db.execute("INSERT INTO web_card_jobs VALUES ('paper','completed')")
        self.db.commit()
        db = self.db
        class FakeCatalog:
            def __init__(self,*args): pass
            def connect(self): return db
        self.mock = patch('maintenance.web_artifact_retention.Catalog',FakeCatalog)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.config = {'catalog_path':str(self.root/'catalog.sqlite3'), 'studio_library_root':str(self.root/'deep_read')}

    def save(self,path,value): path.write_text(json.dumps(value))

    def test_completed_preserves_paths_hashes_and_receipts(self):
        result = compact_completed(self.config)
        self.assertEqual(result['bytes_reclaimed'],11)
        self.assertEqual((self.folder/'visual.pdf').read_bytes(),b'visual')
        self.assertTrue((self.folder/'source.pdf').is_symlink())
        self.assertEqual((self.folder/'pages/P001.png').read_bytes(),b'image')
        self.assertEqual((self.folder/'chatgpt/response-raw.txt').read_text(),'original answer')
        self.assertTrue((self.folder/'retention.json').exists())
        self.assertEqual(compact_completed(self.config)['bytes_reclaimed'],0)

    def test_inflight_and_uncertain_are_preserved(self):
        for state in ('submitted','needs_inspection','failed','queued','preparing'):
            self.db.execute('UPDATE web_card_jobs SET state=?',(state,));self.db.commit()
            self.assertEqual(compact_completed(self.config)['bytes_reclaimed'],0)
            self.assertTrue((self.folder/'visual.pdf').exists())

    def test_mismatched_evidence_or_reply_blocks_cleanup(self):
        for name in ('source.pdf','pages/P001.png','chatgpt/response-raw.txt'):
            p=self.folder/name; old=p.read_bytes();p.write_bytes(b'changed')
            self.assertEqual(compact_completed(self.config)['bytes_reclaimed'],0)
            self.assertTrue((self.folder/'visual.pdf').exists());p.write_bytes(old)

    def test_dry_run_leaves_originals(self):
        self.assertEqual(compact_completed(self.config,True)['bytes_reclaimed'],11)
        self.assertFalse((self.folder/'source.pdf').is_symlink())
        self.assertTrue((self.folder/'visual.pdf').exists())

    def test_ssd_symlink_payload_deleted_after_completed(self):
        import os
        media=self.root/'ssd-media'; payload=media/'paper';payload.mkdir(parents=True)
        self.config['web_cards']={'media_root':str(media)}
        for name in ('source.pdf','visual.pdf'):
            old=self.folder/name; dest=payload/name
            old.rename(dest);old.symlink_to(os.path.relpath(dest,old.parent))
        compact_completed(self.config)
        self.assertFalse((payload/'source.pdf').exists())
        self.assertEqual((payload/'visual.pdf').read_bytes(),b'visual')
        self.assertEqual((self.folder/'source.pdf').read_bytes(),b'source')

    def test_ssd_pages_directory_alias_keeps_valid_page_link(self):
        import os
        media=self.root/'ssd-media';payload=media/'paper';payload.mkdir(parents=True)
        pages=self.folder/'pages';pages.rename(payload/'pages')
        pages.symlink_to(os.path.relpath(payload/'pages',pages.parent))
        self.config['web_cards']={'media_root':str(media)}
        compact_completed(self.config)
        self.assertEqual((pages/'P001.png').read_bytes(),b'image')
        self.assertTrue((payload/'pages/P001.png').is_symlink())

    def test_open_empty_log_preserved(self):
        import os
        import subprocess
        logs=self.root/'logs';logs.mkdir()
        a=logs/'discover-old.log';a.touch();os.utime(a,(0,0))
        b=logs/'discover-closed.log';b.touch();os.utime(b,(0,0))
        with patch('maintenance.web_artifact_retention.subprocess.run',return_value=subprocess.CompletedProcess([],0,'n'+str(a)+'\n','')):
            compact_completed(self.config)
        self.assertTrue(a.exists());self.assertFalse(b.exists())


if __name__=='__main__': unittest.main()
