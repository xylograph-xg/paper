import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog
from core.services import StorageUnavailable, archive_root, store_asset, validate_assessment, verify_identity, public_url, auto_select


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.db')
        from core.catalog import load_config
        self.config={'model':load_config()['model'],'archive_volume':str(self.root),'archive_root':str(self.root/'archive'),'require_mounted_volume':False,
                     'journal_priority':{'Physical Review Letters':2},'first_round':{'direct_card_selection':{'first_round_maximum':1}}}

    def tearDown(self):
        self.temp.cleanup()

    def test_title_identity_survives_doi_enrichment_and_reopen(self):
        first=self.catalog.upsert({'title':'Triplet coherence in rubrene'},candidate=True)
        second=self.catalog.upsert({'title':'Triplet coherence in rubrene','doi':'https://doi.org/10.1000/ABC'})
        self.assertEqual(first,second)
        self.assertEqual(Catalog(self.root/'catalog.db').get(first)['metadata']['doi'],'10.1000/abc')
        self.assertEqual(self.catalog.get(first)['candidate_order'],1)

    def test_conflicting_dois_remain_separate(self):
        a=self.catalog.upsert({'title':'Same title','doi':'10.1/a'})
        b=self.catalog.upsert({'title':'Same title','doi':'10.1/b'})
        self.assertNotEqual(a,b)

    def test_source_identifiers_cannot_merge_two_existing_papers(self):
        self.catalog.upsert({'title':'A','doi':'10.1/a'})
        self.catalog.upsert({'title':'B','semantic_scholar_id':'s2-b'})
        with self.assertRaises(ValueError):
            self.catalog.upsert({'title':'A','doi':'10.1/a','semantic_scholar_id':'s2-b'})
        self.catalog.upsert({'title':'C','doi':'10.1/c','semantic_scholar_id':'s2-c'})
        with self.assertRaises(ValueError):
            self.catalog.upsert({'title':'C','doi':'10.1/other','semantic_scholar_id':'s2-c'})

    def test_queue_deduplicates_recovers_and_retries(self):
        pid=self.catalog.upsert({'title':'A'})
        job=self.catalog.enqueue('screen',pid)
        self.assertEqual(job,self.catalog.enqueue('screen',pid))
        claimed=self.catalog.claim();self.assertEqual(claimed['id'],job)
        reopened=Catalog(self.root/'catalog.db');reopened.recover()
        self.assertEqual(reopened.jobs()[0]['state'],'failed')
        reopened.retry(job);self.assertEqual(reopened.claim()['id'],job)

    def test_human_rejection_cancels_queued_read_and_blocks_auto(self):
        pid=self.catalog.upsert({'title':'A'},candidate=True)
        self.catalog.enqueue('deep_read',pid)
        self.catalog.decide(pid,'reject')
        self.assertEqual(self.catalog.jobs()[0]['state'],'cancelled')
        self.catalog.decide(pid,'unreviewed')
        self.assertFalse(self.catalog.reserve_auto(pid,{},1))

    def test_quota_is_persistent_and_not_reset_by_runs(self):
        ids=[self.catalog.upsert({'title':f'Paper {i}','doi':f'10.1000/{i}'},candidate=True) for i in range(101)]
        self.assertTrue(self.catalog.reserve_auto(ids[0],{},1))
        self.assertFalse(self.catalog.reserve_auto(ids[1],{},1))
        self.assertFalse(Catalog(self.root/'catalog.db').reserve_auto(ids[2],{},1))
        self.assertTrue(self.catalog.reserve_auto(ids[100],{},1))

    def test_first_round_ranks_recent_bonus_and_allows_zero(self):
        ids=[]
        for name,year in [('Old',2010),('Recent',2026)]:
            pid=self.catalog.upsert({'title':name,'venue':'Physical Review Letters','year':year},candidate=True);ids.append(pid)
            self.catalog.update(pid,asset_path='/placeholder/source.pdf',assessment={'relevance':5,'novelty_high':True,
                'novelty':'Compared with seed evidence','evidence_quote':'An observation','evidence_scope':'PDF 文字层全文','evidence_basis':'fulltext',
                'recommendation_reason':'Relevant','workflow_fingerprint':__import__('core.services',fromlist=['screen_workflow_fingerprint']).screen_workflow_fingerprint(self.config['model']),'prompt_version':__import__('core.services',fromlist=['SCREEN_PROMPT_VERSION']).SCREEN_PROMPT_VERSION})
        auto_select(self.catalog,self.config)
        self.assertEqual(self.catalog.get(ids[1])['decision'],'deep_read')
        self.assertEqual(self.catalog.get(ids[0])['decision'],'unreviewed')
        self.assertFalse(self.catalog.reserve_auto(ids[0],{},1))

    def test_unmounted_ssd_does_not_create_fallback(self):
        self.config['require_mounted_volume']=True
        with self.assertRaises(StorageUnavailable):
            archive_root(self.config)
        self.assertFalse((self.root/'archive').exists())

    def test_pdf_asset_hash_dedup_and_wrong_paper(self):
        import pymupdf
        file=self.root/'source.pdf'
        doc=pymupdf.open();page=doc.new_page();page.insert_text((50,50),'Triplet coherence in rubrene DOI: 10.1000/abc');doc.save(file);doc.close()
        verify_identity(file,{'title':'Triplet coherence in rubrene','doi':'10.1000/abc'})
        with self.assertRaises(ValueError):
            verify_identity(file,{'title':'Entirely unrelated methods for galaxies','doi':'10.1000/other'})
        a=store_asset(file,self.config);b=store_asset(file,self.config)
        self.assertEqual(a,b)
        Path(a[0]).write_bytes(b'corrupted')
        with self.assertRaises(ValueError):
            store_asset(file,self.config)

    def test_model_cannot_invent_evidence(self):
        data={'core_findings':'结论','recommendation_reason':'理由','novelty':'新颖','evidence_quote':'invented','relevance':4,'tags':[],'novelty_high':True}
        with self.assertRaises(ValueError):
            validate_assessment(data,'actual experiment')
        data['evidence_quote']=''
        self.assertFalse(validate_assessment(data,'actual experiment')['novelty_high'])

    def test_pdf_typography_and_explicit_omissions_are_grounded(self):
        data={'core_findings':'结论','recommendation_reason':'理由','novelty':'新颖','evidence_quote':'Measured phosphorescent emission. ... The host-guest result is reproducible.',
              'relevance':4,'tags':[],'novelty_high':True}
        result=validate_assessment(data,'Measured phosphores-\ncent emission. Other evidence not quoted. The host–guest result is reproducible.')
        self.assertEqual(len(result['evidence_excerpts']),2)
        data['evidence_quote']='The host-guest result is definitely reproducible.'
        with self.assertRaises(ValueError):
            validate_assessment(data,'The host–guest result is reproducible.')

    def test_download_rejects_private_destination_and_credentials(self):
        with patch('socket.getaddrinfo',return_value=[(None,None,None,None,('127.0.0.1',80))]):
            with self.assertRaises(ValueError):
                public_url('http://host/source.pdf')
        with self.assertRaises(ValueError):
            public_url('https://user:password@example.org/file.pdf')

    def test_download_accepts_dns_resolved_local_proxy_fake_ip_only(self):
        with patch('socket.getaddrinfo',return_value=[(None,None,None,None,('198.18.0.77',443))]):
            self.assertEqual(public_url('https://www.nature.com/article.pdf'),'https://www.nature.com/article.pdf')
        with patch('socket.getaddrinfo',return_value=[(None,None,None,None,('198.18.0.5',80))]):
            with self.assertRaises(ValueError):
                public_url('http://198.18.0.5/source.pdf')


if __name__=='__main__':
    unittest.main()
