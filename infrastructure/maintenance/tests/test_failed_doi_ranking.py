"""Journal level + failed-count ranking tests."""
import unittest

from infrastructure.maintenance.sync_failed_dois import journal_level, load_levels, normalize_journal, rank_journals


class JournalRankingTests(unittest.TestCase):
    def levels(self):
        return {'levels': {normalize_journal('Nature'): 5, normalize_journal('Big Journal'): 1},
                'aliases': {normalize_journal('NATURE'): normalize_journal('Nature')},
                'default': 1, 'max_level': 5, 'level_weight': 0.75, 'source': 'fixture'}

    def test_high_level_beats_high_failure_count_when_weight_is_75_percent(self):
        groups = {'Nature': {'10.1000/a'}, 'Big Journal': {'10.1000/b%d' % i for i in range(200)}}
        ranked = rank_journals(groups, self.levels())
        self.assertEqual(ranked[0]['journal'], 'Nature')
        self.assertGreater(ranked[0]['score'], ranked[1]['score'])

    def test_count_breaks_ties_within_same_level(self):
        levels = self.levels()
        levels['levels'][normalize_journal('Other')] = 5
        groups = {'Nature': {'10.1000/a'}, 'Other': {'10.1000/b', '10.1000/c'}}
        ranked = rank_journals(groups, levels)
        self.assertEqual([row['journal'] for row in ranked], ['Other', 'Nature'])

    def test_alias_and_html_entity_are_normalized(self):
        self.assertEqual(journal_level('NATURE', self.levels()), 5)
        self.assertEqual(normalize_journal('ACS Applied Materials &amp; Interfaces'),
                         normalize_journal('ACS Applied Materials & Interfaces'))

    def test_shipped_levels_are_loaded(self):
        levels = load_levels('infrastructure/config/journal-levels.json')
        self.assertEqual(levels['level_weight'], 0.75)
        self.assertGreaterEqual(journal_level('Nature Photonics', levels), 5)


if __name__ == '__main__':
    unittest.main()
