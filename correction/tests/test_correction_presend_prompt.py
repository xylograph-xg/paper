import tempfile,unittest
from core.api import paths__WorkspacePath as Path
from correction.card_correction_queue import check_retry_prompt

class CorrectionPrompt(unittest.TestCase):
 def test_no_actual_prompt_before_explicit_unsent_failure_is_not_missing_material(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'history'/'retry'/'chatgpt'/'attempt.json';path.parent.mkdir(parents=True)
   check_retry_prompt(path,root,{'state':'not_sent','send_click_started':False})
   for r in [{'state':'submitted','send_click_started':True},{'state':'not_sent','send_click_started':None},
             {'state':'not_sent','send_click_started':False,'actual_prompt_sha256':'expected'}]:
    with self.subTest(r=r),self.assertRaises(FileNotFoundError):check_retry_prompt(path,root,r)
 def test_existing_prompt_without_original_hash_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'attempt.json';(root/'prompt-actual.txt').write_text('unexpected')
   with self.assertRaises(ValueError):check_retry_prompt(path,root,{'state':'not_sent','send_click_started':False})
