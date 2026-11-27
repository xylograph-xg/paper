"""Real Chrome isolation check, using only disposable local synthetic pages."""
import hashlib
import json
import os
import tempfile
from core.api import paths__WorkspacePath as Path

from playwright.sync_api import sync_playwright
from core.services import atomic_json
from browser.shared_browser_window import read_window_inventory, WindowIsolationError
from browser.shared_window_owner import observe, require_slot, registry_path
from browser.shared_page_dispatch import dispatch


def main():
    with tempfile.TemporaryDirectory(prefix='paper-fixed-window-') as folder,sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('PAPER_TEST_CHROME','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),args=['--no-first-run'])
        try:
            session=browser.new_browser_cdp_session()
            ids=[session.send('Target.createTarget',{'url':'about:blank','background':True})['targetId'] for _ in range(20)]
            config={'catalog_path':str(Path(folder)/'catalog.sqlite3')}
            entries={tid:{'state':'ready_blank'} for tid in ids}
            report=observe(config,browser,entries)
            assert report['live_fixed_slots']==20 and len(report['eligible_target_ids'])==20,report
            before=registry_path(config).read_bytes()
            foreign=session.send('Target.createTarget',{'url':'data:text/html,<textarea>USER DRAFT</textarea>','newWindow':True,'background':True,'focus':False})['targetId']
            inventory=read_window_inventory(browser)
            assert inventory['targets'][foreign]['window_id']!=report['window_id'],inventory
            report=observe(config,browser,entries)
            assert report['browser_total_pages']==21 and report['other_window_pages']==1,report
            assert foreign not in report['collect_target_ids'] and foreign not in report['eligible_target_ids']
            assigned=dispatch(entries,report['eligible_target_ids'],cards_limit=20,review_limit=4)
            assert len(assigned['card_ready'])==16 and len(assigned['review_ready'])==4,assigned
            assert foreign not in assigned['card_targets']+assigned['review_targets']
            try:require_slot(config,browser,foreign)
            except WindowIsolationError:pass
            else:raise AssertionError('foreign page accepted')
            session.send('Target.closeTarget',{'targetId':ids[0]})
            report=observe(config,browser,entries)
            assert len(report['missing_slot_ids'])==1 and report['live_fixed_slots']==19,report
            assert registry_path(config).read_bytes()==before,'slot registration changed'
            after=read_window_inventory(browser)
            assert foreign in after['targets'] and after['targets'][foreign]['url']==inventory['targets'][foreign]['url']
            assert after['total_pages']==20,'unexpected page creation'
            print(json.dumps({'state':'pass','fixed_slots':20,'other_window_preserved':True,'budget':assigned['budget'],
                'missing_slot_preserved':True,'registry_sha256':hashlib.sha256(before).hexdigest(),'network_requests':0},ensure_ascii=False))
        finally:browser.close()


if __name__=='__main__':main()
