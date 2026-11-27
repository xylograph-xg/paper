"""Open-access gate and priority tests for the acquisition queue."""
import json
import unittest
from datetime import date

from fetch.oa_policy import eligible, priority
from fetch.preprints import relevant, recent_enough
from fetch.tests.test_fetch_pipeline import FetchFixtures
from fetch.fetching import queue_pending


class OAPolicyTests(unittest.TestCase):
    def test_preprint_and_repository_routes_are_eligible(self):
        self.assertTrue(eligible({'channels': ['arxiv'], 'doi': '10.48550/arxiv.2401.00001'}))
        self.assertTrue(eligible({'channels': ['journal'], 'doi': '10.1002/x',
                                  'pdf_urls': ['https://eprints.example.ac.uk/x.pdf']}))
        self.assertEqual(priority({'channels': ['arxiv'], 'doi': '10.48550/arxiv.2401.00001'}), 0)

    def test_publisher_only_closed_link_is_not_eligible(self):
        record = {'channels': ['journal'], 'doi': '10.1002/adma.201003128',
                  'pdf_urls': ['https://onlinelibrary.wiley.com/doi/pdf/10.1002/adma.201003128']}
        self.assertFalse(eligible(record))
        self.assertEqual(priority(record), 2)

    def test_explicit_oa_flag_or_green_copy_keeps_subscription_doi(self):
        self.assertTrue(eligible({'channels': ['journal'], 'doi': '10.1002/x', 'is_oa': True}))
        self.assertEqual(priority({'channels': ['journal'], 'doi': '10.1002/x', 'is_oa': True}), 1)
        record = {'channels': ['journal'], 'doi': '10.1002/x',
                  'pdf_urls': ['https://arxiv.org/pdf/2401.00001']}
        self.assertTrue(eligible(record))
        self.assertEqual(priority(record), 0)

    def test_moderate_oa_publishers_are_kept_below_high_yield(self):
        record = {'channels': ['journal'], 'doi': '10.1007/s10853-018-2986-9', 'is_oa': True}
        self.assertTrue(eligible(record))
        self.assertEqual(priority(record), 1)

    def test_high_prefix_without_oa_flag_is_not_eligible(self):
        for doi in ('10.1038/s41586-020-0000-0', '10.1103/PhysRevLett.120.000001',
                    '10.1007/s10853-018-2986-9', '10.1017/s0000000000000000'):
            self.assertFalse(eligible({'channels': ['journal'], 'doi': doi}))


class OAGateQueueTests(FetchFixtures):
    def test_closed_record_is_excluded_and_oa_records_are_queued_first(self):
        self.config['fetch_pipeline']['oa_only'] = True
        rows = [
            {'title': 'Organic triplet emitter measurement closed', 'doi': '10.1002/closed',
             'channels': ['journal'], 'pdf_urls': ['https://onlinelibrary.wiley.com/doi/pdf/10.1002/closed']},
            {'title': 'Organic triplet emitter measurement arxiv', 'doi': '10.48550/arxiv.2401.00001',
             'channels': ['arxiv'], 'pdf_urls': ['https://arxiv.org/pdf/2401.00001']},
            {'title': 'Organic triplet emitter measurement repository', 'doi': '10.1002/repository',
             'channels': ['journal'], 'pdf_urls': ['https://eprints.example.ac.uk/paper.pdf']},
        ]
        self.catalog.retain_discovery(rows, {})
        added = queue_pending(self.catalog, self.config)
        self.assertEqual(len(added), 2)
        with self.catalog.connect() as db:
            closed = db.execute("select state,error from discovery_pending where key='10.1002/closed'").fetchone()
            first = json.loads(db.execute("select payload from jobs where id=?", (added[0],)).fetchone()[0]).get('pending_key')
            jobs = {json.loads(r[0]).get('pending_key') for r in db.execute("select payload from jobs")}
        self.assertEqual(closed['state'], 'excluded')
        self.assertIn('OA', closed['error'])
        self.assertEqual(first, '10.48550/arxiv.2401.00001')
        self.assertEqual(jobs, {'10.48550/arxiv.2401.00001', '10.1002/repository'})


class MechanismRelevanceTests(unittest.TestCase):
    def test_mechanism_only_papers_are_kept_with_organic_context(self):
        for text in ('Exciton dynamics in organic molecular crystals',
                     'Triplet-triplet annihilation in conjugated polymers',
                     'Intersystem crossing and spin-orbit coupling in iridium complexes',
                     'Hot exciton electroluminescence in organic emitters',
                     'Singlet fission in molecular crystals',
                     'Triplet-triplet annihilation in rubrene',
                     'Exciton binding energy in organic semiconductors',
                     'Exciton diffusion length in conjugated polymers',
                     'Triplet energy transfer in molecular crystals',
                     'Spin mixing and radical pair recombination in organic crystals',
                     'Aggregation-induced emission from organic luminogens',
                     'Circularly polarized luminescence from chiral organic emitters',
                     'Charge transport and recombination in organic field-effect transistors',
                     'Revealing the contest between triplet-triplet exchange and triplet-triplet energy transfer',
                     'Tetracene dimers: a platform for intramolecular down- and up-conversion'):
            self.assertTrue(relevant(text), text)

    def test_inorganic_exciton_and_unrelated_oled_are_rejected(self):
        self.assertFalse(relevant('Exciton dynamics in GaAs quantum wells'))
        self.assertFalse(relevant('Fluorescence imaging of protein conformations'))
        self.assertFalse(relevant('Lithium battery charge transport in electrolyte'))
        self.assertFalse(relevant('Quantum spin coherence in NV centers'))
        self.assertFalse(relevant('Recombination in optimized organic solar cells'))
        self.assertFalse(relevant('Photophysics of two-dimensional organic-inorganic perovskites'))
        self.assertFalse(relevant('DNA-induced circularly polarized luminescence of helicene racemates'))
        self.assertFalse(relevant('Iridium chemosensor for imaging living cells'))
        self.assertFalse(relevant('Photocatalytic hydrogen evolution from covalent organic frameworks'))
        self.assertFalse(relevant('Green-to-blue triplet fusion upconversion sensitized by anisotropic CdSe nanoplatelets'))
        self.assertFalse(relevant('New photosensitizers for photodynamic therapy'))
        self.assertFalse(relevant('OLED display driving circuit with mixture of experts'))


class RecentWindowTests(unittest.TestCase):
    def test_twenty_year_window_is_inclusive_and_unknown_dates_pass(self):
        today = date(2026, 10, 18)
        self.assertTrue(recent_enough({'year': 2006}, 20, today))
        self.assertFalse(recent_enough({'year': 2005}, 20, today))
        self.assertFalse(recent_enough({'publication_date': '2006-10-17'}, 20, today))
        self.assertTrue(recent_enough({'publication_date': '2006-10-18'}, 20, today))
        self.assertTrue(recent_enough({}, 20, today))
        self.assertTrue(recent_enough({'year': 1990}, 0, today))


if __name__ == '__main__':
    unittest.main()
