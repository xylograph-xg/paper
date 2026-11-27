import json
from core.api import paths__WorkspacePath as Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from core.catalog import Catalog
from cards import web_card_queue as queue


class PoolLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.catalog=Catalog(self.root/'catalog.sqlite3');queue.install(self.catalog)
        (self.root/'gpt-window-pool.json').write_text('{"windows":{}}')
        self.config={'catalog_path':str(self.catalog.path),'studio_library_root':str(self.root/'library'),
            '_config_path':str(self.root/'config.json'),'web_cards':{'enabled':True,'allowed_providers':['chatgpt'],'background_no_create':True}}

    def test_background_executor_recovers_interrupted_jobs_under_service_lock(self):
        from cards.web_card_service import run
        with self.catalog.connect() as db:
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated,state) VALUES('p','hash','title','{}','now','submitted')")
        with patch('browser.web_card_pool.run_pool') as pool:
            run(self.config);pool.assert_called_once_with(self.config)
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'needs_inspection')
        self.assertIsNone(queue.claim(self.catalog))

    def test_failed_connection_releases_driver_without_closing_dedicated_chrome(self):
        from browser.web_card_pool import run_pool
        callbacks={};driver=Mock()
        driver.chromium.connect_over_cdp.side_effect=RuntimeError('CDP connection failure')
        manager=Mock();manager.start.return_value=driver
        def register(sig,handler):callbacks[sig]=handler
        def stop_after_iteration(_):next(iter(callbacks.values()))(None,None)
        with patch('playwright.sync_api.sync_playwright',return_value=manager),\
             patch('browser.web_card_pool.signal.signal',side_effect=register),\
             patch('browser.web_media_storage.require_config_storage'),\
             patch('browser.web_card_pool.time.sleep',side_effect=stop_after_iteration):
            run_pool(self.config)
        driver.stop.assert_called_once()
        self.assertEqual(json.loads((self.root/'web-card-service.json').read_text())['state'],'stopped')
        driver.chromium.launch.assert_not_called()
