"""Core direction behavior, hierarchy retrieval and retained supporting evidence."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from core.api import catalog__Catalog as Catalog
from literature.api import Library, Store, classify
from literature.classifier import validate_evidence, metadata_fingerprint


def document(title='MR-TADF emitters for OLEDs', abstract='We investigate reverse intersystem crossing.'):
    return {'paper_id':'synthetic', 'title':title, 'abstract':abstract,
        'metadata_fingerprint':'meta', 'source_fingerprint':'source',
        'chunks':[{'id':'body','scope':'fulltext','section':'results','page':2,
            'text':'We investigate reverse intersystem crossing. We performed cyclic voltammetry measurements.'}]}


class CoreDirectionTests(unittest.TestCase):
    def test_no_duplicate_parents_or_generic_objects_and_routine_methods_retained(self):
        d=document();r=classify(d)
        self.assertEqual({x['id'] for x in r['level1']},{'topic.mr_tadf','topic.oled'})
        self.assertIn('mechanism.risc',{x['id'] for x in r['level2']})
        self.assertNotIn('method.electrochemistry',{x['id'] for x in r['level2']})
        self.assertIn('method.electrochemistry',{x['id'] for x in r['supporting_labels']})
        self.assertEqual({x['id'] for x in r['inherited_labels']},{'topic.tadf','topic.organic_luminescence'})
        validate_evidence(d,r)
        damaged=deepcopy(r);damaged['supporting_labels'][0]['evidence'][0]['quote']='invented'
        with self.assertRaises(ValueError):validate_evidence(d,damaged)

    def test_distinctive_method_needs_body_evidence_even_if_abstract_names_it(self):
        d=document(abstract='We develop cyclic voltammetry for these materials.')
        r=classify(d)
        self.assertIn('method.electrochemistry',{x['id'] for x in r['level2']})
        d['chunks']=[]
        self.assertEqual(classify(d)['level2'],[])

    def test_guidance_does_not_pad_or_truncate_and_level1_stays_metadata_only(self):
        d=document(title='TADF, AIE, phosphorescence and exciplex emission',abstract='')
        first=classify(d)
        self.assertEqual(len(first['level1']),4)
        d['chunks']=[]
        self.assertEqual(first['level1'],classify(d)['level1'])
        self.assertEqual(classify(d)['level2'],[])
        self.assertFalse(first['count_guidance']['hard_limit'])
        self.assertEqual(classify(document('Unspecified study',''))['level1'],[])

    def test_sidecar_core_and_parent_filter_supporting_only_in_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog=Catalog(Path(tmp)/'catalog.db')
            pid=catalog.upsert({'title':'MR-TADF emitters for OLEDs','abstract':'We investigate reverse intersystem crossing.'})
            catalog.update(pid,asset_hash='source')
            library=Library(catalog.path)
            d=document();d['paper_id']=pid
            d['metadata_fingerprint']=metadata_fingerprint(library._rows()[0])
            r=classify(d);pristine=deepcopy(r)
            saved=library.store.save_automatic_run(d,r)
            self.assertEqual(r,pristine)  # Persistence must not mutate the frozen prediction.
            self.assertEqual(saved['run_id'],library.store.save_automatic_run(d,r)['run_id'])
            parent=library.store.resolve('热活化延迟荧光','topic')
            routine=library.store.resolve('循环伏安测量','method')
            self.assertEqual(library.query({'tags':{'topic':[parent]}})['total'],1)
            self.assertEqual(library.query({'tags':{'method':[routine]}})['total'],0)
            detail=library.detail(pid)
            self.assertIn('supporting',{a.get('importance') for a in detail['annotations']})
            catalog.update(pid,asset_hash='changed')
            self.assertFalse(any(a.get('level')==2 for a in library.detail(pid)['annotations']))

    def test_old_automatic_runs_remain_readable_and_distinct_from_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'labels.db');d=document();r=classify(d)
            old=deepcopy(r);old['rule_version']='historical';old.pop('selection_policy')
            a=store.save_automatic_run(d,old);b=store.save_automatic_run(d,r)
            self.assertNotEqual(a['run_id'],b['run_id'])
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM automatic_runs').fetchone()[0],2)
