import copy
import unittest

from browser.shared_page_dispatch import dispatch


def pool(count=20, state='ready_blank', kind=None):
    return {f't{i:02d}': {'state': state, 'slot': i, **({'kind': kind} if kind else {})}
            for i in range(1, count + 1)}


class SharedPageDispatch(unittest.TestCase):
    def assert_disjoint(self, plan):
        self.assertFalse(set(plan['card_targets']) & set(plan['review_targets']))
        self.assertFalse(set(plan['card_ready']) & set(plan['review_ready']))
        self.assertFalse(set(plan['protected_targets']) &
                         (set(plan['card_targets']) | set(plan['review_targets'])))

    def test_default_competing_lanes_reserve_four_review_pages(self):
        entries = pool()
        before = copy.deepcopy(entries)
        plan = dispatch(entries, entries)
        self.assertEqual(plan['budget'], {'cards': 16, 'review': 4})
        self.assertEqual(len(plan['card_ready']), 16)
        self.assertEqual(len(plan['review_ready']), 4)
        self.assert_disjoint(plan)
        self.assertEqual(entries, before)

    def test_twenty_existing_cards_drain_and_released_slot_goes_to_review(self):
        entries = pool(state='busy')
        plan = dispatch(entries, entries)
        self.assertEqual(len(plan['card_targets']), 20)
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(plan['review_ready'], [])
        self.assertEqual(plan['status']['cards'], 'draining')
        self.assertEqual(plan['status']['review'], 'waiting_slot')
        entries['t20']['state'] = 'ready'
        plan = dispatch(entries, entries)
        self.assertEqual(plan['review_ready'], ['t20'])
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(len(plan['card_targets']), 19)
        self.assert_disjoint(plan)

    def test_four_released_slots_stay_reserved_while_over_budget_cards_drain(self):
        entries = pool(state='busy')
        for tid in ('t17', 't18', 't19', 't20'):
            entries[tid]['state'] = 'ready_blank'
        plan = dispatch(entries, entries)
        self.assertEqual(plan['review_ready'], ['t17', 't18', 't19', 't20'])
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(plan['active'], {'cards': 16, 'review': 0})

    def test_unknown_verification_and_external_pages_are_never_borrowed(self):
        entries = pool()
        entries['t01']['state'] = 'needs_inspection'
        entries['t02']['verification_required'] = True
        entries['t03']['owned'] = False
        entries['t04']['submission_unknown'] = True
        entries['t05']['attempt_state'] = 'needs_inspection'
        plan = dispatch(entries, entries, excluded_targets=['t06'])
        self.assertEqual(plan['protected'], 6)
        self.assertEqual(set(plan['protected_targets']), {f't{i:02d}' for i in range(1, 7)})
        self.assertEqual(len(plan['card_targets']) + len(plan['review_targets']), 14)
        self.assert_disjoint(plan)

    def test_review_pause_lends_idle_capacity_and_keeps_active_reviews(self):
        entries = pool()
        for tid in ('t01', 't02', 't03', 't04'):
            entries[tid].update(state='busy', kind='review')
        plan = dispatch(entries, entries, review_allowed=False)
        self.assertEqual(plan['budget'], {'cards': 20, 'review': 0})
        self.assertEqual(plan['review_targets'], ['t01', 't02', 't03', 't04'])
        self.assertEqual(plan['review_ready'], [])
        self.assertEqual(len(plan['card_ready']), 16)
        self.assertEqual(plan['status']['review'], 'draining')
        self.assert_disjoint(plan)

    def test_either_idle_lane_lends_only_up_to_other_menu_limit(self):
        entries = pool()
        plan = dispatch(entries, entries, review_pending=0)
        self.assertEqual(len(plan['card_ready']), 20)
        self.assertEqual(plan['review_targets'], [])
        plan = dispatch(entries, entries, cards_pending=False, review_limit=12)
        self.assertEqual(len(plan['review_ready']), 12)
        self.assertEqual(plan['card_targets'], [])
        self.assertEqual(len(plan['unassigned_targets']), 8)
        plan = dispatch(entries, entries, cards_allowed=False, review_limit=20)
        self.assertEqual(len(plan['review_ready']), 20)

    def test_two_twenty_page_menus_share_capacity_without_starvation(self):
        entries = pool()
        plan = dispatch(entries, entries, cards_limit=20, review_limit=20)
        self.assertEqual(plan['budget'], {'cards': 10, 'review': 10})
        self.assertEqual(len(plan['card_ready']), 10)
        self.assertEqual(len(plan['review_ready']), 10)
        self.assert_disjoint(plan)

    def test_reduction_preserves_activity_and_stops_excess_new_claims(self):
        entries = pool()
        for tid in ('t01', 't02', 't03', 't04', 't05'):
            entries[tid]['state'] = 'busy'
        for tid in ('t06', 't07', 't08'):
            entries[tid].update(state='busy', kind='review')
        plan = dispatch(entries, entries, cards_limit=2, review_limit=1)
        self.assertEqual(plan['budget'], {'cards': 2, 'review': 1})
        self.assertEqual(plan['card_targets'], ['t01', 't02', 't03', 't04', 't05'])
        self.assertEqual(plan['review_targets'], ['t06', 't07', 't08'])
        self.assertEqual(plan['card_ready'] + plan['review_ready'], [])
        self.assertEqual(plan['status'], {'cards': 'draining', 'review': 'draining'})

    def test_incomplete_or_overflow_inventory_blocks_new_claims_but_keeps_activity(self):
        entries = pool()
        entries['t01'].update(state='busy', kind='review')
        plan = dispatch(entries, entries, inventory_complete=False)
        self.assertEqual(plan['review_targets'], ['t01'])
        self.assertEqual(plan['card_ready'] + plan['review_ready'], [])
        self.assertEqual(set(plan['status'].values()), {'waiting_inventory'})
        entries['extra'] = {'state': 'ready_blank'}
        plan = dispatch(entries, entries)
        self.assertTrue(plan['overflow'])
        self.assertEqual(plan['review_targets'], ['t01'])
        self.assertEqual(plan['card_ready'] + plan['review_ready'], [])

    def test_missing_history_does_not_occupy_live_slot_and_unowned_live_page_is_protected(self):
        entries = pool(2)
        entries['old'] = {'state': 'needs_inspection'}
        plan = dispatch(entries, ['t01', 't02', 'unowned'])
        self.assertEqual(plan['protected_targets'], ['unowned'])
        self.assertNotIn('old', plan['card_targets'] + plan['review_targets'])
        self.assertEqual(plan['live_slots'], 3)
        self.assert_disjoint(plan)

    def test_single_slot_can_only_be_claimed_by_one_lane(self):
        entries = pool(1)
        plan = dispatch(entries, entries, max_slots=1)
        self.assertEqual(len(plan['card_ready']) + len(plan['review_ready']), 1)
        self.assert_disjoint(plan)

    def test_idle_lane_affinity_preserves_stable_target_assignment(self):
        entries = pool()
        for tid in ('t17', 't18', 't19', 't20'):
            entries[tid]['kind'] = 'review'
        plan = dispatch(entries, entries)
        self.assertEqual(plan['review_ready'], ['t17', 't18', 't19', 't20'])
        self.assertEqual(plan, dispatch(entries, reversed(list(entries))))

    def test_invalid_controls_are_rejected(self):
        entries = pool()
        for kwargs in ({'cards_limit': True}, {'review_limit': 21}, {'max_slots': 21},
                       {'cards_pending': -1}, {'review_pending': 'yes'}):
            with self.assertRaises(ValueError):
                dispatch(entries, entries, **kwargs)


