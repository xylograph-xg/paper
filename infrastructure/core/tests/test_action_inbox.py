import json
from core.api import paths__WorkspacePath as Path
import tempfile
import time
import unittest
from core.action_inbox import snapshot


class ActionInbox(unittest.TestCase):
    def test_overdue_archived_unknown_receipt_is_actionable_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config={'catalog_path':str(root/'catalog.sqlite3'),'web_cards':{'enabled':True}}
            path=root/'web_cards'/'paper'/'history'/'old'/'chatgpt'/'attempt.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'state':'needs_inspection','target_id':'original',
                'created':time.time()-90000,'conversation_url':'https://chatgpt.com/c/original'}))
            before=path.read_bytes();items=snapshot(config)['items']
            self.assertEqual(len(items),1)
            self.assertTrue(items[0]['id'].startswith('receipt:'))
            self.assertEqual(path.read_bytes(),before)

    def test_manual_and_browser_actions_are_visible_but_cooldown_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config={'catalog_path':str(root/'catalog.sqlite3'),'web_cards':{'enabled':True,'allowed_providers':['chatgpt']}}
            (root/'web-provider-control.json').write_text(json.dumps({'chatgpt':{'blocked_until':time.time()+60}}))
            self.assertEqual(snapshot(config)['items'],[])
            (root/'web-channel-control.json').write_text('{"chatgpt":{"manual_verification_required":true}}')
            (root/'web-tab-check.json').write_text(json.dumps({'total_pages':0,'updated':time.time()}))
            before={p.name:p.read_bytes() for p in root.iterdir()}
            items=snapshot(config)['items']
            self.assertEqual({i['id'] for i in items},{'channel:chatgpt','browser-page'})
            self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)

    def test_user_pause_does_not_request_browser_or_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config={'catalog_path':str(root/'catalog.sqlite3')}
            (root/'web-card-control.json').write_text('{"paused_by_user":true}')
            (root/'web-tab-check.json').write_text(json.dumps({'total_pages':0,'updated':time.time()}))
            self.assertEqual(snapshot(config)['items'],[])
