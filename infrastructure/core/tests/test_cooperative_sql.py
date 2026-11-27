import asyncio
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.cooperative_sql import read_checkpoints, set_checkpoint


class CooperativeSqlTests(unittest.TestCase):
    def setUp(self):
        self.old=set_checkpoint(None);self.addCleanup(set_checkpoint,self.old)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.db=sqlite3.connect(Path(temp.name)/'catalog.sqlite');self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE numbers(n)')
        self.db.executemany('INSERT INTO numbers VALUES(?)',[(i,) for i in range(100)])
        self.db.commit()

    def test_default_has_no_owner_callback_or_change_to_results(self):
        with read_checkpoints(self.db):self.assertEqual(self.db.execute('SELECT count(*) FROM numbers').fetchone()[0],100)

    def test_pure_reads_checkpoint_but_explicit_transaction_and_writes_do_not(self):
        callback=Mock();set_checkpoint(callback)
        with read_checkpoints(self.db,interval=0,steps=1):
            self.assertEqual(len(self.db.execute('SELECT * FROM numbers').fetchall()),100)
            self.assertGreater(callback.call_count,0);callback.reset_mock()
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO numbers SELECT n+100 FROM numbers')
            self.assertEqual(self.db.execute('SELECT count(*) FROM numbers').fetchone()[0],200)
            self.db.commit();callback.assert_not_called()

    def test_callback_failure_aborts_read_and_preserves_original_error(self):
        set_checkpoint(Mock(side_effect=RuntimeError('owner loop unavailable')))
        with self.assertRaisesRegex(RuntimeError,'owner loop unavailable'):
            with read_checkpoints(self.db,interval=0,steps=1):self.db.execute('SELECT * FROM numbers').fetchall()

    def test_registration_is_not_inherited_by_background_threads(self):
        callback=Mock();set_checkpoint(callback)
        def read():
            db=sqlite3.connect(':memory:')
            try:
                with read_checkpoints(db,interval=0,steps=1):db.execute('SELECT 1').fetchall()
            finally:db.close()
        thread=threading.Thread(target=read);thread.start();thread.join();callback.assert_not_called()

    def test_non_wal_reads_keep_original_execution_to_avoid_writer_deadlock(self):
        db=sqlite3.connect(':memory:');callback=Mock();set_checkpoint(callback)
        try:
            with read_checkpoints(db,interval=0,steps=1):self.assertEqual(db.execute('SELECT 1').fetchone()[0],1)
        finally:db.close()
        callback.assert_not_called()

    def test_real_owner_loop_keeps_observing_and_wal_writer_commits_once(self):
        from playwright.sync_api import sync_playwright
        from greenlet import getcurrent
        from browser.owner_upload_jobs import OwnerUploadJobs
        with tempfile.TemporaryDirectory() as folder,sync_playwright() as pw:
            path=Path(folder)/'catalog.sqlite';reader=sqlite3.connect(path);reader.execute('PRAGMA journal_mode=WAL')
            reader.execute('CREATE TABLE items(n)');reader.executemany('INSERT INTO items VALUES(?)',[(i,) for i in range(1000)]);reader.commit()
            reader.create_function('slow',1,lambda n:(time.sleep(.001),n)[1])
            pulses=[];ticks=[];done=False
            def checkpoint():
                if getcurrent() is not pw._dispatcher_fiber:
                    pulses.append(time.monotonic());pw._sync(asyncio.sleep(0))
            set_checkpoint(checkpoint)
            async def observe():
                while not done:ticks.append(time.monotonic());await asyncio.sleep(.01)
            task=pw._loop.create_task(observe());jobs=OwnerUploadJobs(pw);writes=[]
            def write():
                db=sqlite3.connect(path,timeout=.2)
                try:
                    with read_checkpoints(db),db:db.execute('INSERT INTO items VALUES(1000)')
                finally:db.close()
                writes.append(1);return True
            jobs.start('other-owned-page',write)
            try:
                with read_checkpoints(reader):rows=reader.execute('SELECT slow(n) FROM items').fetchall()
                self.assertEqual(len(rows),1000);self.assertEqual(writes,[1]);self.assertGreater(len(ticks),2)
                self.assertGreater(len(pulses),2);self.assertEqual(reader.execute('SELECT count(*) FROM items').fetchone()[0],1001)
            finally:
                done=True;task.cancel();jobs.drain();reader.close();set_checkpoint(None)
