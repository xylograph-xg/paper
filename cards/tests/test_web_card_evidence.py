import os
import copy
import json
from core.api import paths__WorkspacePath as Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from cards.web_card_inputs import prepare, digest
from cards.web_card_evidence import verify


class WebEvidence(unittest.TestCase):
    quote='Triplet excitons persist under explicitly stated experimental conditions.'

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'inputs'
        bundle_environment=patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')})
        bundle_environment.start();self.addCleanup(bundle_environment.stop)
        source=self.root/'source.pdf'
        with pymupdf.open() as doc:
            doc.new_page().insert_text((20,40),self.quote,fontsize=10)
            doc.new_page().insert_text((20,40),'A different page contains unrelated source observations.',fontsize=10)
            doc.save(source)
        self.packet=prepare(source,self.folder,'synthetic','Synthetic evidence',digest(source))
        self.card={'figures':[{'label':'Fig. 1','source_page':1,'evidence_quote':self.quote,'one_line':r'$\Omega_{CT}$ remains distinct from $\omega$'}],
                   'equations':[],'tables':[]}

    def test_exact_quote_is_checked_against_actual_pdf_and_sent_page(self):
        original=copy.deepcopy(self.card)
        report=verify(self.card,self.folder,self.packet,{})
        self.assertEqual(report['verified_count'],1);self.assertTrue(report['evidence_verified'])
        self.assertEqual(self.card['figures'][0]['evidence_status'],'verified')
        self.assertEqual(self.card['figures'][0]['one_line'],original['figures'][0]['one_line'])
        self.assertFalse(report['scientific_verified']);self.assertFalse(report['production_contract_complete'])

    def test_plausible_fabrication_or_wrong_page_never_verified(self):
        for change in ({'evidence_quote':'A plausible but invented scientific source observation.'},{'source_page':2}):
            card=copy.deepcopy(self.card);card['figures'][0].update(change)
            report=verify(card,self.folder,self.packet,{})
            self.assertFalse(report['evidence_verified']);self.assertEqual(report['needs_review_count'],1)

    def test_changed_frozen_context_blocks_publication(self):
        (self.folder/'source-context.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'指纹变化'):verify(self.card,self.folder,self.packet,{})

    def test_past_pruned_attachment_does_not_get_fabricated_as_complete(self):
        (self.folder/'visual.pdf').unlink()
        with self.assertRaises(FileNotFoundError):verify(self.card,self.folder,self.packet,{})
        report=verify(self.card,self.folder,self.packet,{},require_complete_inputs=False)
        self.assertEqual(report['verified_count'],1)
        self.assertFalse(report['input_artifacts_complete']);self.assertEqual(report['missing_inputs'],['visual.pdf'])
        self.assertFalse(report['production_contract_complete'])

    def test_changed_visual_evidence_blocks_publication(self):
        (self.folder/'pages/P001.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'视觉证据'):verify(self.card,self.folder,self.packet,{})

    def test_missing_text_extractor_is_explicitly_unverified(self):
        with patch('cards.web_card_evidence.subprocess.run',side_effect=FileNotFoundError('missing interpreter')):
            report=verify(self.card,self.folder,self.packet,{})
        self.assertEqual(report['state'],'unavailable');self.assertEqual(report['needs_review_count'],1)

    def test_scientific_symbol_case_is_significant(self):
        from read.app.evidence_literal import literal_match
        self.assertFalse(literal_match('Omega','omega',case_sensitive=True))
        self.assertFalse(literal_match('Ω','ω',case_sensitive=True))


class MathSummary(unittest.TestCase):
    def test_web_card_inventory_never_uses_local_model_identity(self):
        from reading.reading_contract import inventory
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'card';folder.mkdir()
            (folder/'card.json').write_text(json.dumps({'meta':{'producer':'web_card_service','evidence_verification':{'evidence_verified':True}}}))
            with patch('reading.reading_contract.verified_completion',side_effect=AssertionError('local model contract must not run')):
                self.assertEqual(inventory(td)['cards'][0]['state'],'web_source_quotes_verified')
    def test_math_delimiters_unknown_commands_and_scripts_are_preserved(self):
        from read.app.analyzer import plain_text
        values=[r'$k_{cat}^{app}$',r'$\Omega_{CT}$',r'$\eta_{EQE}$ and $\varepsilon_r$',
                r'$2^{1}A_{g}^{-}$',r'$\omega$ and $\Omega$',r'$\unknown_{r}^{2}$']
        for value in values:self.assertEqual(plain_text(value),value)

    def test_preserved_summary_remains_visible_to_math_checker(self):
        from read.app.analyzer import parse_one_line
        from reading.science_verifier import math_spans
        findings,summary=parse_one_line('An observation.\n一句话总结：$k_{cat}^{app}$ obeys $x^2$.')
        self.assertIn('$k_{cat}^{app}$',summary);self.assertIn('$x^2$',summary)
        self.assertEqual(len(math_spans(summary)),2)
