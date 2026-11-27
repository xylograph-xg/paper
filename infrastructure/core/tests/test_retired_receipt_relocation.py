import json,tempfile,unittest,hashlib
from core.api import paths__WorkspacePath as Path
from browser.shared_claim_recovery import locate_retired_receipt

class RetiredReceipt(unittest.TestCase):
 def test_unique_archived_original_found_without_using_changed_current_receipt(self):
  with tempfile.TemporaryDirectory() as folder:
   paper=Path(folder)/'web_cards'/'paper';current=paper/'chatgpt'/'attempt.json';current.parent.mkdir(parents=True)
   raw=json.dumps({'target_id':'original','state':'not_sent','send_click_started':False}).encode()
   record={'target_id':'original','_ledger_path':str(current),'_ledger_sha256':hashlib.sha256(raw).hexdigest()}
   archive=paper/'history'/'retry'/'attempt.json';archive.parent.mkdir(parents=True);archive.write_bytes(raw)
   current.write_text(json.dumps({'target_id':'new','state':'submitted'}))
   self.assertEqual(locate_retired_receipt(record)['_ledger_path'],str(archive.resolve()))
   current.unlink();self.assertEqual(locate_retired_receipt(record)['_ledger_sha256'],record['_ledger_sha256'])
   archive.write_bytes(b'{}')
   with self.assertRaises(ValueError):locate_retired_receipt(record)
