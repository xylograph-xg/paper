"""Meaningful automatic-only contracts with synthetic originals and frozen inputs."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from core.api import catalog__Catalog as Catalog
from literature.api import Library
from literature.classifier import classify, metadata_fingerprint, validate_evidence
from literature.inputs import prepare_document, blocks_from_pages


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.db')
        self.pid=self.catalog.upsert({'title':'TADF emitters for organic light-emitting diodes','doi':'10.1000/automatic','abstract':'We report donor-acceptor TADF emitters for OLEDs.'})
        self.source=self.root/'source.pdf';self.source.write_bytes(b'%PDF synthetic source bound by content hash')
        self.source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.catalog.update(self.pid,acquisition='available',asset_path=str(self.source),asset_hash=self.source_hash)
        self.folder=self.root/'frozen';self.folder.mkdir()
        self.pages=[{'source_page':1,'text':'Introduction\nPrevious studies reported Dexter energy transfer.\nResults and Discussion\nWe measured reverse intersystem crossing using temperature-dependent photoluminescence spectra. We performed time-dependent density functional theory calculations.\nReferences\nA. Author. Transient absorption spectroscopy.'}]
        raw=json.dumps({'source_text':self.pages,'scientific_rules':'FORBIDDEN_OLD_RULES'},ensure_ascii=False).encode()
        (self.folder/'source-context.json').write_bytes(raw)
        self.packet={'paper_id':self.pid,'source_original_sha256':self.source_hash,'input_hashes':{'source-context.json':hashlib.sha256(raw).hexdigest()}}
        (self.folder/'packet.json').write_text(json.dumps(self.packet))
        from cards.api import web_card_queue__install as install
        install(self.catalog)
        with self.catalog.connect() as db:
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,provider,folder,error,attempts,updated) VALUES(?,?,?,'{}','ready','gpt',?,'',0,'')",(self.pid,self.source_hash,'TADF',str(self.folder)))
        self.library=Library(self.catalog.path)

    def document(self):
        from core.api import literature_catalog__source_records as records
        return prepare_document(records(self.catalog.path,[self.pid])[0])

    def test_two_stages_and_reference_background_exclusion(self):
        doc=self.document();r=classify(doc)
        self.assertIn('topic.tadf',{t['id'] for t in r['level1']})
        fine={t['id'] for t in r['level2']+r['supporting_labels'] if t['level']==2}
        self.assertIn('mechanism.risc',fine);self.assertIn('method.tddft',fine)
        self.assertNotIn('mechanism.dexter',fine);self.assertNotIn('method.transient_absorption',fine)
        self.assertNotIn('FORBIDDEN_OLD_RULES',json.dumps(doc))
        validate_evidence(doc,r)
        self.assertFalse(r['scientific_verified'])

    def test_primary_readonly_persistence_idempotence_and_freshness(self):
        with self.catalog.connect() as db:before=list(db.iterdump())
        first=self.library.auto_label([self.pid]);second=self.library.auto_label([self.pid])
        self.assertEqual(first['results'][0]['run_id'],second['results'][0]['run_id'])
        self.assertTrue(any(a['state']=='automatic' for a in self.library.detail(self.pid)['annotations']))
        frozen=self.library.store.automatic_input(self.pid)
        self.assertEqual(frozen,self.document())
        with self.catalog.connect() as db:after=list(db.iterdump())
        self.assertEqual(before,after)
        self.catalog.upsert({'doi':'10.1000/automatic','title':'New subject'})
        detail=self.library.detail(self.pid)
        self.assertFalse(detail['automatic_labeling']['input_current'])
        self.assertFalse(any(a['state']=='automatic' for a in detail['annotations']))

    def test_corrupt_or_changed_original_and_missing_input_are_not_guessed(self):
        self.source.write_bytes(b'changed original')
        doc=self.document();self.assertEqual(doc['chunks'],[])
        self.assertIn('current_original_hash_mismatch',doc['limitations'])
        self.assertEqual(classify(doc)['level2_state'],'missing_input')
        self.source.write_bytes(b'%PDF synthetic source bound by content hash')
        (self.folder/'source-context.json').write_text('{"source_text":[]}')
        doc=self.document();self.assertEqual(doc['chunks'],[])
        self.assertIn('frozen_context_hash_mismatch',doc['material_errors'])

    def test_metadata_only_and_manual_api_disabled(self):
        self.catalog.update(self.pid,asset_path=None,acquisition='not_attempted')
        r=self.library.auto_label([self.pid])['results'][0]
        self.assertTrue(r['level1']);self.assertEqual(r['level2_state'],'missing_input')
        with self.assertRaisesRegex(ValueError,'人工'):self.library.dispatch('annotate',{'records':[]})
        with self.assertRaisesRegex(ValueError,'人工'):self.library.annotate([])

    def test_negative_and_background_and_typography_offsets(self):
        doc=self.document();doc['chunks']=[{'id':'a','scope':'fulltext','page':2,'section':'results','text':'We observed no evidence for Dexter energy transfer. We performed time-dependent density func-\ntional theory calculations.'}]
        r=classify(doc);ids={x['id'] for x in r['level2']+r['supporting_labels'] if x['level']==2}
        self.assertNotIn('mechanism.dexter',ids);self.assertIn('method.tddft',ids)
        validate_evidence(doc,r)
        doc['abstract']='Previous studies reported phosphorescence.';doc['title']='A different phenomenon'
        self.assertFalse(classify(doc)['level1'])

    def test_same_information_contract_and_bounded_body_coverage(self):
        doc=self.document();r=classify(doc)
        changed=json.loads(json.dumps(doc));changed['chunks']=[]
        self.assertEqual(classify(changed)['level2'],[])
        self.assertNotEqual(r['input_fingerprint'],classify(changed)['input_fingerprint'])
        self.assertIn('selected_chars',doc['coverage'])
        self.assertTrue(all(b['page']>=1 for b in doc['chunks']))
        self.assertFalse(any('References' in b['text'] for b in doc['chunks']))

    def test_protected_source_stays_metadata_only(self):
        from core.api import literature_catalog__source_records as records
        row=records(self.catalog.path,[self.pid])[0];row['metadata']['identity_review_required']=True
        doc=prepare_document(row)
        self.assertEqual(doc['chunks'],[])
        self.assertIn('source_identity_version_or_scope_protected',doc['limitations'])

    def test_si_only_guard_is_separate_from_frozen_hash_integrity(self):
        text='S1\nSupporting Information\nSynthetic emitter paper\nMethods\nWe measured reverse intersystem crossing.'
        raw=json.dumps({'source_text':[{'source_page':1,'text':text}]}).encode()
        (self.folder/'source-context.json').write_bytes(raw)
        self.packet['input_hashes']['source-context.json']=hashlib.sha256(raw).hexdigest()
        (self.folder/'packet.json').write_text(json.dumps(self.packet))
        doc=self.document()
        self.assertEqual(doc['chunks'],[])
        self.assertIn('supplementary_input_not_main_article',doc['limitations'])
        self.assertEqual(doc['source_provenance']['source_kind'],'supplementary_only')

    def test_explicit_pdf_fallback_uses_local_text_without_frozen_writes(self):
        import pymupdf
        pdf=pymupdf.open();page=pdf.new_page()
        text='Methods\nWe performed time-dependent density functional theory calculations.\nWe measured temperature-dependent photoluminescence spectra to investigate reverse intersystem crossing in TADF emitters.\nThe experimental spectra and calculations are compared for this molecular system.'
        page.insert_textbox(pymupdf.Rect(40,40,550,750),text,fontsize=11)
        self.source.unlink();pdf.save(self.source);pdf.close()
        h=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.catalog.update(self.pid,asset_hash=h)
        before=(self.folder/'source-context.json').read_bytes()
        result=self.library.auto_label([self.pid],fallback_pdf=True)['results'][0]
        self.assertTrue(result['level2'])
        self.assertEqual(self.library.store.automatic_input(self.pid)['source_provenance']['kind'],'local_pdf_text')
        self.assertEqual((self.folder/'source-context.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