def arrivals(lane, count, first=0, step=1):
    return [{'job_id': f'{lane}-{i:02d}', 'queued_at': first + i * step, 'sequence': i}
            for i in range(count)]


class ThreeLaneFifoDispatch(unittest.TestCase):
    def plan(self, entries, queues=None, **kwargs):
        if queues is None:
            queues = {'cards': arrivals('cards', 20, 100),
                      'review': arrivals('review', 20),
                      'correction': arrivals('correction', 20, 50)}
        options = {'cards_limit': 20, 'review_limit': 20, 'correction_limit': 20,
                   'cards_min_pages': 8, 'cards_pending': len(queues.get('cards', ())),
                   'review_pending': len(queues.get('review', ())),
                   'correction_pending': len(queues.get('correction', ())),
                   'queue_heads': queues}
        options.update(kwargs)
        return dispatch(entries, entries, **options)

    def assert_safe(self, plan):
        groups = [set(plan[key]) for key in
                  ('card_targets', 'review_targets', 'correction_targets')]
        for i, group in enumerate(groups):
            self.assertFalse(group & set(plan['protected_targets']))
            for other in groups[i + 1:]:
                self.assertFalse(group & other)
        self.assertLessEqual(sum(map(len, groups)) + plan['protected'], plan['max_slots'])
        self.assertEqual(len(plan['claim_order']), sum(len(plan[key]) for key in
                         ('card_ready', 'review_ready', 'correction_ready')))

    def test_reserves_eight_cards_then_uses_oldest_arrivals_without_lane_share(self):
        entries = pool()
        plan = self.plan(entries)
        self.assertEqual(plan['budget'], {'cards': 8, 'review': 12, 'correction': 0})
        self.assertEqual([claim['lane'] for claim in plan['claim_order']],
                         ['cards'] * 8 + ['review'] * 12)
        self.assertTrue(all(claim['reserved'] for claim in plan['claim_order'][:8]))
        self.assertTrue(all(not claim['reserved'] for claim in plan['claim_order'][8:]))
        self.assertEqual(plan['cards_min_shortfall'], 0)
        self.assert_safe(plan)

    def test_correction_older_than_review_gets_all_shared_slots_after_reservation(self):
        queues = {'cards': arrivals('cards', 20, 100),
                  'review': arrivals('review', 20, 50),
                  'correction': arrivals('correction', 20)}
        plan = self.plan(pool(), queues)
        self.assertEqual(plan['budget'], {'cards': 8, 'review': 0, 'correction': 12})
        self.assertEqual(plan['review_ready'], [])
        self.assert_safe(plan)

    def test_remaining_pages_merge_individual_jobs_in_arrival_order(self):
        queues = {'cards': arrivals('cards', 20, 100),
                  'review': arrivals('review', 6, 0, 2),
                  'correction': arrivals('correction', 6, 1, 2)}
        plan = self.plan(pool(), queues)
        self.assertEqual([claim['lane'] for claim in plan['claim_order'][8:]],
                         ['review', 'correction'] * 6)
        self.assertEqual([claim['queued_at'] for claim in plan['claim_order'][8:]], list(range(12)))
        self.assert_safe(plan)

    def test_cards_also_participate_in_shared_fifo_after_their_minimum(self):
        entries = pool()
        for tid in list(entries)[:8]:
            entries[tid].update(state='busy', kind='cards')
        queues = {'cards': arrivals('cards', 1, 1),
                  'review': arrivals('review', 1, 3),
                  'correction': arrivals('correction', 1, 2)}
        plan = self.plan(entries, queues)
        self.assertEqual([claim['lane'] for claim in plan['claim_order']],
                         ['cards', 'correction', 'review'])
        self.assertFalse(any(claim['reserved'] for claim in plan['claim_order']))
        self.assertEqual(len(plan['unassigned_targets']), 9)
        self.assert_safe(plan)

    def test_existing_cards_count_towards_reservation(self):
        entries = pool()
        for tid in list(entries)[:3]:
            entries[tid]['state'] = 'busy'
        plan = self.plan(entries)
        self.assertEqual(plan['active']['cards'], 3)
        self.assertEqual(len(plan['card_ready']), 5)
        self.assertEqual(len(plan['review_ready']), 12)
        self.assertEqual(len(plan['card_targets']), 8)
        self.assert_safe(plan)

    def test_adjustable_minimum_only_changes_new_allocation(self):
        entries = pool()
        plan = self.plan(entries, cards_min_pages=12)
        self.assertEqual(plan['budget'], {'cards': 12, 'review': 8, 'correction': 0})
        plan = self.plan(entries, cards_min_pages=4)
        self.assertEqual(plan['budget'], {'cards': 4, 'review': 16, 'correction': 0})
        self.assert_safe(plan)

    def test_increasing_minimum_waits_for_activity_to_finish(self):
        entries = pool()
        for tid in list(entries)[:2]:
            entries[tid]['state'] = 'busy'
        for tid in list(entries)[2:12]:
            entries[tid].update(state='busy', kind='review')
        plan = self.plan(entries, cards_min_pages=12)
        self.assertEqual(len(plan['review_targets']), 10)
        self.assertEqual(len(plan['card_ready']), 8)
        self.assertEqual(plan['cards_min_shortfall'], 2)
        entries['t03']['state'] = entries['t04']['state'] = 'ready'
        plan = self.plan(entries, cards_min_pages=12)
        self.assertEqual(len(plan['card_targets']), 12)
        self.assertEqual(len(plan['review_targets']), 8)
        self.assertEqual(plan['cards_min_shortfall'], 0)
        self.assert_safe(plan)

    def test_less_real_card_work_lends_surplus_without_inventing_jobs(self):
        queues = {'cards': arrivals('cards', 3, 100),
                  'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(pool(), queues)
        self.assertEqual(plan['budget'], {'cards': 3, 'review': 17, 'correction': 0})
        self.assertEqual(plan['cards_min_shortfall'], 5)
        self.assertEqual({claim['job_id'] for claim in plan['claim_order'][:3]},
                         {job['job_id'] for job in queues['cards']})
        self.assert_safe(plan)

    def test_empty_or_paused_cards_lend_only_idle_pages(self):
        entries = pool()
        for tid in list(entries)[:3]:
            entries[tid]['state'] = 'busy'
        plan = self.plan(entries, cards_allowed=False)
        self.assertEqual(plan['card_targets'], ['t01', 't02', 't03'])
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(len(plan['review_ready']), 17)
        self.assertEqual(plan['cards_reservation'], 0)
        self.assertEqual(plan['status']['cards'], 'draining')
        self.assert_safe(plan)
        queues = {'cards': [], 'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(pool(), queues)
        self.assertEqual(len(plan['review_ready']), 20)
        self.assertEqual(plan['status']['cards'], 'idle')

    def test_each_lane_pause_is_independent_and_preserves_activity(self):
        entries = pool()
        entries['t01'].update(state='busy', kind='review')
        entries['t02'].update(state='busy', kind='correction')
        plan = self.plan(entries, review_allowed=False)
        self.assertEqual(plan['review_targets'], ['t01'])
        self.assertEqual(plan['review_ready'], [])
        self.assertEqual(len(plan['card_ready']), 8)
        self.assertEqual(len(plan['correction_ready']), 10)
        self.assertEqual(plan['status']['review'], 'draining')
        self.assert_safe(plan)
        plan = self.plan(entries, correction_allowed=False)
        self.assertEqual(plan['correction_targets'], ['t02'])
        self.assertEqual(plan['correction_ready'], [])
        self.assertEqual(len(plan['review_ready']), 10)
        self.assert_safe(plan)

    def test_menu_reduction_drains_all_three_lanes_without_cancellation(self):
        entries = pool()
        for tid in list(entries)[:5]:
            entries[tid]['state'] = 'busy'
        for tid in list(entries)[5:10]:
            entries[tid].update(state='busy', kind='review')
        for tid in list(entries)[10:15]:
            entries[tid].update(state='busy', kind='correction')
        plan = self.plan(entries, cards_limit=2, review_limit=2, correction_limit=2,
                         cards_min_pages=2)
        self.assertEqual(plan['active'], {'cards': 5, 'review': 5, 'correction': 5})
        self.assertEqual(plan['budget'], {'cards': 2, 'review': 2, 'correction': 2})
        self.assertEqual(set(plan['status'].values()), {'draining'})
        self.assertEqual(plan['claim_order'], [])
        self.assertEqual(len(plan['unassigned_targets']), 5)
        self.assert_safe(plan)

    def test_saturated_lane_does_not_block_older_eligible_other_lane(self):
        entries = pool()
        for tid in list(entries)[:4]:
            entries[tid].update(state='busy', kind='review')
        plan = self.plan(entries, review_limit=4)
        self.assertEqual(plan['budget'], {'cards': 8, 'review': 4, 'correction': 8})
        self.assertEqual(len(plan['correction_ready']), 8)
        self.assertEqual(plan['review_ready'], [])
        self.assert_safe(plan)

    def test_protected_pages_can_make_the_card_minimum_unreachable(self):
        entries = pool()
        for tid in list(entries)[:15]:
            entries[tid]['state'] = 'needs_inspection'
        plan = self.plan(entries)
        self.assertEqual(plan['protected'], 15)
        self.assertEqual(len(plan['card_ready']), 5)
        self.assertEqual(plan['review_ready'] + plan['correction_ready'], [])
        self.assertEqual(plan['cards_min_shortfall'], 3)
        self.assert_safe(plan)

    def test_ready_labels_never_override_unknown_draft_or_validation_evidence(self):
        entries = pool()
        flags = [{'draft_text': 'user draft'}, {'attachments': ['a.zip']},
                 {'verification_required': True}, {'submission_unknown': True},
                 {'owned': False}, {'attempt_state': 'needs_inspection'},
                 {'repair_in_progress': True}, {'kind': 'foreign'}]
        for tid, flag in zip(entries, flags):
            entries[tid].update(flag)
        plan = self.plan(entries, excluded_targets=['t09'])
        self.assertEqual(plan['protected_targets'], [f't{i:02d}' for i in range(1, 10)])
        self.assert_safe(plan)

    def test_incomplete_inventory_or_overflow_preserves_all_original_activity(self):
        entries = pool()
        entries['t01'].update(state='busy', kind='correction')
        plan = self.plan(entries, inventory_complete=False)
        self.assertEqual(plan['correction_targets'], ['t01'])
        self.assertEqual(plan['claim_order'], [])
        self.assertEqual(set(plan['status'].values()), {'waiting_inventory'})
        entries['extra'] = {'state': 'ready_blank'}
        plan = self.plan(entries)
        self.assertTrue(plan['overflow'])
        self.assertEqual(plan['claim_order'], [])
        self.assertEqual(plan['correction_targets'], ['t01'])

    def test_missing_arrival_evidence_prevents_new_claims_instead_of_guessing_fifo(self):
        entries = pool()
        entries['t01'].update(state='busy', kind='review')
        plan = self.plan(entries, queue_heads=None)
        self.assertFalse(plan['queue_metadata_complete'])
        self.assertEqual(plan['claim_order'], [])
        self.assertEqual(plan['review_targets'], ['t01'])
        self.assertEqual(set(plan['status'].values()), {'waiting_queue'})

    def test_equal_timestamp_uses_global_sequence_and_stable_job_id(self):
        entries = pool()
        for tid in list(entries)[:8]:
            entries[tid]['state'] = 'busy'
        queues = {'cards': [{'job_id': 'card-next', 'queued_at': 10, 'sequence': 3}],
                  'review': [{'job_id': 'review-next', 'queued_at': 10, 'sequence': 1}],
                  'correction': [{'job_id': 'correction-next', 'queued_at': 10, 'sequence': 2}]}
        plan = self.plan(entries, queues)
        self.assertEqual([claim['lane'] for claim in plan['claim_order']],
                         ['review', 'correction', 'cards'])
        self.assert_safe(plan)

    def test_iso_timestamp_and_unix_timestamp_share_one_order(self):
        queues = {'cards': arrivals('cards', 8, 100),
                  'review': [{'job_id': 'r', 'queued_at': '1970-01-01T08:00:02+08:00'}],
                  'correction': [{'job_id': 'c', 'queued_at': 1}]}
        plan = self.plan(pool(), queues)
        self.assertEqual([claim['job_id'] for claim in plan['claim_order'][8:]], ['c', 'r'])
        self.assertEqual(plan['ready_jobs'][plan['correction_ready'][0]]['queued_at'], 1)

    def test_entry_affinity_changes_target_choice_without_changing_job_order(self):
        entries = pool()
        for tid in list(entries)[8:]:
            entries[tid]['kind'] = 'correction'
        queues = {'cards': arrivals('cards', 8, 100), 'review': arrivals('review', 1, 1),
                  'correction': arrivals('correction', 1)}
        plan = self.plan(entries, queues)
        self.assertEqual(plan['card_ready'], [f't{i:02d}' for i in range(1, 9)])
        self.assertEqual(plan['correction_ready'], ['t09'])
        self.assertEqual(plan['review_ready'], ['t10'])
        self.assertEqual([claim['lane'] for claim in plan['claim_order'][8:]],
                         ['correction', 'review'])

    def test_no_input_mutation_and_repeat_plan_is_stable(self):
        entries = pool()
        queues = {'cards': arrivals('cards', 20, 100),
                  'review': arrivals('review', 20), 'correction': arrivals('correction', 20, 50)}
        before_entries, before_queues = copy.deepcopy(entries), copy.deepcopy(queues)
        first = self.plan(entries, queues)
        second = self.plan(dict(reversed(list(entries.items()))), queues)
        self.assertEqual(first, second)
        self.assertEqual(entries, before_entries)
        self.assertEqual(queues, before_queues)
        self.assert_safe(first)

    def test_lower_maximum_does_not_falsely_claim_the_configured_minimum(self):
        plan = self.plan(pool(), cards_limit=4)
        self.assertEqual(len(plan['card_targets']), 4)
        self.assertEqual(plan['cards_min_pages'], 8)
        self.assertEqual(plan['cards_reservation'], 4)
        self.assertEqual(plan['cards_min_shortfall'], 4)
        self.assert_safe(plan)

    def test_pending_count_does_not_create_more_jobs_than_received(self):
        queues = {'cards': arrivals('cards', 2, 100),
                  'review': arrivals('review', 2), 'correction': arrivals('correction', 2, 50)}
        plan = self.plan(pool(), queues, cards_pending=1)
        self.assertEqual(len(plan['card_ready']), 1)
        self.assertEqual(len(plan['claim_order']), 5)
        self.assertEqual(len(plan['unassigned_targets']), 15)
        self.assert_safe(plan)

    def test_invalid_arrival_and_controls_are_rejected_even_on_paused_lane(self):
        entries = pool()
        for options in ({'cards_min_pages': 0}, {'cards_min_pages': True},
                        {'correction_limit': 21}, {'correction_pending': -1},
                        {'cards_pending': 'yes', 'cards_allowed': False}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.plan(entries, **options)
        for record in ({'job_id': 'r'}, {'job_id': 'r', 'queued_at': True},
                       {'job_id': 'r', 'queued_at': float('nan')},
                       {'job_id': 'r', 'queued_at': 'not a timestamp'},
                       {'job_id': 'r', 'queued_at': 1, 'sequence': True}):
            queues = {'cards': arrivals('cards', 8), 'review': [record], 'correction': []}
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.plan(entries, queues)

    def test_all_minimum_and_maximum_combinations_obey_bounds(self):
        for minimum in range(1, 21):
            for review_max in range(1, 21):
                with self.subTest(minimum=minimum, review_max=review_max):
                    plan = self.plan(pool(), cards_min_pages=minimum, review_limit=review_max)
                    self.assertGreaterEqual(len(plan['card_ready']), minimum)
                    self.assertLessEqual(len(plan['review_ready']), review_max)
                    self.assertEqual(len(plan['claim_order']), 20)
                    self.assert_safe(plan)

    def test_fixed_card_reservation_is_held_when_queue_is_empty(self):
        queues = {'cards': [], 'review': arrivals('review', 20),
                  'correction': arrivals('correction', 20, 50)}
        plan = self.plan(pool(), queues, hold_card_reservation=True)
        self.assertEqual(plan['reserved_idle_targets'], [f't{i:02d}' for i in range(1, 9)])
        self.assertEqual(plan['card_targets'], plan['reserved_idle_targets'])
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(plan['budget'], {'cards': 8, 'review': 12, 'correction': 0})
        self.assertEqual(plan['reserved_capacity'], 8)
        self.assertEqual(plan['cards_min_shortfall'], 0)
        self.assertEqual(plan['status']['cards'], 'idle')
        self.assertEqual([claim['lane'] for claim in plan['claim_order']], ['review'] * 12)
        self.assert_safe(plan)

    def test_fixed_reservation_keeps_unprepared_card_capacity_without_fake_claims(self):
        entries = pool()
        entries['t01']['state'] = entries['t02']['state'] = 'busy'
        queues = {'cards': [], 'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(entries, queues, hold_card_reservation=True)
        self.assertEqual(plan['active']['cards'], 2)
        self.assertEqual(len(plan['reserved_idle_targets']), 6)
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(len(plan['review_ready']), 12)
        self.assertFalse(any(job['lane'] == 'cards' for job in plan['ready_jobs'].values()))
        self.assert_safe(plan)

    def test_fixed_reservation_holds_surplus_when_fewer_than_eight_cards_are_ready(self):
        queues = {'cards': arrivals('cards', 3, 100),
                  'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(pool(), queues, hold_card_reservation=True)
        self.assertEqual(len(plan['card_ready']), 3)
        self.assertEqual(len(plan['reserved_idle_targets']), 5)
        self.assertEqual(len(plan['card_targets']), 8)
        self.assertEqual(len(plan['review_ready']), 12)
        self.assertEqual(plan['cards_min_shortfall'], 0)
        self.assertEqual(len(plan['claim_order']), 15)
        self.assert_safe(plan)

    def test_card_pause_lends_fixed_idle_reservation_but_keeps_active_cards(self):
        entries = pool()
        entries['t01']['state'] = entries['t02']['state'] = 'busy'
        plan = self.plan(entries, hold_card_reservation=True, cards_allowed=False)
        self.assertEqual(plan['card_targets'], ['t01', 't02'])
        self.assertEqual(plan['reserved_idle_targets'], [])
        self.assertEqual(plan['reserved_capacity'], 0)
        self.assertEqual(len(plan['review_ready']), 18)
        self.assert_safe(plan)

    def test_protected_pages_reduce_fixed_reservation_without_false_capacity(self):
        entries = pool()
        for tid in list(entries)[:15]:
            entries[tid]['state'] = 'needs_inspection'
        queues = {'cards': [], 'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(entries, queues, hold_card_reservation=True)
        self.assertEqual(len(plan['reserved_idle_targets']), 5)
        self.assertEqual(plan['reserved_capacity'], 5)
        self.assertEqual(plan['cards_min_shortfall'], 3)
        self.assertEqual(plan['claim_order'], [])
        self.assert_safe(plan)

    def test_finished_review_page_fills_fixed_reservation_before_shared_fifo(self):
        entries = pool(kind='review', state='busy')
        queues = {'cards': [], 'review': arrivals('review', 20), 'correction': []}
        plan = self.plan(entries, queues, hold_card_reservation=True)
        self.assertEqual(plan['cards_min_shortfall'], 8)
        self.assertEqual(len(plan['review_targets']), 20)
        self.assertEqual(plan['reserved_idle_targets'], [])
        entries['t20']['state'] = 'ready'
        plan = self.plan(entries, queues, hold_card_reservation=True)
        self.assertEqual(plan['reserved_idle_targets'], ['t20'])
        self.assertEqual(plan['cards_min_shortfall'], 7)
        self.assertEqual(len(plan['review_targets']), 19)
        self.assertEqual(plan['claim_order'], [])
        self.assert_safe(plan)

    def test_adjustable_fixed_minimum_is_independent_of_current_card_queue(self):
        queues = {'cards': [], 'review': arrivals('review', 20), 'correction': []}
        for minimum in (1, 8, 12, 20):
            with self.subTest(minimum=minimum):
                plan = self.plan(pool(), queues, cards_min_pages=minimum, hold_card_reservation=True)
                self.assertEqual(len(plan['reserved_idle_targets']), minimum)
                self.assertEqual(len(plan['review_ready']), 20 - minimum)
                self.assertEqual(plan['reserved_capacity'], minimum)
                self.assert_safe(plan)

    def test_invalid_reservation_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(pool(), hold_card_reservation='yes')


if __name__ == '__main__':
    unittest.main()
