"""Real Chrome lifecycle isolation check; synthetic pages and no account/network."""
import hashlib
import json
import os
import tempfile
import time
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from browser.browser_inventory import enumerate_pages
from core.services import atomic_json
from browser.shared_browser_window import read_window_inventory
from browser.shared_page_repair import run_once
from browser.shared_window_owner import observe, registry_path
from browser.shared_window_tabs import MANIFEST, WORKER_SOURCE


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _window_tabs(browser, root, window_id):
    """Read exact tab active/focus metadata through a disposable, permissionless worker."""
    with tempfile.TemporaryDirectory(prefix='read-window-', dir=root) as folder:
        source = Path(folder)
        (source / 'manifest.json').write_text(json.dumps(MANIFEST))
        (source / 'worker.js').write_text(WORKER_SOURCE)
        session = browser.new_browser_cdp_session()
        extension_id = session.send('Extensions.loadUnpacked', {'path': str(source)})['id']
        try:
            expected = 'chrome-extension://' + extension_id + '/worker.js'
            deadline = time.monotonic() + 5
            while True:
                session.send('Target.getTargets')
                workers = [worker for context in browser.contexts for worker in context.service_workers
                           if worker.url == expected]
                if workers:
                    return workers[0].evaluate('''async windowId => ({
                        tabs: (await chrome.tabs.query({windowId})).map(tab => ({id:tab.id,windowId:tab.windowId,active:tab.active})),
                        windows: (await chrome.windows.getAll()).map(window => ({id:window.id,focused:window.focused}))
                    })''', window_id)
                if time.monotonic() >= deadline:
                    raise AssertionError('Isolated read-only worker did not start')
                time.sleep(.05)
        finally:
            session.send('Extensions.uninstall', {'id': extension_id})
            session.detach()


