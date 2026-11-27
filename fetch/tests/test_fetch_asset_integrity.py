from core.api import paths__WorkspacePath as Path
import tempfile
import unittest
from core.catalog import Catalog


class AssetIntegrity(unittest.TestCase):
    def test_fresh_catalog_never_reports_acquisition_without_asset_as_done(self):
        with tempfile.TemporaryDirectory() as td:
            catalog=Catalog(Path(td)/'catalog.sqlite3');pid=catalog.upsert({'title':'Synthetic source'})
            for kind in ('acquire','acquire_fallback'):
                jid=catalog.enqueue(kind,pid);catalog.claim((kind,));catalog.finish(jid,'done')
                with catalog.connect() as db:
                    self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'deferred')
            catalog.update(pid,acquisition='available',asset_path=str(Path(td)/'source.pdf'))
            jid=catalog.enqueue('acquire',pid);catalog.claim(('acquire',));catalog.finish(jid,'done')
            with catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'done')

    def test_terminal_fetch_policy_survives_base_guard(self):
        from fetch.fetch_policy import install
        with tempfile.TemporaryDirectory() as td:
            catalog=Catalog(Path(td)/'catalog.sqlite3');pid=catalog.upsert({'title':'Synthetic terminal source'});install(catalog)
            with catalog.connect() as db:db.execute("INSERT INTO fetch_targets(paper_id,input_hash,state) VALUES(?,?,'terminal')",(pid,'hash'))
            jid=catalog.enqueue('acquire',pid,{'manual_retry':True});catalog.claim(('acquire',));catalog.finish(jid,'done')
            with catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'needs_manual')
