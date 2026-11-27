import tempfile,unittest
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog
from fetch.fetch_timing import status

class FetchTimingTests(unittest.TestCase):
 def test_actual_claim_and_finish_are_distinct_from_queue_creation(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=Catalog(Path(tmp)/'catalog.sqlite3');pid=c.upsert({'title':'paper'});jid=c.enqueue('acquire',pid)
   with c.connect() as db:
    db.execute("UPDATE jobs SET created='2000-01-01T00:00:00+00:00' WHERE id=?",(jid,))
    db.execute("UPDATE jobs SET state='running',attempts=1,updated='2026-10-07T12:00:00+00:00' WHERE id=?",(jid,))
   s=status(c);self.assertEqual(s['active'][0]['started_at'],'2026-10-07T12:00:00+00:00');self.assertIsNone(s['last_finished'])
   with c.connect() as db:db.execute("UPDATE jobs SET state='deferred',updated='2026-10-07T12:01:00+00:00' WHERE id=?",(jid,))
   s=status(c);self.assertFalse(s['active']);self.assertEqual(s['last_finished']['ended_at'],'2026-10-07T12:01:00+00:00');self.assertEqual(s['last_finished']['result'],'deferred')
   with c.connect() as db:
    db.execute("UPDATE jobs SET state='queued' WHERE id=?",(jid,));db.execute("UPDATE jobs SET state='running',attempts=2,updated='2026-10-07T13:00:00+00:00' WHERE id=?",(jid,))
   self.assertEqual(status(c)['active'][0]['attempt'],2);self.assertEqual(status(c)['recent'][0]['started_at'],'2026-10-07T12:00:00+00:00')

if __name__=='__main__':unittest.main()
