import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,MagicMock
from fetch import osti_retrieval as osti
from core.catalog import Catalog

class OSTIRetrieval(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'db.sqlite3');self.pid=self.catalog.upsert({'title':'A verified source title for testing','doi':'10.1234/test'})
        self.paper=self.catalog.get(self.pid);self.target=self.root/'candidate.pdf'
        self.record={'doi':'10.1234/test','product_type':'Journal Article','osti_id':'123','article_type':'Accepted Manuscript',
            'links':[{'rel':'fulltext','href':'https://www.osti.gov/servlets/purl/123'}]}
        self.config={'catalog_path':str(self.catalog.path)}

    def fetch(self,rows=None):
        with patch.object(osti,'lookup',return_value=rows if rows is not None else [self.record]), \
             patch('core.services.download',side_effect=lambda u,p:(p.write_bytes(b'verified bytes'),'https://www.osti.gov/servlets/purl/123')[1]), \
             patch('core.services.verify_identity',return_value='A verified source title for testing 10.1234/test'):
            return osti.fetch(self.paper,self.root,self.target)

    def test_only_exact_doi_journal_and_public_osti_fulltext_is_used(self):
        for changed in ({'doi':'10.1234/other'},{'product_type':'Dataset'},
                        {'links':[{'rel':'citation','href':'https://www.osti.gov/servlets/purl/123'}]},
                        {'links':[{'rel':'fulltext','href':'http://localhost/file.pdf'}]}):
            with patch('core.services.download') as download:
                with patch.object(osti,'lookup',return_value=[{**self.record,**changed}]):
                    self.assertIsNone(osti.fetch(self.paper,self.root,self.target))
                download.assert_not_called()
        self.assertTrue(self.fetch()['version_review_required'])

    def test_accepted_source_is_archived_with_version_gate_not_silently_formal(self):
        result=self.fetch()
        with patch('core.services.store_asset',return_value=(str(self.target),result['verified_sha256'])):
            osti.bind(self.catalog,self.config,self.paper,result)
        paper=self.catalog.get(self.pid)
        self.assertEqual(paper['asset_hash'],result['verified_sha256']);self.assertTrue(paper['metadata']['version_review_required'])
        self.assertEqual(paper['metadata']['asset_version'],'Accepted Manuscript')
        with self.catalog.connect() as db:
            event=json.loads(db.execute("SELECT payload FROM events WHERE kind='download'").fetchone()[0])
            self.assertEqual(event['provider'],'osti')

    def test_concurrent_existing_original_card_and_human_decision_are_preserved(self):
        for fields in ({'asset_path':'original'},{'card_path':'card'},{'acquisition':'available'}):
            if fields=={'acquisition':'available'}:continue
            result=self.fetch();self.catalog.update(self.pid,**fields)
            with patch('core.services.store_asset',return_value=(str(self.target),result['verified_sha256'])):
                with self.assertRaises(ValueError):osti.bind(self.catalog,self.config,self.paper,result)
            self.catalog.update(self.pid,asset_path=None,card_path=None)
        self.catalog.event(self.pid,'human_decision',{})
        result=self.fetch()
        with patch('core.services.store_asset',return_value=(str(self.target),result['verified_sha256'])):
            with self.assertRaises(ValueError):osti.bind(self.catalog,self.config,self.paper,result)

    def test_wrong_frontmatter_and_changed_bytes_never_publish(self):
        with patch.object(osti,'lookup',return_value=[self.record]),patch('core.services.download'),patch('core.services.verify_identity',return_value='another doi'):
            with self.assertRaises(ValueError):osti.fetch(self.paper,self.root,self.target)
        result=self.fetch()
        with patch('core.services.store_asset',return_value=('changed','changed-hash')):
            with self.assertRaises(ValueError):osti.bind(self.catalog,self.config,self.paper,result)
        self.assertIsNone(self.catalog.get(self.pid)['asset_path'])

    def test_cache_and_json_accept_header_and_response_bound(self):
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=json.dumps([self.record]).encode()
        client=MagicMock();client.open.return_value=response
        with patch('fetch.public_http.opener',return_value=client),patch('core.services.public_url'), \
             patch('fetch.network.ready'),patch('fetch.network.pace'),patch('fetch.network.succeeded'):
            self.assertEqual(osti.lookup('10.1234/test',self.root),[self.record])
            self.assertEqual(osti.lookup('10.1234/test',self.root),[self.record])
            client.open.assert_called_once()
            request=client.open.call_args.args[0];self.assertEqual(request.get_header('Accept'),'application/json')
            self.assertEqual(response.read.call_args.args[0],2*1024*1024+1)

    def test_protected_preprint_and_existing_card_never_lookup(self):
        for patch_meta in ({'publication_kind':'preprint'},{'version_review_required':True},{'identity_review_required':True},{'out_of_scope':True}):
            self.paper['metadata']={**self.paper['metadata'],**patch_meta}
            with patch.object(osti,'lookup') as lookup:
                self.assertIsNone(osti.fetch(self.paper,self.root,self.target));lookup.assert_not_called()

    def test_acquisition_uses_verified_route_and_keeps_manuscript_out_of_card_queue(self):
        from core.catalog import ROOT
        from core.services import acquisition
        from cards.web_card_queue import select
        import pymupdf
        self.config=json.loads((ROOT/'config/first_round.json').read_text())
        self.config.update(catalog_path=str(self.catalog.path),archive_volume=str(self.root),archive_root=str(self.root/'archive'),
                           studio_library_root=str(self.root/'cards'),require_mounted_volume=False)
        self.config['pdf_retrieval']['osti_enabled']=True
        self.config['manual_literature']['enabled']=False
        def download(url,path):
            with pymupdf.open() as doc:
                page=doc.new_page();page.insert_text((40,70),self.paper['title'],fontsize=12)
                page.insert_text((40,100),'10.1234/test',fontsize=12);doc.save(path)
            return url
        with patch.object(osti,'lookup',return_value=[self.record]),patch('core.services.download',side_effect=download), \
             patch('core.process_runner.run') as other_route:
            acquisition(self.catalog,self.config,self.pid,stage='fallback')
            other_route.assert_not_called()
        stored=self.catalog.get(self.pid)
        self.assertTrue(Path(stored['asset_path']).is_file());self.assertTrue(stored['metadata']['version_review_required'])
        self.assertEqual(select(self.catalog,self.config)['added'],[])

    def test_fast_stage_does_not_spend_time_on_repository_lookup(self):
        from core.services import acquisition
        self.config.update(archive_volume=str(self.root),archive_root=str(self.root/'archive'),require_mounted_volume=False,
                           pdf_retrieval={'enabled':True,'osti_enabled':True})
        with patch.object(osti,'lookup') as lookup:
            acquisition(self.catalog,self.config,self.pid,stage='fast')
            lookup.assert_not_called()

    def test_binding_conflict_does_not_fall_through_to_stale_alternative_download(self):
        from core.services import acquisition
        self.config.update(archive_volume=str(self.root),archive_root=str(self.root/'archive'),require_mounted_volume=False,
                           pdf_retrieval={'enabled':True,'osti_enabled':True})
        with patch.object(osti,'fetch',return_value={'path':'candidate'}), \
             patch.object(osti,'bind',side_effect=osti.BindingConflict('changed')),patch('core.process_runner.run') as other:
            with self.assertRaises(osti.BindingConflict):acquisition(self.catalog,self.config,self.pid,stage='fallback')
            other.assert_not_called()
