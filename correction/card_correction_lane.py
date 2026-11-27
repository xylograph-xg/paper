"""Correction bookkeeping on the single shared browser owner's event loop.

Source reworks are sent by the existing source-only card transport. This lane
does not create a second CDP connection, uploader, submit lock or worker service.
"""
import json

from core.api import catalog__Catalog as Catalog
from . import card_correction_queue as queue


class CorrectionLane:
    def __init__(self, config, *, start_producer=True):
        self.config = config; self.catalog = Catalog(config['catalog_path'])
        queue.install(self.catalog)
        self.adoption = queue.adopt_legacy(self.catalog, config)
        self.producer = queue.CorrectionProducer(config) if start_producer else None
        if self.producer:
            self.producer.start()

    def stop(self):
        if self.producer:
            self.producer.stop()

    def sync(self, entries=None):
        return queue.sync(self.catalog, self.config, entries)

    def pending(self):
        return queue.enabled(self.config) and bool(queue.ready_requests(self.catalog))

    def ready_requests(self):
        return queue.ready_requests(self.catalog) if queue.enabled(self.config) else []

    def latest(self):
        with self.catalog.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='web_card_jobs'").fetchone():
                return []
            jobs = [dict(row) for row in db.execute("SELECT * FROM web_card_jobs WHERE json_extract(selection,'$.rework.correction_id') IS NOT NULL")]
        attempts = []
        for job in jobs:
            cid = json.loads(job['selection'])['rework']['correction_id']
            for path in (self.catalog.path.parent/'web_cards'/job['paper_id']).glob('*/attempt.json'):
                receipt = json.loads(path.read_text())
                if receipt.get('target_id'):
                    attempts.append({**receipt, 'kind':'correction', 'correction_id':receipt.get('correction_id'), 'association':'explicit' if receipt.get('correction_id') == cid else 'unknown_legacy', '_ledger_path':str(path)})
        return attempts

    def allow(self, job):
        return queue.allows_web_job(self.config, job)

    def state(self, job, state, **details):
        return queue.mark_web_state(self.catalog, job, state, **details)

    def status(self):
        return queue.status(self.config)