def main():
    with tempfile.TemporaryDirectory(prefix='paper-page-repair-') as folder, sync_playwright() as pw:
        root = Path(folder)
        config = {'catalog_path': str(root / 'catalog.sqlite'), 'web_cards': {'enabled': True,
            'shared_window': {'enabled': True, 'slot_count': 20, 'health_repair': {
                'enabled': True, 'check_interval_seconds': 30, 'max_replacements_per_cycle': 2}}}}
        # A descriptive endpoint binds this isolated registry; no server is started or connected.
        with patch.dict(os.environ, {'WEB_GPT_CDP_URL': 'http://127.0.0.1:59999'}):
            context = pw.chromium.launch_persistent_context(str(root / 'isolated-profile'),
                headless=True, executable_path=os.environ.get(
                'PAPER_TEST_CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                args=['--no-first-run', '--enable-extensions'],
                ignore_default_args=['--disable-extensions', '--enable-automation'])
            browser = context.browser
            try:
                session = browser.new_browser_cdp_session()
                ids = list(enumerate_pages(browser)['pages'])
                assert len(ids) == 1, ids
                ids += [session.send('Target.createTarget', {'url': 'about:blank', 'background': True})['targetId']
                        for _ in range(19)]
                entries = {tid: {'state': 'ready_blank', 'never_submitted': True} for tid in ids}
                pool = {'windows': entries}
                initial = observe(config, browser, entries)
                assert initial['live_fixed_slots'] == 20, initial
                registry_before = json.loads(registry_path(config).read_text())
                bad_slot = registry_before['slots'][0]
                old = bad_slot['target_id']
                entries[old] = {'state': 'needs_inspection', 'kind': 'cards'}
                foreign = session.send('Target.createTarget', {'url': 'about:blank', 'newWindow': True,
                    'background': True, 'focus': False})['targetId']
                inventory_before = read_window_inventory(browser)
                foreign_window = inventory_before['targets'][foreign]['window_id']
                assert foreign_window != initial['window_id'], inventory_before
                session.send('Target.activateTarget', {'targetId': foreign})
                pages = enumerate_pages(browser)['pages']
                pages[foreign].set_content('<textarea id="user-draft">USER DRAFT — 保留此窗口</textarea>')
                pages[old].set_content('<div id="main-frame-error">net::ERR_SSL_PROTOCOL_ERROR</div>')
                foreign_content = pages[foreign].content()
                foreign_url = pages[foreign].url
                foreign_draft = pages[foreign].locator('#user-draft').input_value()
                foreign_metadata = _window_tabs(browser, root, foreign_window)
                assert foreign_metadata['tabs'][0]['active'] is True, foreign_metadata

                ledger = root / 'web_cards' / 'synthetic-paper' / 'chatgpt' / 'attempt.json'
                ledger.parent.mkdir(parents=True)
                prompt = '仅用于隔离测试的合成文献任务；此提示从未发送。'
                (ledger.parent / 'prompt-actual.txt').write_text(prompt)
                atomic_json(ledger, {'paper_id': 'synthetic-paper', 'target_id': old, 'state': 'not_sent',
                    'send_click_started': False, 'conversation_url': 'about:blank',
                    'actual_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                    'error': 'synthetic upload failed: net::ERR_SSL_PROTOCOL_ERROR'})
                ledger_before = ledger.read_bytes()
                ledger_sha = _sha(ledger)
                homepage_requests = []
                blocked_requests = []

                def synthetic_home(route):
                    if route.request.url.rstrip('/') == 'https://chatgpt.com':
                        homepage_requests.append(route.request.url)
                        route.fulfill(status=200, content_type='text/html', body='''<!doctype html>
                            <main><div id="prompt-textarea" contenteditable="true" role="textbox"
                            style="display:block;width:400px;height:60px"> </div></main>''')
                    else:
                        blocked_requests.append(route.request.url)
                        route.abort()

                for context in browser.contexts:
                    context.route('https://**/*', synthetic_home)
                    context.route('http://**/*', synthetic_home)
                first = run_once(config, browser, pool, lock_factory=lambda timeout: nullcontext())
                assert first['errors'] == [], first
                assert first['pages'][old]['health'] == 'waiting_stable', first
                assert first['replaced'] == [], first
                assert old in read_window_inventory(browser)['targets'], 'first inspection closed original page'
                assert ledger.read_bytes() == ledger_before, 'first inspection mutated original ledger'

                with patch('browser.shared_page_repair.time.time', return_value=first['checked_at'] + 35):
                    second = run_once(config, browser, pool, lock_factory=lambda timeout: nullcontext())
                assert second['errors'] == [], second
                assert second['state'] == 'checked' and len(second['replaced']) == 1, second
                replacement = second['replaced'][0]
                new = replacement['new_target_id']
                assert replacement['old_target_id'] == old and new != old, replacement
                registry_after = json.loads(registry_path(config).read_text())
                after_slots = {slot['slot_id']: slot['target_id'] for slot in registry_after['slots']}
                before_slots = {slot['slot_id']: slot['target_id'] for slot in registry_before['slots']}
                assert after_slots == {**before_slots, bad_slot['slot_id']: new}, registry_after
                final_inventory = read_window_inventory(browser)
                dedicated = {tid for tid, target in final_inventory['targets'].items()
                             if target['window_id'] == initial['window_id']}
                assert dedicated == set(after_slots.values()) and len(dedicated) == 20, final_inventory
                assert final_inventory['total_pages'] == 21 and old not in final_inventory['targets'], final_inventory
                assert final_inventory['targets'][foreign]['window_id'] == foreign_window, final_inventory
                final_pages = enumerate_pages(browser)['pages']
                assert final_pages[foreign].url == foreign_url, 'foreign URL changed'
                assert final_pages[foreign].content() == foreign_content, 'foreign DOM changed'
                assert final_pages[foreign].locator('#user-draft').input_value() == foreign_draft, 'foreign draft changed'
                assert _window_tabs(browser, root, foreign_window) == foreign_metadata, 'foreign active tab/window focus changed'
                assert pool['windows'] is entries, 'owner windows object was replaced'
                assert entries[old]['state'] == 'retired_replaced' and entries[new]['state'] == 'ready_blank', entries
                assert ledger.read_bytes() == ledger_before and _sha(ledger) == ledger_sha, 'original ledger changed'
                assert final_pages[new].url.rstrip('/') == 'https://chatgpt.com', final_pages[new].url
                assert final_pages[new].locator('#prompt-textarea').is_visible(), 'replacement composer missing'
                assert final_pages[new].locator('[data-message-author-role="user"]').count() == 0, 'unexpected send'
                journal_path = Path(replacement['journal'])
                journal = json.loads(journal_path.read_text())
                assert journal['state'] == 'ready' and journal['candidate']['extension_uninstalled'] is True, journal
                archive = journal_path.parent / 'diagnostics'
                assert (archive / 'ledger-before.json').read_bytes() == ledger_before, 'archived ledger mismatch'
                assert 'ERR_SSL_PROTOCOL_ERROR' in (archive / 'body.txt').read_text(), 'error evidence missing'
                assert (archive / 'page.png').stat().st_size > 0, 'diagnostic screenshot missing'
                for name, expected in journal['archive_hashes'].items():
                    assert _sha(archive / name) == expected, 'diagnostic fingerprint mismatch: ' + name
                assert session.send('Extensions.getExtensions')['extensions'] == [], 'temporary extension remained installed'
                assert not list(root.rglob('slot-extension-*')), 'temporary extension source remained'
                assert homepage_requests == ['https://chatgpt.com/'] and blocked_requests == [], (homepage_requests, blocked_requests)
                print(json.dumps({'state': 'pass', 'fixed_slots': 20, 'other_window_preserved': True,
                    'foreign_draft_active_and_focus_unchanged': True, 'original_ledger_sha256': ledger_sha,
                    'stable_inspections': 2, 'replaced_slots': [replacement['slot_id']],
                    'archive_fingerprints_verified': True, 'temporary_extensions_uninstalled': True,
                    'synthetic_homepage_requests': len(homepage_requests), 'external_network_requests': 0,
                    'submitted_messages': 0}, ensure_ascii=False))
                session.detach()
            finally:
                context.close()


if __name__ == '__main__':
    main()
