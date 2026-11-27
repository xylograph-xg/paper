import tempfile,unittest
from core.api import paths__WorkspacePath as Path
from cards.publication_materials import copy

class PublicationAliases(unittest.TestCase):
 def test_shared_pdf_and_page_aliases_do_not_copy_onto_themselves(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';out=root/'out';source.mkdir();out.mkdir()
   (out/'source.pdf').write_bytes(b'%PDF-test');(out/'pages').mkdir();(out/'pages/a.png').write_bytes(b'image')
   (source/'source.pdf').symlink_to(out/'source.pdf');(source/'pages').symlink_to(out/'pages',target_is_directory=True)
   copy(source,out);self.assertEqual((out/'source.pdf').read_bytes(),b'%PDF-test');self.assertEqual((out/'pages/a.png').read_bytes(),b'image')
 def test_distinct_materials_are_copied_with_hash_verification(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';out=root/'out';source.mkdir();out.mkdir()
   (source/'source.pdf').write_bytes(b'%PDF-test');(source/'pages').mkdir();(source/'pages/a.png').write_bytes(b'image')
   copy(source,out);self.assertEqual((out/'source.pdf').read_bytes(),b'%PDF-test')

class SavedPublicationGuards(unittest.TestCase):
 def test_unknown_receipt_never_reaches_publication(self):
  import json
  from unittest.mock import MagicMock,patch
  from correction.recover_saved_publication import run_once
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'web_cards'/'paper';attempt=folder/'chatgpt';attempt.mkdir(parents=True)
   (attempt/'attempt.json').write_text(json.dumps({'state':'needs_inspection','send_click_started':True}))
   (folder/'packet.json').write_text('{}')
   cat=MagicMock();cat.path=root/'catalog.sqlite3';cat.connect.return_value.__enter__.return_value.execute.return_value=[{'paper_id':'paper'}]
   with patch('correction.card_correction_queue.enabled',return_value=True),patch('correction.card_correction_queue.allows_web_job',return_value=True),patch('cards.web_card_service.publish_saved') as publish:
    result=run_once(cat,{})
   publish.assert_not_called();self.assertEqual(result[0]['state'],'cycling')
