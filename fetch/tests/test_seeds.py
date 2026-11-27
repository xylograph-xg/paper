import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog
from core.services import init_seeds, discover


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.c=Catalog(self.root/'catalog.db')
        self.p=self.c.upsert({'title':'Organic triplet exciton transport','doi':'10.1000/seed'},candidate=True)
        self.c.decide(self.p,'deep_read');self.c.update(self.p,asset_path='/original.pdf',card_path='/card.json')
    def tearDown(self):self.temp.cleanup()

    def test_seed_membership_does_not_change_reading_or_assets(self):
        before=self.c.get(self.p);result=self.c.set_seed(self.p,True);after=self.c.get(self.p)
        self.assertEqual(after['seed'],1)
        for field in ('decision','asset_path','card_path','candidate_order'):self.assertEqual(before[field],after[field])
        self.assertEqual(next(j for j in self.c.jobs() if j['id']==result['job_id'])['kind'],'seed_control')

    def test_busy_discovery_cannot_swallow_seed_change(self):
        active=self.c.enqueue('discover');self.c.claim(('discover',))
        self.c.set_seed(self.p,True)
        self.assertTrue(self.c.get(self.p)['seed'])
        self.assertEqual(sum(j['kind']=='discover' and j['paper_id']==self.p for j in self.c.jobs()),1)
        self.assertEqual(next(j for j in self.c.jobs() if j['id']==active)['state'],'running')

    def test_one_off_related_metadata_cannot_implicitly_promote_non_seed(self):
        with self.c.connect() as db:db.execute('UPDATE papers SET seed=1 WHERE id=?',(self.p,))
        self.assertFalse(self.c.get(self.p)['seed'])
        self.c.set_seed(self.p,True)
        self.assertTrue(self.c.get(self.p)['seed'])

    def test_legacy_endpoint_enqueue_also_persists_the_seed_control(self):
        self.c.enqueue('discover')
        job=self.c.enqueue('discover',payload={'seed_id':self.p,'seed_action':'add'})
        self.assertEqual(self.c.get(self.p)['seed'],1)
        self.assertEqual(next(j for j in self.c.jobs() if j['id']==job)['state'],'done')

    def test_repeated_add_does_not_duplicate_expansion_and_remove_cancels_queued(self):
        self.c.set_seed(self.p,True);self.c.set_seed(self.p,True)
        self.assertEqual(sum(j['kind']=='discover' and j['paper_id']==self.p and j['state']=='queued' for j in self.c.jobs()),1)
        self.c.set_seed(self.p,False)
        self.assertFalse(self.c.get(self.p)['seed'])
        self.assertFalse(any(j['kind']=='discover' and j['paper_id']==self.p and j['state']=='queued' for j in self.c.jobs()))
        self.c.upsert({'title':'Organic triplet exciton transport','doi':'10.1000/seed'},seed=True)
        self.assertFalse(self.c.get(self.p)['seed'])

    def test_corrections_and_unscreened_candidates_cannot_be_seeds(self):
        p=self.c.upsert({'title':'Erratum','doi':'10.1000/correction','is_correction':True},seed=True)
        with self.assertRaises(ValueError):self.c.set_seed(p,True)
        p=self.c.upsert({'title':'OLED candidate','doi':'10.1000/candidate'})
        with self.assertRaises(ValueError):self.c.set_seed(p,True)

    def test_initial_seed_registration_respects_explicit_removal(self):
        folder=self.root/'data/seed_intake';folder.mkdir(parents=True)
        (folder/'seeds.json').write_text(json.dumps([{'title':'Organic triplet exciton transport','doi':'10.1000/seed'}]))
        self.c.set_seed(self.p,True);self.c.set_seed(self.p,False)
        with patch('core.services.ROOT',self.root):init_seeds(self.c,{})
        self.assertFalse(self.c.get(self.p)['seed'])

    def test_following_discovery_uses_all_selected_seeds_and_excludes_errata(self):
        self.c.set_seed(self.p,True)
        self.c.upsert({'title':'Erratum','doi':'10.1000/erratum','is_correction':True},seed=True)
        config={'archive_volume':str(self.root),'archive_root':str(self.root/'archive'),'require_mounted_volume':False,'first_round':{'candidate_limit_total':10}}
        with patch('core.services.bridge',return_value={'pool':[],'resolved':[],'raw':[],'warnings':[]}) as bridge:
            discover(self.c,config)
        self.assertEqual([p['doi'] for p in bridge.call_args.args[1]['seeds']],['10.1000/seed'])
