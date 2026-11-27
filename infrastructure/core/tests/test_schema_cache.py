from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from core.catalog import Catalog
from reading import reading_library


class SchemaCache(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'catalog.sqlite3';self.catalog=Catalog(self.path)

    def test_unchanged_initialization_reads_while_another_writer_is_active(self):
        queries=[];connect=Catalog.connect
        @contextmanager
        def traced(catalog):
            with connect(catalog) as db:
                db.set_trace_callback(queries.append);yield db
        with sqlite3.connect(self.path,timeout=.1) as holder:
            holder.execute('BEGIN IMMEDIATE')
            holder.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(NULL,'uncommitted','{}','now')")
            start=time.monotonic()
            with patch.object(Catalog,'connect',traced):Catalog(self.path)
            self.assertLess(time.monotonic()-start,1)
        self.assertFalse(any(q.lstrip().upper().startswith(('INSERT','UPDATE','DROP','CREATE','ALTER','BEGIN IMMEDIATE')) for q in queries))

    def test_missing_trigger_is_restored_instead_of_trusting_cache(self):
        with self.catalog.connect() as db:db.execute('DROP TRIGGER fetch_attempt_started')
        Catalog(self.path)
        with self.catalog.connect() as db:
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='fetch_attempt_started'").fetchone())

    def test_changed_loaded_initializer_runs_new_schema_then_reuses_it(self):
        install=reading_library.install
        def changed(catalog):
            install(catalog)
            with catalog.connect() as db:db.execute('CREATE INDEX IF NOT EXISTS changed_initializer_index ON paper_reading_state(note)')
        with patch.object(reading_library,'install',changed):
            Catalog(self.path)
            with self.catalog.connect() as db:
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='changed_initializer_index'").fetchone())
            Catalog(self.path)


if __name__=='__main__':unittest.main()
