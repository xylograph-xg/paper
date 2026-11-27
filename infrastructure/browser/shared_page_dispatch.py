"""Pure allocation of the keeper's fixed pages between independent task lanes.

The caller supplies live target IDs already restricted to the dedicated window.
Only ``ready``/``ready_blank`` pages can be assigned. Existing activity stays with
its original lane, including activity above a newly reduced concurrency limit.
This module neither changes entries nor inspects, creates or navigates pages.
"""
from collections.abc import Mapping
from datetime import datetime, timezone
import math


MAX_SLOTS = 20
READY_STATES = frozenset(('ready', 'ready_blank'))
ACTIVE_STATES = frozenset(('busy', 'submitting', 'submitted', 'collecting', 'submission_started'))
UNKNOWN_STATES = frozenset(('needs_inspection', 'unknown', 'submission_unknown', 'needs_user'))
LANES = ('cards', 'review', 'correction')


def _limit(value, name, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(name + ' must be an integer between 0 and ' + str(maximum))
    return value


def _pending(value, name):
    if type(value) is bool:
        return value
    if type(value) is int and value >= 0:
        return value > 0
    raise ValueError(name + ' must be a boolean or nonnegative integer')


def _budgets(capacity, cards, review):
    if cards + review <= capacity:
        return {'cards': cards, 'review': review}
    if not cards:
        return {'cards': 0, 'review': min(review, capacity)}
    if not review:
        return {'cards': min(cards, capacity), 'review': 0}
    # Round review's proportional share up: cards=20/review=4 reserves four of
    # twenty pages, while cards=20/review=20 gives each lane ten pages.
    review_budget = min(review, (capacity * review + cards + review - 1) // (cards + review))
    if capacity >= 2:
        review_budget = min(review_budget, capacity - 1)
    return {'cards': min(cards, capacity - review_budget), 'review': review_budget}


def _legacy_dispatch(entries, live_targets, *, cards_limit=20, review_limit=4,
             cards_pending=True, review_pending=True,
             cards_allowed=True, review_allowed=True, max_slots=20,
             inventory_complete=True, excluded_targets=()):
    """Return disjoint lane targets and read-only allocation diagnostics.

    ``entries`` uses the keeper's existing per-target ``state`` and ``kind``
    (``review`` or absent/``card``/``cards``) records. Unknown/missing records,
    explicit unknown submission or verification flags, unowned pages, and
    ``excluded_targets`` are protected and never assigned. Historical targets
    absent from ``live_targets`` do not occupy a current slot.

    Limits are menu maxima, not promises to run that many jobs. With both lanes
    runnable, their combined budget fits the nonprotected twenty-slot pool.
    A lane without pending work or permission lends only its *idle* slots;
    already active pages remain in its lane. Incomplete/overflow inventory
    prevents new allocation without dropping existing activity.

    ``card_targets``/``review_targets`` contain original active pages followed
    by each lane's exclusively allocated idle pages. ``card_ready`` and
    ``review_ready`` identify the only targets eligible for new claims. The
    caller must still recheck page/attempt evidence under the submission lock.
    """
    if type(max_slots) is not int or not 1 <= max_slots <= MAX_SLOTS:
        raise ValueError('max_slots must be an integer between 1 and 20')
    cards_limit = _limit(cards_limit, 'cards_limit', MAX_SLOTS)
    review_limit = _limit(review_limit, 'review_limit', MAX_SLOTS)
    demand = {
        'cards': bool(cards_allowed) and _pending(cards_pending, 'cards_pending') and cards_limit > 0,
        'review': bool(review_allowed) and _pending(review_pending, 'review_pending') and review_limit > 0,
    }
    excluded = set(excluded_targets)
    targets = set(live_targets)
    if not all(isinstance(t, str) and t for t in targets):
        raise ValueError('live_targets must contain nonempty target IDs')

    def order(tid):
        entry = entries.get(tid, {})
        slot = entry.get('slot') if isinstance(entry, Mapping) else None
        return (slot if type(slot) is int else MAX_SLOTS + 1, tid)

    active = {'cards': [], 'review': []}
    idle = []
    protected = []
    for tid in sorted(targets, key=order):
        entry = entries.get(tid)
        if not isinstance(entry, Mapping):
            protected.append(tid)
            continue
        state = entry.get('state')
        kind = entry.get('kind')
        if (tid in excluded or entry.get('owned') is False or
                entry.get('eligible') is False or entry.get('external') or
                entry.get('submission_unknown') or entry.get('verification_required') or
                entry.get('ledger_state') in UNKNOWN_STATES or
                entry.get('attempt_state') in UNKNOWN_STATES or
                kind not in (None, 'card', 'cards', 'review')):
            protected.append(tid)
        elif state in ACTIVE_STATES:
            active['review' if kind == 'review' else 'cards'].append(tid)
        elif state in READY_STATES:
            idle.append(tid)
        else:
            protected.append(tid)

    capacity = max(0, max_slots - len(protected))
    budget = _budgets(capacity, cards_limit if demand['cards'] else 0,
                      review_limit if demand['review'] else 0)
    ready = {'cards': [], 'review': []}
    overflow = len(targets) > max_slots
    if inventory_complete and not overflow:
        remaining = max(0, capacity - sum(len(v) for v in active.values()))
        # Reserve review's shortage before cards can reacquire a just-freed
        # page. This drains an already full twenty-card pool into 16 + 4.
        for lane in ('review', 'cards'):
            count = min(max(0, budget[lane] - len(active[lane])), remaining, len(idle))
            preferred = sorted(idle, key=lambda tid: (
                (entries[tid].get('kind') == 'review') != (lane == 'review'), order(tid)))
            ready[lane] = preferred[:count]
            allocated = set(ready[lane])
            idle = [tid for tid in idle if tid not in allocated]
            remaining -= count

    def status(lane, allowed, pending):
        if not inventory_complete:
            return 'waiting_inventory'
        if overflow:
            return 'waiting_capacity'
        if not allowed:
            return 'draining' if active[lane] else 'paused'
        if not _pending(pending, lane + '_pending'):
            return 'draining' if active[lane] else 'idle'
        if len(active[lane]) > budget[lane]:
            return 'draining'
        if ready[lane]:
            return 'ready'
        if active[lane]:
            return 'running' if len(active[lane]) == budget[lane] else 'waiting_slot'
        return 'waiting_slot'

    return {
        'card_targets': active['cards'] + ready['cards'],
        'review_targets': active['review'] + ready['review'],
        'card_ready': ready['cards'], 'review_ready': ready['review'],
        'budget': budget,
        'active': {lane: len(value) for lane, value in active.items()},
        'status': {'cards': status('cards', cards_allowed, cards_pending),
                   'review': status('review', review_allowed, review_pending)},
        'protected': len(protected), 'protected_targets': protected,
        'unassigned_targets': idle, 'capacity': capacity,
        'live_slots': len(targets), 'max_slots': max_slots,
        'inventory_complete': bool(inventory_complete), 'overflow': overflow,
    }


def _arrival(value):
    """Normalize a persisted queue arrival; never substitute an update time."""
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            value = stamp.timestamp()
        except ValueError as exc:
            raise ValueError('queued_at must be a persisted timestamp') from exc
    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise ValueError('queued_at must be a finite nonnegative timestamp')
    return value


def _queue_records(queue_heads, pending):
    if queue_heads is None:
        return {lane: [] for lane in LANES}
    if not isinstance(queue_heads, Mapping) or set(queue_heads) - set(LANES):
        raise ValueError('queue_heads must map cards, review and correction to queued jobs')
    queues = {}
    for lane in LANES:
        records = queue_heads.get(lane, ())
        if not isinstance(records, (list, tuple)):
            raise ValueError('queue_heads values must be lists of queued jobs')
        normalized, seen = [], set()
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError('queued jobs must be records')
            job_id = record.get('job_id', record.get('id', record.get('paper_id')))
            if not isinstance(job_id, str) or not job_id or job_id in seen:
                raise ValueError('queued job IDs must be nonempty and unique within their lane')
            seen.add(job_id)
            sequence = record.get('sequence', 0)
            if type(sequence) is not int or sequence < 0:
                raise ValueError('queue sequence must be a nonnegative integer')
            normalized.append({**record, 'job_id': job_id,
                'queued_at': _arrival(record.get('queued_at')), 'sequence': sequence})
        normalized.sort(key=lambda job: (job['queued_at'], job['sequence'], job['job_id']))
        count = pending[lane]
        queues[lane] = normalized if type(count) is bool and count else normalized[:count] if type(count) is int else []
    return queues


def _fifo_dispatch(entries, live_targets, *, cards_limit, review_limit,
                   correction_limit, cards_pending, review_pending,
                   correction_pending, cards_allowed, review_allowed,
                   correction_allowed, cards_min_pages, queue_heads,
                   max_slots, inventory_complete, excluded_targets,
                   hold_card_reservation):
    if type(max_slots) is not int or not 1 <= max_slots <= MAX_SLOTS:
        raise ValueError('max_slots must be an integer between 1 and 20')
    cards_min_pages = _limit(cards_min_pages, 'cards_min_pages', MAX_SLOTS)
    if cards_min_pages == 0:
        raise ValueError('cards_min_pages must be an integer between 1 and 20')
    if type(hold_card_reservation) is not bool:
        raise ValueError('hold_card_reservation must be a boolean')
    limits = {lane: _limit(value, lane + '_limit', MAX_SLOTS) for lane, value in
              zip(LANES, (cards_limit, review_limit, correction_limit))}
    pending = dict(zip(LANES, (cards_pending, review_pending, correction_pending)))
    allowed = dict(zip(LANES, (cards_allowed, review_allowed, correction_allowed)))
    has_pending = {lane: _pending(pending[lane], lane + '_pending') for lane in LANES}
    demand = {lane: bool(allowed[lane]) and has_pending[lane]
              and limits[lane] > 0 for lane in LANES}
    queues = _queue_records(queue_heads, pending)
    queue_complete = all(not demand[lane] or queues[lane] for lane in LANES)
    targets = set(live_targets)
    if not all(isinstance(t, str) and t for t in targets):
        raise ValueError('live_targets must contain nonempty target IDs')
    excluded = set(excluded_targets)

    def order(tid):
        entry = entries.get(tid, {})
        slot = entry.get('slot') if isinstance(entry, Mapping) else None
        return (slot if type(slot) is int else MAX_SLOTS + 1, tid)

    def lane_for(entry):
        return {'card': 'cards', 'cards': 'cards', None: 'cards',
                'review': 'review', 'correction': 'correction'}.get(entry.get('kind'))

    active = {lane: [] for lane in LANES}
    ready = {lane: [] for lane in LANES}
    idle, protected = [], []
    for tid in sorted(targets, key=order):
        entry = entries.get(tid)
        if not isinstance(entry, Mapping):
            protected.append(tid)
            continue
        lane = lane_for(entry)
        if (tid in excluded or lane is None or entry.get('owned') is False or
                entry.get('eligible') is False or entry.get('external') or
                entry.get('submission_unknown') or entry.get('verification_required') or
                entry.get('ledger_state') in UNKNOWN_STATES or
                entry.get('attempt_state') in UNKNOWN_STATES or
                entry.get('draft') or entry.get('has_draft') or entry.get('draft_text') or
                entry.get('attachments') or entry.get('uploading') or
                entry.get('repair_in_progress')):
            protected.append(tid)
        elif entry.get('state') in ACTIVE_STATES:
            active[lane].append(tid)
        elif entry.get('state') in READY_STATES:
            idle.append(tid)
        else:
            protected.append(tid)

    capacity = max(0, max_slots - len(protected))
    overflow = len(targets) > max_slots
    reserve_cards = bool(cards_allowed) and cards_limit > 0 and (hold_card_reservation or demand['cards'])
    reservation = min(cards_min_pages, cards_limit) if reserve_cards else 0
    claim_order, ready_jobs = [], {}
    held = []

    def assign(lane, job, reserved=False):
        # Page affinity only selects a page for the already selected FIFO job.
        # It never changes which lane/job reaches the next shared slot.
        tid = min(idle, key=lambda target: (lane_for(entries[target]) != lane, order(target)))
        idle.remove(tid)
        ready[lane].append(tid)
        ready_jobs[tid] = {**job, 'lane': lane}
        claim_order.append({'lane': lane, 'target_id': tid, 'job_id': job['job_id'],
            'queued_at': job['queued_at'], 'sequence': job['sequence'], 'reserved': reserved})

    if inventory_complete and not overflow:
        remaining = min(len(idle), max(0, capacity - sum(map(len, active.values()))))
        # An active card already occupies one reserved slot. Demand smaller
        # than the minimum uses only real jobs; the surplus can be borrowed.
        reserve_count = min(max(0, reservation - len(active['cards'])),
                            len(queues['cards']) if demand['cards'] and queue_complete else 0, remaining)
        for _ in range(reserve_count):
            assign('cards', queues['cards'].pop(0), reserved=True)
            remaining -= 1
        if hold_card_reservation:
            for _ in range(min(max(0, reservation - len(active['cards']) - len(ready['cards'])), remaining)):
                tid = min(idle, key=lambda target: (lane_for(entries[target]) != 'cards', order(target)))
                idle.remove(tid)
                held.append(tid)
                remaining -= 1
        merged = sorted(((job['queued_at'], job['sequence'], job['job_id'], lane, job)
                         for lane in LANES if demand[lane] and queue_complete for job in queues[lane]),
                        key=lambda row: row[:4])
        for _, _, _, lane, job in merged:
            if remaining <= 0:
                break
            if len(active[lane]) + len(ready[lane]) >= limits[lane]:
                continue
            assign(lane, job)
            remaining -= 1

    # Budgets describe this allocation, never an invented proportional share.
    # Activity above a menu maximum is retained separately and drains safely.
    budgets = {lane: min(limits[lane], len(active[lane]) + len(ready[lane]))
               if demand[lane] else 0 for lane in LANES}
    if hold_card_reservation and reserve_cards:
        budgets['cards'] = min(cards_limit, len(active['cards']) + len(ready['cards']) + len(held))

    def status(lane):
        if not inventory_complete:
            return 'waiting_inventory'
        if overflow:
            return 'waiting_capacity'
        if not allowed[lane]:
            return 'draining' if active[lane] else 'paused'
        if not _pending(pending[lane], lane + '_pending') or limits[lane] == 0:
            return 'draining' if active[lane] else 'idle'
        if len(active[lane]) > limits[lane]:
            return 'draining'
        if not queue_complete:
            return 'waiting_queue'
        if ready[lane]:
            return 'ready'
        return 'running' if active[lane] else 'waiting_slot'

    occupied_cards = len(active['cards']) + len(ready['cards']) + len(held)
    return {
        'card_targets': active['cards'] + ready['cards'] + held,
        'review_targets': active['review'] + ready['review'],
        'correction_targets': active['correction'] + ready['correction'],
        'card_ready': ready['cards'], 'review_ready': ready['review'],
        'correction_ready': ready['correction'], 'claim_order': claim_order,
        'ready_jobs': ready_jobs, 'policy': 'cards_minimum_then_fifo',
        'cards_min_pages': cards_min_pages, 'cards_reservation': reservation,
        'hold_card_reservation': hold_card_reservation,
        'reserved_idle_targets': held, 'reserved_capacity': min(reservation, occupied_cards),
        'cards_min_shortfall': max(0, (cards_min_pages if reserve_cards else 0) - occupied_cards),
        'budget': budgets, 'active': {lane: len(active[lane]) for lane in LANES},
        'status': {lane: status(lane) for lane in LANES},
        'protected': len(protected), 'protected_targets': protected,
        'unassigned_targets': idle, 'capacity': capacity,
        'live_slots': len(targets), 'max_slots': max_slots,
        'inventory_complete': bool(inventory_complete), 'overflow': overflow,
        'queue_metadata_complete': bool(queue_complete),
    }


def dispatch(entries, live_targets, *, cards_limit=20, review_limit=4,
             cards_pending=True, review_pending=True, cards_allowed=True,
             review_allowed=True, max_slots=20, inventory_complete=True,
             excluded_targets=(), correction_limit=0, correction_pending=False,
             correction_allowed=True, cards_min_pages=None, queue_heads=None,
             hold_card_reservation=False):
    """Allocate idle pages without moving or resending existing activity.

    New owners explicitly pass ``cards_min_pages`` and ``queue_heads`` to share
    pages between cards, review and correction. ``queue_heads`` is a mapping
    from those lane names to *all currently runnable, unsent* jobs. Each job
    contains ``job_id``, immutable ``queued_at`` (Unix seconds or ISO time),
    and optional immutable ``sequence`` for equal-time arrivals. Caller-side
    packet readiness, pause and request evidence checks must precede inclusion.

    First fill the runnable cards lane's minimum, capped by its menu maximum
    and real pending jobs. Then merge all remaining jobs by arrival time and
    sequence. Empty/paused lanes and a lane with too little runnable work lend
    idle pages. Active/unknown/draft pages are never borrowed, even after a
    lower maximum/minimum. ``cards_min_shortfall`` reports when existing
    activity, protected pages, a lower maximum or insufficient real work prevent
    the requested minimum being reached.

    The main fixed-window owner sets ``hold_card_reservation=True``. This keeps
    the cards minimum reserved even while its inputs are being prepared or its
    queue is empty. ``reserved_idle_targets`` are included in ``card_targets``
    but never in ``card_ready``/``claim_order``: they are available card slots,
    not invented jobs. Review/correction can use only surplus idle capacity.
    Explicitly pausing cards lends those idle slots; existing work still stays.

    ``claim_order`` is the submission order the owner must follow, and
    ``ready_jobs`` binds each allocation to its chosen job. A caller must not
    replace this with separate review-first/card-first claim loops. Missing
    queue arrival metadata prevents new allocations instead of inventing FIFO
    history. Limits remain per-lane maxima, and the total stays within 20.

    Old callers supplying no new arguments retain the legacy two-lane API and
    its proportional allocation. This compatibility path is never used by the
    new three-lane owner. The module performs no I/O or mutation.
    """
    if (cards_min_pages is None and queue_heads is None and correction_limit == 0 and
            not correction_pending and hold_card_reservation is False):
        return _legacy_dispatch(entries, live_targets, cards_limit=cards_limit,
            review_limit=review_limit, cards_pending=cards_pending,
            review_pending=review_pending, cards_allowed=cards_allowed,
            review_allowed=review_allowed, max_slots=max_slots,
            inventory_complete=inventory_complete, excluded_targets=excluded_targets)
    return _fifo_dispatch(entries, live_targets, cards_limit=cards_limit,
        review_limit=review_limit, correction_limit=correction_limit,
        cards_pending=cards_pending, review_pending=review_pending,
        correction_pending=correction_pending, cards_allowed=cards_allowed,
        review_allowed=review_allowed, correction_allowed=correction_allowed,
        cards_min_pages=8 if cards_min_pages is None else cards_min_pages,
        queue_heads=queue_heads, max_slots=max_slots,
        inventory_complete=inventory_complete, excluded_targets=excluded_targets,
        hold_card_reservation=hold_card_reservation)
