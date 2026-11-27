import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.catalog import Catalog
from cards.web_card_queue import _selection_papers, ranking, select


class SelectionProjectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.catalog=Catalog(self.root/'catalog.sqlite')
        self.config={'studio_library_root':str(self.root/'library'),'topic_queries':['topic material'],
            'journal_priority':{'science':3},'web_cards':{'selection_fraction':1}}

    def paper(self, title, **metadata):
        pid=self.catalog.upsert({'title':title,**metadata});source=self.root/(pid+'.pdf');source.write_bytes(b'original')
        self.catalog.update(pid,acquisition='available',asset_path=str(source),
            asset_hash=hashlib.sha256(source.read_bytes()).hexdigest())
        return pid

    def test_projection_preserves_ranking_flags_and_missing_vs_null_citations(self):
        for i,citation in enumerate([{}, {'citation_count':None}, {'citation_count':0}, {'citation_count':21}]):
            pid=self.paper('topic material '+str(i),venue='Science',year=2025,cited_by_count=51,
                identity_review_required=i==1,version_review_required=i==2,out_of_scope=i==3,**citation)
            with self.catalog.connect() as db:
                db.execute('UPDATE papers SET assessment=? WHERE id=?',
                    (json.dumps({'relevance':8,'evidence_unverified':False,'unused_card_body':'x'*10000}),pid))
        originals={p['id']:p for p in self.catalog.list()}
        for p in _selection_papers(self.catalog):
            original=originals[p['id']]
            self.assertEqual(ranking(p,self.config),ranking(original,self.config))
            for flag in ['identity_review_required','version_review_required','out_of_scope']:
                self.assertEqual(bool(p['metadata'].get(flag)),bool(original['metadata'].get(flag)))
            self.assertNotIn('unused_card_body',p['assessment'])

    def test_selection_does_not_load_catalog_history_and_preserves_existing_card_denominator(self):
        current=self.paper('current');protected=self.paper('existing')
        self.catalog.update(protected,card_path=str(self.root/'existing-card.json'))
        self.catalog.upsert({'title':'unavailable metadata only'})
        with patch.object(self.catalog,'list',side_effect=AssertionError('full catalog loader must not run')):
            result=select(self.catalog,self.config)
        self.assertEqual(result['available'],2);self.assertEqual(result['target'],2)
        self.assertEqual(result['added'],[current])
