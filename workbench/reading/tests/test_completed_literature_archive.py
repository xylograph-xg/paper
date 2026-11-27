import unittest,tempfile,hashlib
from core.api import paths__WorkspacePath as Path
from reading.completed_literature_archive import move_verified, digest

class ArchiveMove(unittest.TestCase):
 def test_preserves_bytes_and_other_destination_on_collision(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);library=root/'library';library.mkdir();source=root/'original.pdf';source.write_bytes(b'verified source');(library/source.name).write_bytes(b'other paper')
   sha=digest(source);target=Path(move_verified(source,library,sha,lambda:None))
   self.assertFalse(source.exists());self.assertEqual(target.read_bytes(),b'verified source');self.assertEqual((library/'original.pdf').read_bytes(),b'other paper')
 def test_changed_acceptance_chain_never_removes_original(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'original.pdf';source.write_bytes(b'verified');calls=[]
   def guard():
    calls.append(1)
    if len(calls)==2:raise ValueError('current card changed')
   with self.assertRaises(ValueError):move_verified(source,root/'library',digest(source),guard)
   self.assertEqual(source.read_bytes(),b'verified')
 def test_changed_source_is_not_moved(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'original.pdf';source.write_bytes(b'new version')
   with self.assertRaises(ValueError):move_verified(source,root/'library',hashlib.sha256(b'old').hexdigest(),lambda:None)
   self.assertTrue(source.exists())

class CompleteWorkflowArchive(unittest.TestCase):
 from reading.tests.test_reading_library import ReadingLibrary
 setUp=ReadingLibrary.setUp
 tearDown=ReadingLibrary.tearDown
 paper=ReadingLibrary.paper
 def test_completed_read_paper_moves_but_direct_pass_without_correction_stays(self):
  from correction.tests.test_corrected_library import mark_corrected,mark_passed
  from reading.manual_literature import install
  from reading.reading_library import update
  from reading.completed_literature_archive import run_once
  install(self.catalog);pid=self.paper('completed');mark_passed(self.catalog,pid,self.root)
  incoming=self.root/'staging';incoming.mkdir();file=incoming/'paper.pdf';file.write_bytes(self.source.read_bytes())
  config={'manual_literature':{'archive_completed_enabled':True,'directory':str(incoming),'failed_directory':str(self.root/'failed'),'completed_directory':str(self.root/'library')}}
  self.assertFalse(run_once(self.catalog,config)['moved']);self.assertTrue(file.exists())
  mark_corrected(self.catalog,pid,self.root);update(self.catalog,pid,{'is_read':True})
  self.assertEqual(self.catalog.page(tab='deep')['total'],0)
  report=run_once(self.catalog,config);self.assertEqual(len(report['moved']),1);self.assertFalse(file.exists())
  self.assertTrue(self.source.exists());self.assertEqual((self.root/'library'/'paper.pdf').read_bytes(),self.source.read_bytes())
