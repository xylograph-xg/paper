import json
from core.api import paths__WorkspacePath as Path
import tempfile
import unittest
from core.catalog import ROOT, load_config, validate_local_model


class ConfigBoundaries(unittest.TestCase):
    def test_web_and_fetch_load_without_local_model_config(self):
        config=json.loads((ROOT/'config/first_round.json').read_text())
        config.pop('model');config['local_model_schedule']={'start':'bad','end':'bad'}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.json';path.write_text(json.dumps(config))
            loaded=load_config(path)
            self.assertTrue(loaded['web_cards']['enabled'])
            with self.assertRaises(ValueError):validate_local_model(loaded)

    def test_total_browser_capacity_is_validated(self):
        config=json.loads((ROOT/'config/first_round.json').read_text());config['web_cards']['max_total_pages']=21
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.json';path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):load_config(path)
