import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import patch
from core.catalog import Catalog
from core.continuous_status import status
from core.continuous_start import start

class ContinuousControl(unittest.TestCase):
 def test_counts_and_completion_time_use_catalog(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'data/catalog.sqlite3';catalog=Catalog(db)
   pid=catalog.upsert({'title':'Synthetic original'})
   catalog.update(pid,acquisition='available',card_path='/synthetic/card.json')
   catalog.upsert({'title':'Metadata only'})
   with catalog.connect() as conn:
    conn.execute("INSERT INTO events(kind,paper_id,created,payload) VALUES(?,?,?,?)",('web_card_generated',pid,'2026-10-07T14:43:23+00:00','{}'))
   value=status(db)
   self.assertEqual((value['total'],value['downloaded'],value['cards']),(2,1,1))
   self.assertEqual(value['last_card_completed_shanghai'],'2026-10-07 22:43:23')
 def test_main_start_preserves_local_pause_and_reuses_services(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir()
   local=data/'local-model-control.json';local.write_text('{"paused_by_user":true}')
   (data/'fetch-control.json').write_text('{"paused_by_user":true}')
   (data/'web-card-control.json').write_text('{"paused_by_user":true}')
   with patch('core.continuous_start.ROOT',root),patch('core.continuous_start.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='',stdout='')) as run:
    start({'catalog_path':str(data/'catalog.sqlite3')})
    calls=[c.args[0] for c in run.call_args_list]
    self.assertEqual(len(calls),3);self.assertTrue(all(c[:2]==['launchctl','kickstart'] and '-k' not in c for c in calls))
   self.assertTrue(json.loads(local.read_text())['paused_by_user'])
   self.assertFalse(json.loads((data/'fetch-control.json').read_text())['paused_by_user'])
   self.assertEqual(json.loads((data/'web-provider-selection.json').read_text())['allowed_providers'],['chatgpt'])
 def test_isolated_catalog_rejected_before_mutation(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):start({'catalog_path':str(Path(td)/'catalog.sqlite3')})
   self.assertEqual(list(Path(td).iterdir()),[])
 def test_stop_persists_pause_and_signals_only_current_services(self):
  from core.continuous_start import stop
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir()
   local=data/'local-model-control.json';local.write_text('{"paused_by_user":true}')
   with patch('core.continuous_start.ROOT',root),patch('fetch.fetch_service.request_stop',return_value={'state':'stop_requested'}),patch('cards.web_card_service.stop',return_value={'state':'stop_requested'}),patch('core.continuous_start.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
    stop({'catalog_path':str(data/'catalog.sqlite3')})
    calls=[c.args[0] for c in run.call_args_list]
    self.assertEqual(len(calls),3)
    self.assertTrue(all(c[:3]==['launchctl','kill','SIGTERM'] for c in calls))
   for name in ('fetch-control.json','web-card-control.json','web-tab-watch-control.json'):
    self.assertTrue(json.loads((data/name).read_text())['paused_by_user'])
   self.assertTrue(json.loads(local.read_text())['paused_by_user'])
 def test_task_controls_are_independent(self):
  from core.continuous_start import stop
  for target,changed,untouched in [('fetch','fetch-control.json','web-card-control.json'),('cards','web-card-control.json','fetch-control.json')]:
   with self.subTest(target=target),tempfile.TemporaryDirectory() as td:
    root=Path(td);data=root/'data';data.mkdir()
    (data/untouched).write_text('{"paused_by_user":true,"marker":"preserved"}')
    original=(data/untouched).read_bytes()
    with patch('core.continuous_start.ROOT',root),patch('core.continuous_start.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='',stdout='')) as run,patch('fetch.fetch_service.request_stop',return_value={}),patch('cards.web_card_service.stop',return_value={}):
     start({'catalog_path':str(data/'catalog.sqlite3')},target=target)
     self.assertFalse(json.loads((data/changed).read_text())['paused_by_user'])
     self.assertEqual((data/untouched).read_bytes(),original)
     self.assertEqual(run.call_count,1 if target=='fetch' else 2)
     run.reset_mock()
     stop({'catalog_path':str(data/'catalog.sqlite3')},target=target)
     self.assertTrue(json.loads((data/changed).read_text())['paused_by_user'])
     self.assertEqual((data/untouched).read_bytes(),original)
     self.assertEqual(run.call_count,1 if target=='fetch' else 2)
