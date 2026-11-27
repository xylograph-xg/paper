import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import json
from core.catalog import Catalog
from fetch.preprints import parse_arxiv, parse_chemrxiv, relevant
from core.services import discover, maybe_daily


class ChannelTests(unittest.TestCase):
    def test_legacy_source_string_and_null_lists_are_normalized(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db')
            p=c.upsert({'title':'OLED','doi':'10.1000/legacy','source':'openalex','pdf_urls':None})
            with c.connect() as db:
                db.execute('UPDATE papers SET metadata=? WHERE id=?',(json.dumps({'title':'OLED','doi':'10.1000/legacy','source':'openalex'}),p))
            c.upsert({'title':'OLED','doi':'10.1000/legacy','source':['arxiv']})
            self.assertEqual(c.get(p)['metadata']['source'],['openalex','arxiv'])

    def test_chemrxiv_null_authors_and_links_and_false_oled_acronym(self):
        records=parse_chemrxiv([{'DOI':'10.26434/chemrxiv-2025-x-v1','title':['OLED emitter'],'author':None,'link':None}])
        self.assertEqual(len(records),1)
        self.assertFalse(relevant('OLED-MoE: Accelerating dLLM inference'))

    def test_completion_loop_continues_success_and_backs_off_empty_round(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db')
            config={'automatic_schedule_enabled':True,'daily_schedule':{'mode':'on_completion','idle_backoff_minutes':30},'archive_volume':folder,'archive_root':str(Path(folder)/'archive'),'require_mounted_volume':False}
            first=maybe_daily(c,config);self.assertIsNotNone(first)
            self.assertIsNone(maybe_daily(c,config))
            c.finish(first['job_id'],'done')
            with c.connect() as db:db.execute('INSERT INTO runs VALUES(?,?,?)',('test',datetime.now(timezone.utc).isoformat(),json.dumps({'selected':['verified']})))
            second=maybe_daily(c,config);self.assertNotEqual(first['job_id'],second['job_id'])
            c.finish(second['job_id'],'done')
            with c.connect() as db:db.execute('UPDATE runs SET result=?',(json.dumps({'selected':[]}),))
            self.assertIsNone(maybe_daily(c,config))
            self.assertIsNotNone(maybe_daily(c,config,datetime.now(timezone.utc)+timedelta(minutes=31)))

    def test_schedule_waits_until_nine_and_checks_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db')
            config={'automatic_schedule_enabled':True,'daily_schedule':{'hour':9,'minute':0},'archive_volume':folder,'archive_root':str(Path(folder)/'archive'),'require_mounted_volume':False}
            self.assertIsNone(maybe_daily(c,config,datetime(2026,10,5,8,59)))
            first=maybe_daily(c,config,datetime(2026,10,5,9,0))
            self.assertEqual(first['job_id'],maybe_daily(c,config,datetime(2026,10,5,12,0))['job_id'])

    def test_arxiv_versions_keep_latest_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db')
            p=c.upsert({'title':'OLED new','doi':'10.48550/arxiv.2406.02703','arxiv_id':'2406.02703','arxiv_version_id':'2406.02703v2'},candidate=True)
            older=c.upsert({'title':'OLED old','doi':'10.48550/arxiv.2406.02703','arxiv_id':'2406.02703','arxiv_version_id':'2406.02703v1'},candidate=True)
            self.assertEqual(p,older);self.assertEqual(c.get(p)['metadata']['arxiv_version_id'],'2406.02703v2')

    def test_arxiv_record_retains_version_and_journal_doi(self):
        xml='''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:x="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/2406.02703v2</id><title>Spin coherence in rubrene</title><summary>Triplet excitons in molecular crystals.</summary><published>2024-06-04T00:00:00Z</published><x:doi>10.1103/PhysRevLett.133.056901</x:doi></entry></feed>'''
        p=parse_arxiv(xml)[0]
        self.assertEqual(p['arxiv_id'],'2406.02703');self.assertEqual(p['arxiv_version_id'],'2406.02703v2')
        self.assertEqual(p['doi'],'10.1103/PhysRevLett.133.056901')
        self.assertEqual(p['publication_kind'],'preprint')

    def test_chemrxiv_preserves_unrelated_for_versioned_scope_policy(self):
        items=[{'DOI':'10.26434/chemrxiv-2025-abcd-v1','title':['OLED emitter'],'posted':{'date-parts':[[2025,1,1]]}},
               {'DOI':'10.26434/chemrxiv-2025-abcd-v2','title':['OLED emitter'],'posted':{'date-parts':[[2025,2,1]]}},
               {'DOI':'10.26434/other','title':['OLED emitter']},
               {'DOI':'10.26434/chemrxiv-2025-no-v1','title':['Galaxy surveys']}]
        result=parse_chemrxiv(items);self.assertEqual(len(result),2);self.assertTrue(any(x['doi'].endswith('abcd-v2') for x in result));self.assertTrue(any(x['title']=='Galaxy surveys' for x in result))
        self.assertFalse(relevant('Triplet stars and galaxies'))

    def test_daily_enqueue_remains_idempotent_after_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db');first=c.enqueue_daily('2026-10-05')
            c.finish(first['job_id'],'done')
            repeated=Catalog(Path(folder)/'catalog.db').enqueue_daily('2026-10-05')
            self.assertEqual(first['job_id'],repeated['job_id']);self.assertTrue(repeated['already_scheduled'])
            self.assertNotEqual(c.enqueue_daily('2026-10-06')['job_id'],first['job_id'])

    def test_preprint_versions_do_not_duplicate_or_downgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Catalog(Path(folder)/'catalog.db')
            first=c.upsert({'title':'OLED emitter','doi':'10.26434/chemrxiv-2025-abcd-v1','channels':['chemrxiv']},candidate=True)
            second=c.upsert({'title':'Updated OLED emitter','doi':'10.26434/chemrxiv-2025-abcd-v2','channels':['journal']},candidate=True)
            self.assertEqual(first,second);self.assertEqual(c.get(first)['candidate_order'],1)
            c.upsert({'title':'OLED emitter','doi':'10.26434/chemrxiv-2025-abcd-v1'})
            self.assertTrue(c.get(first)['metadata']['doi'].endswith('v2'))
            self.assertEqual(set(c.get(first)['metadata']['channels']),{'chemrxiv','journal'})

    def test_round_distributes_slots_across_channels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);c=Catalog(root/'catalog.db');c.upsert({'title':'Organic triplet exciton','doi':'10.1/seed'},seed=True)
            pool=[{'title':f'Organic triplet exciton {channel} paper {i}','doi':f'10.1000/{channel}{i}','channels':[channel],'discovery_reasons':[channel]} for channel in ('journal','arxiv','chemrxiv') for i in range(5)]
            config={'archive_volume':folder,'archive_root':str(root/'archive'),'require_mounted_volume':False,'first_round':{'candidate_limit_total':6}}
            with patch('core.services.bridge',return_value={'pool':pool,'resolved':[],'warnings':[],'raw':[]}):chosen=discover(c,config)
            counts={k:sum(k in c.get(pid)['metadata']['channels'] for pid in chosen) for k in ('journal','arxiv','chemrxiv')}
            self.assertEqual(counts,{'journal':2,'arxiv':2,'chemrxiv':2})

    def test_pdf_only_admits_verified_asset_and_excludes_failed_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);c=Catalog(root/'catalog.db')
            pool=[{'title':'OLED '+str(i),'doi':'10.1000/pdf'+str(i),'channels':['journal'],'discovery_reasons':['topic']} for i in range(2)]
            config={'archive_volume':folder,'archive_root':str(root/'archive'),'require_mounted_volume':False,'first_round':{'candidate_limit_total':10},'pdf_only':True}
            asset=root/'verified.pdf';asset.write_bytes(b'verified fixture')
            def acquire(catalog,config,pid):
                if catalog.get(pid)['title']=='OLED 1':catalog.update(pid,asset_path=str(asset),acquisition='available')
                else:catalog.update(pid,acquisition='needs_manual_download')
            with patch('core.services.bridge',return_value={'pool':pool,'resolved':[],'warnings':[],'raw':[]}),patch('core.services.acquisition',side_effect=acquire):
                chosen=discover(c,config)
            self.assertEqual(len(chosen),1)
            self.assertEqual(c.get(chosen[0])['title'],'OLED 1')
            self.assertEqual(sum(p['candidate_order'] is not None for p in c.list()),1)
            self.assertEqual(sum(j['kind']=='screen' for j in c.jobs()),1)
