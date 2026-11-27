import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, ROOT
from reading import manual_literature as manual
from cards import web_card_queue as cards
from core.workflow_priority import sort


class ManualLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.folder = self.root/'manual'; self.seed_folder = self.root/'seeds'
        self.seed_storage = self.root/'seed_storage'; self.storage = self.root/'storage'
        for folder in (self.folder, self.seed_folder, self.seed_storage, self.storage): folder.mkdir()
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path),'studio_library_root':str(self.root/'cards'),
            'manual_literature':{'enabled':True,'directory':str(self.folder),
                                 'seed_directory':str(self.seed_folder),'seed_storage_directory':str(self.seed_storage),'storage_directory':str(self.storage)},
            'web_cards':{'pdf_python':'fixture-python','selection_fraction':.01,
                         'shared_window':{'backlog':{'queue_order':'paper_score'}}}}
        cards.install(self.catalog)

    def paper(self, name, source=b'original'):
        pid = self.catalog.upsert({'title':'Verified paper title '+name,'doi':'10.1234/'+name})
        asset = self.root/(name+'.pdf'); asset.write_bytes(source)
        digest = hashlib.sha256(source).hexdigest()
        self.catalog.update(pid,asset_path=str(asset),asset_hash=digest,acquisition='available')
        return pid, asset, digest

    def inspect_mock(self, value):
        return patch.object(manual.subprocess,'run',return_value=subprocess.CompletedProcess(
            [],0,stdout=json.dumps(value),stderr=''))

    def test_seed_folder_registers_seed_and_moves_to_seed_storage(self):
        pid, asset, digest = self.paper('seed')
        incoming = self.seed_folder/'original.pdf'; incoming.write_bytes(asset.read_bytes())
        with self.inspect_mock({'kind':'original_pdf','source_hash':digest}):
            first = manual.run_once(self.catalog,self.config)
            second = manual.run_once(self.catalog,self.config)
        self.assertEqual(first['items'][0]['state'],'seed_stored')
        self.assertEqual(first['selection']['added'],[pid])
        self.assertEqual(second['selection']['added'],[])
        self.assertFalse(incoming.exists())
        stored=Path(first['items'][0]['path'])
        self.assertEqual(stored.read_bytes(),b'original')
        self.assertEqual(stored.parent.resolve(),self.seed_storage.resolve())
        self.assertTrue(self.catalog.get(pid)['seed'])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM manual_card_priority').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM manual_seed_roots').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT state FROM manual_literature_items').fetchone()[0],'seed_stored')
        job = cards.jobs(self.catalog)[0]
        self.assertEqual(json.loads(job['selection'])['selection_kind'],'manual_library')

    def test_manual_folder_is_normal_candidate_and_moves_to_storage(self):
        pid, asset, digest = self.paper('manual')
        incoming = self.folder/'original.pdf'; incoming.write_bytes(asset.read_bytes())
        with self.inspect_mock({'kind':'original_pdf','source_hash':digest}):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual(report['items'][0]['state'],'stored')
        self.assertFalse(incoming.exists())
        stored = Path(report['items'][0]['path'])
        self.assertEqual(stored.read_bytes(),b'original')
        self.assertFalse(self.catalog.get(pid)['seed'])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM manual_card_priority').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT state,stored_path FROM manual_literature_items').fetchone()['state'],'stored')

    def test_seed_index_keeps_original_and_requires_exact_accepted_card(self):
        pid, asset, digest = self.paper('kept')
        incoming = self.seed_folder/'文献 & original.pdf'
        incoming.write_bytes(asset.read_bytes())
        self.config['manual_literature']['keep_seed_originals'] = True
        card = self.root/'card.json'
        card.write_text(json.dumps({'meta':{'scientific_verified':True, 'production_contract_complete':True,
                                           'source_original_sha256':digest}}))
        self.catalog.update(pid,card_path=str(card))
        index = self.seed_folder/'文献库索引.html'
        with self.inspect_mock({'kind':'original_pdf','source_hash':digest}):
            manual.run_once(self.catalog,self.config)
            self.assertIn('暂无可展示卡片 · 1',index.read_text())
            self.assertNotIn('打开成品卡',index.read_text())
            from review.card_review_queue import install
            install(self.catalog)
            with self.catalog.connect() as db:
                db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,folder,state,updated) "
                           "VALUES(?,?,?,?,?,?,'passed','t')",
                           ('pass',pid,hashlib.sha256(card.read_bytes()).hexdigest(),digest,'paper',str(self.root)))
            manual.run_once(self.catalog,self.config)
            self.assertIn('已有成品卡 · 1',index.read_text())
            self.assertIn(incoming.resolve().as_uri(),index.read_text())
            self.assertIn(card.as_uri(),index.read_text())
            card.write_text(card.read_text()+' ')
            manual.run_once(self.catalog,self.config)
            self.assertIn('暂无可展示卡片 · 1',index.read_text())
        self.assertEqual(incoming.read_bytes(),asset.read_bytes())
        self.assertEqual(list(self.seed_storage.iterdir()),[])

    def test_seed_index_previews_same_source_structural_card_separately(self):
        from review.card_review_queue import install
        install(self.catalog)
        pid, asset, digest = self.paper('preview')
        incoming = self.seed_folder/'preview.pdf'
        incoming.write_bytes(asset.read_bytes())
        card = self.root/'card.json'
        document = {'meta':{'producer':'web_card_service', 'structural_complete':True,
                            'source_original_sha256':digest, 'scientific_verified':False,
                            'production_contract_complete':False},
                    'one_line_summary':'<script>候选摘要</script>'}
        raw = json.dumps(document).encode()
        card.write_bytes(raw)
        self.catalog.update(pid,card_path=str(card))
        self.config['manual_literature']['keep_seed_originals'] = True
        index = self.seed_folder/'文献库索引.html'
        with self.catalog.connect() as db:
            db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,folder,state,updated) "
                       "VALUES(?,?,?,?,?,?,'submitted','t')",
                       ('review',pid,hashlib.sha256(raw).hexdigest(),digest,'paper',str(self.root)))
        with self.inspect_mock({'kind':'original_pdf','source_hash':digest}):
            report = manual.run_once(self.catalog,self.config)
        html = index.read_text()
        self.assertIn('可预览候选卡 · 1',html)
        self.assertIn('已有成品卡 · 0',html)
        self.assertIn('核验请求已提交，等待收取完整回答',html)
        self.assertIn('&lt;script&gt;候选摘要&lt;/script&gt;',html)
        self.assertIn(card.as_uri(),html)
        self.assertEqual(card.read_bytes(),raw)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM card_review_jobs").fetchone()[0],'submitted')
        incoming.write_bytes(b'changed source')
        manual._write_seed_index(self.catalog,self.seed_folder.resolve(),report['items'])
        self.assertNotIn(card.as_uri(),index.read_text())
        self.assertIn('卡片与当前原文的指纹不一致',index.read_text())
        incoming.write_bytes(asset.read_bytes())
        self.catalog.decide(pid,'reject')
        manual._write_seed_index(self.catalog,self.seed_folder.resolve(),report['items'])
        self.assertNotIn(card.as_uri(),index.read_text())

    def test_wrapped_doi_requires_matching_first_page_link(self):
        import pymupdf
        from core.api import services__pdf_dois as pdf_dois
        path = self.root/'wrapped.pdf'
        printed = '10.1234/a-\n9876'
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_link({'kind':pymupdf.LINK_URI, 'from':pymupdf.Rect(20, 20, 100, 40),
                              'uri':'https://doi.org/10.1234/a-9876'})
            doc.save(path)
        self.assertEqual(pdf_dois(path,printed),{'10.1234/a-9876'})
        self.assertEqual(pdf_dois(path,printed.replace('9876','4321')),set())

    def test_inline_title_markup_matches_printed_formula_tokens(self):
        from core.api import services__verify_identity as verify_identity
        title = 'A kinetic study of <i>S</i>\n <sub>1</sub> and <i>T</i> <sub>1</sub> states'
        printed = 'A kinetic study of S1 and T1 states'
        with patch('core.services.validate_pdf',return_value=printed):
            self.assertEqual(verify_identity(self.root/'source.pdf',{'title':title}),printed)
            with self.assertRaises(ValueError):
                verify_identity(self.root/'source.pdf',{'title':'An unrelated short title'})

    def test_note_uses_registered_original_never_note_body(self):
        pid, asset, digest = self.paper('note')
        incoming = self.folder/'note.docx'; incoming.write_bytes(b'private scientific answer')
        with self.inspect_mock({'kind':'reading_reference','source_hash':hashlib.sha256(incoming.read_bytes()).hexdigest(),'dois':['10.1234/note']}):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual(report['items'][0]['state'],'manual_existing_card' if self.catalog.get(pid)['card_path'] else 'manual_registered')
        self.assertTrue(incoming.exists())
        self.assertEqual(self.catalog.get(pid)['asset_path'],str(asset))
        self.assertNotIn('private scientific answer',json.dumps(report))
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM manual_card_priority').fetchone()[0],0)

    def test_removing_uninspected_manual_file_is_recorded_as_removed(self):
        incoming = self.folder/'broken.pdf'; incoming.write_bytes(b'broken')
        def inspect(command, **kwargs): raise ValueError('broken PDF')
        with patch.object(manual.subprocess,'run',side_effect=inspect):
            manual.run_once(self.catalog,self.config)
        incoming.unlink()
        manual.run_once(self.catalog,self.config)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM manual_literature_items').fetchone()[0],'removed')
            self.assertEqual(db.execute('SELECT count(*) FROM manual_card_priority').fetchone()[0],0)

    def test_existing_card_in_manual_folder_does_not_get_priority(self):
        pid, asset, digest = self.paper('protected')
        (self.folder/'original.pdf').write_bytes(asset.read_bytes())
        self.catalog.update(pid,card_path=str(self.root/'existing-card.json'))
        with self.inspect_mock({'kind':'original_pdf','source_hash':digest}):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual(report['items'][0]['state'],'stored')
        self.assertEqual(report['selection']['added'],[])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM manual_card_priority').fetchone()[0],0)

    def test_current_hash_required_and_seed_priority_applies_only_to_cards(self):
        pid, _, digest = self.paper('priority')
        with self.catalog.connect() as db:
            db.execute('INSERT INTO manual_card_priority VALUES(?,?,?)',(pid,digest,1))
            rows = [{'paper_id':'auto','job_id':'auto','lane':'cards','queued_at':0,'source_sha256':'auto'},
                    {'paper_id':pid,'job_id':pid,'lane':'cards','queued_at':10,'source_sha256':digest},
                    {'paper_id':pid,'job_id':'review','lane':'review','queued_at':0,'source_sha256':digest}]
            ranked = sort(db,rows,self.config)
            self.assertEqual(ranked[0]['job_id'],pid)
            self.assertFalse(ranked[1]['manual_priority'])
            db.execute('UPDATE manual_card_priority SET source_hash=?',('stale',))
            self.assertFalse(any(row['manual_priority'] for row in sort(db,rows,self.config)))
        self.assertEqual(rows[1]['queued_at'],10)

    def test_docx_inspection_outputs_only_identifier_and_hash(self):
        path = self.folder/'note.docx'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>DOI: 10.1234/abc private scientific summary</w:t></w:r></w:p></w:document>')
        result = manual.inspect_file(path)
        self.assertEqual(result['dois'],['10.1234/abc'])
        self.assertNotIn('private scientific summary',json.dumps(result))

    def test_failed_file_does_not_block_other_intake(self):
        pid, asset, digest = self.paper('good')
        (self.folder/'a.pdf').write_bytes(b'broken')
        (self.folder/'b.pdf').write_bytes(asset.read_bytes())
        def inspect(command, **kwargs):
            if command[-1].endswith('a.pdf'):raise ValueError('broken PDF')
            return subprocess.CompletedProcess([],0,stdout=json.dumps({'kind':'original_pdf','source_hash':digest}),stderr='')
        with patch.object(manual.subprocess,'run',side_effect=inspect):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual([i['state'] for i in report['items']],['needs_inspection','stored'])
        self.assertEqual(report['selection']['added'],[])

    def test_seed_rejects_non_pdf(self):
        path = self.seed_folder/'note.docx'; path.write_bytes(b'not a seed')
        with self.inspect_mock({'kind':'reading_reference','source_hash':hashlib.sha256(b'not a seed').hexdigest(),'dois':['10.1234/x']}):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual(report['items'][0]['state'],'seed_needs_inspection')
        self.assertTrue(path.exists())

    def test_manual_version_conflict_never_overwrites_imported_asset(self):
        pid, asset, digest = self.paper('version')
        incoming = self.folder/'changed.pdf'; incoming.write_bytes(b'changed version')
        new_hash = hashlib.sha256(incoming.read_bytes()).hexdigest()
        info = {'kind':'original_pdf','source_hash':new_hash,
                'record':{'title':'Verified paper title version','doi':'10.1234/version'}}
        with self.inspect_mock(info):
            report = manual.run_once(self.catalog,self.config)
        self.assertEqual(report['items'][0]['state'],'needs_inspection')
        self.assertTrue(incoming.exists())
        self.assertEqual(Path(self.catalog.get(pid)['asset_path']).read_bytes(),b'original')
        self.assertEqual(self.catalog.get(pid)['asset_hash'],digest)


class SupplementCoverTests(unittest.TestCase):
    def test_acs_front_matter_link_is_not_a_supplement(self):
        text = ('Machine-Learning Predictions\nAuthors\nCite This: J. 2026\n'
                'Supporting Information\nABSTRACT: A full article body.\n1. INTRODUCTION')
        self.assertFalse(manual._supplement_cover(text))

    def test_cover_heading_without_article_body_is_a_supplement(self):
        text = 'Supporting Information\nFigure S1. Spectra\nTable S1. Energies'
        self.assertTrue(manual._supplement_cover(text))


if __name__ == '__main__':
    unittest.main()
