import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock

from browser.shared_window_tabs import CREATE_EXPRESSION, MANIFEST, WORKER_SOURCE, TabCreationError, blank_url, create_in_window, probe_support, _confirm_cleanup


NONCE = "0123456789abcdef0123456789abcdef"


class WindowCDP:
    def __init__(self, owned_count=19, *, foreign_count=15):
        self.targets = {f"owned-{i}": {"targetId": f"owned-{i}", "type": "page",
                                      "url": "https://chatgpt.com/", "window": 77}
                        for i in range(owned_count)}
        self.owned = set(self.targets)
        self.targets.update({f"user-{i}": {"targetId": f"user-{i}", "type": "page",
                                           "url": "https://example.test/", "window": 999}
                             for i in range(foreign_count)})
        self.calls = []
        self.extension_path = None
        self.extension_loaded = False
        self.create_count = 0
        self.raise_after_create = False
        self.cleanup_fail = False
        self.created_window_id = None
        self.created_active = False
        self.foreign_enters_during_create = False
        self.worker = SimpleNamespace(url="chrome-extension://temporary/worker.js",
                                      evaluate=self.evaluate)
        self.context = SimpleNamespace(service_workers=[self.worker])
        self.browser = SimpleNamespace(contexts=[self.context],
                                       new_browser_cdp_session=lambda: self)

    def send(self, method, params=None):
        self.calls.append((method, params))
        if method == "Target.getTargets":
            return {"targetInfos": [{k: v for k, v in target.items() if k != "window"}
                                    for target in self.targets.values()]}
        if method == "Browser.getWindowForTarget":
            return {"windowId": self.targets[params["targetId"]]["window"]}
        if method == "Extensions.getExtensions":
            return {"extensions": []}
        if method == "Extensions.loadUnpacked":
            self.extension_path = Path(params["path"])
            self.extension_loaded = True
            self.loaded_manifest = json.loads((self.extension_path / "manifest.json").read_text())
            return {"id": "temporary"}
        if method == "Extensions.uninstall":
            if self.cleanup_fail:
                raise RuntimeError("cannot unload now")
            self.extension_loaded = False
            return {}
        raise AssertionError("Unapproved command: " + method)

    def detach(self):
        self.calls.append(("detach", None))

    def evaluate(self, expression, props=None):
        if props is None:
            return 1
        if expression != CREATE_EXPRESSION:
            raise AssertionError("Unapproved expression")
        self.create_count += 1
        created_window = props["windowId"] if self.created_window_id is None else self.created_window_id
        self.targets["new-owned"] = {"targetId": "new-owned", "type": "page",
                                      "url": props["url"], "window": created_window}
        if self.foreign_enters_during_create:
            self.targets["user-0"]["window"] = props["windowId"]
        if self.raise_after_create:
            raise RuntimeError("creation succeeded but receipt connection lost")
        return {"id": 123, "windowId": created_window, "active": self.created_active}


class SharedWindowTabs(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def create(self, cdp, **kwargs):
        return create_in_window(cdp.browser, 77, root=self.folder.name,
                                nonce=NONCE, owned_ids=cdp.owned, **kwargs)

    def test_precise_window_background_create_and_transient_extension_cleanup(self):
        cdp = WindowCDP()
        user_before = {tid: dict(target) for tid, target in cdp.targets.items() if tid.startswith("user-")}
        receipts = []
        result = self.create(cdp, on_created=receipts.append)
        self.assertEqual(result["target_id"], "new-owned")
        self.assertEqual(result["window_id"], 77)
        self.assertEqual(result["url"], blank_url(NONCE))
        self.assertTrue(result["extension_uninstalled"])
        self.assertEqual(cdp.create_count, 1)
        self.assertEqual(receipts[0]["nonce"], NONCE)
        self.assertFalse(cdp.extension_loaded)
        self.assertFalse(cdp.extension_path.exists())
        self.assertEqual(user_before, {tid: target for tid, target in cdp.targets.items() if tid.startswith("user-")})
        self.assertNotIn("permissions", cdp.loaded_manifest)
        self.assertNotIn("host_permissions", cdp.loaded_manifest)
        self.assertNotIn("content_scripts", cdp.loaded_manifest)

    def test_twenty_page_window_waits_before_loading_or_creating(self):
        cdp = WindowCDP(owned_count=20)
        with self.assertRaisesRegex(TabCreationError, "先归档并关闭"):
            self.create(cdp)
        self.assertEqual(cdp.create_count, 0)
        self.assertFalse(cdp.extension_loaded)
        self.assertFalse(any(method.startswith("Extensions.") for method, _ in cdp.calls))

    def test_detach_failure_preserves_final_cleanup_in_callback_and_exception(self):
        cdp = WindowCDP()
        cdp.detach = Mock(side_effect=RuntimeError('detach reply lost'))
        receipts = []
        with self.assertRaises(TabCreationError) as caught:
            self.create(cdp, on_created=receipts.append)
        self.assertTrue(receipts[-1]['extension_uninstalled'])
        self.assertTrue(caught.exception.candidate['extension_uninstalled'])
        self.assertEqual(cdp.create_count, 1)
        self.assertFalse(cdp.extension_loaded)

    def cleanup_browser(self, extensions, *, fail_uninstall=False):
        session = Mock()
        def send(method, params=None):
            if method == 'Extensions.getExtensions':
                return {'extensions': list(extensions)}
            self.assertEqual(method, 'Extensions.uninstall')
            if fail_uninstall:
                raise RuntimeError('uninstall receipt unknown')
            extensions[:] = [item for item in extensions if item['id'] != params['id']]
            return {}
        session.send.side_effect = send
        return SimpleNamespace(new_browser_cdp_session=lambda: session), session

    def test_cleanup_absence_confirmation_preserves_unrelated_extensions(self):
        extensions = [{'id': 'user-extension', 'path': '/other/profile/user-helper'}]
        browser, session = self.cleanup_browser(extensions)
        proof = _confirm_cleanup(browser, self.folder.name)
        self.assertTrue(proof['extension_uninstalled'])
        self.assertIsNone(proof['removed_extension_id'])
        self.assertEqual(extensions[0]['id'], 'user-extension')
        session.send.assert_called_once_with('Extensions.getExtensions')

    def test_cleanup_uninstalls_only_exact_journal_helper_after_source_validation(self):
        source = Path(self.folder.name)/'slot-extension-original'
        source.mkdir()
        (source/'manifest.json').write_text(json.dumps(MANIFEST))
        (source/'worker.js').write_text(WORKER_SOURCE)
        extensions = [{'id': 'owned', 'path': str(source)},
                      {'id': 'other', 'path': '/other/profile/user-helper'}]
        browser, session = self.cleanup_browser(extensions)
        proof = _confirm_cleanup(browser, self.folder.name)
        self.assertEqual(proof['removed_extension_id'], 'owned')
        self.assertEqual(extensions, [{'id': 'other', 'path': '/other/profile/user-helper'}])
        self.assertTrue(source.exists())  # Evidence is retained, not garbage-collected.
        self.assertEqual(session.send.call_args_list[1].args, ('Extensions.uninstall', {'id': 'owned'}))

    def test_cleanup_changed_source_duplicate_or_unknown_uninstall_stays_unconfirmed(self):
        source = Path(self.folder.name)/'slot-extension-original'
        source.mkdir()
        (source/'manifest.json').write_text(json.dumps(MANIFEST))
        (source/'worker.js').write_text('user-modified helper')
        extensions = [{'id': 'owned', 'path': str(source)}]
        browser, session = self.cleanup_browser(extensions)
        with self.assertRaisesRegex(TabCreationError, '源码'):
            _confirm_cleanup(browser, self.folder.name)
        self.assertEqual(session.send.call_count, 1)
        (source/'worker.js').write_text(WORKER_SOURCE)
        extensions.append({'id': 'duplicate', 'path': str(source)})
        with self.assertRaisesRegex(TabCreationError, '不唯一'):
            _confirm_cleanup(browser, self.folder.name)
        extensions.pop()
        browser, session = self.cleanup_browser(extensions, fail_uninstall=True)
        with self.assertRaisesRegex(RuntimeError, 'unknown'):
            _confirm_cleanup(browser, self.folder.name)
        self.assertEqual(len(extensions), 1)

    def test_cleanup_incomplete_metadata_and_pause_never_uninstall(self):
        browser, session = self.cleanup_browser([{'id': 'missing-path'}])
        with self.assertRaisesRegex(TabCreationError, '清单不完整'):
            _confirm_cleanup(browser, self.folder.name)
        self.assertEqual(session.send.call_count, 1)
        session.reset_mock()
        with self.assertRaisesRegex(TabCreationError, '暂停'):
            _confirm_cleanup(browser, self.folder.name, stopping=lambda: True)
        session.send.assert_not_called()

    def test_user_page_inside_window_blocks_without_mutation(self):
        cdp = WindowCDP()
        cdp.targets["user-0"]["window"] = 77
        with self.assertRaisesRegex(TabCreationError, "混入用户页面"):
            self.create(cdp)
        self.assertEqual(cdp.create_count, 0)
        self.assertFalse(cdp.extension_loaded)

    def test_missing_original_window_is_not_replaced_by_current_foreign_window(self):
        cdp = WindowCDP(owned_count=0)
        with self.assertRaisesRegex(TabCreationError, "原专用窗口缺失"):
            self.create(cdp)
        self.assertEqual(cdp.create_count, 0)

    def test_existing_unique_nonce_is_recovered_without_second_create(self):
        cdp = WindowCDP()
        cdp.targets["original-created"] = {"targetId": "original-created", "type": "page",
                                            "url": blank_url(NONCE), "window": 77}
        receipts = []
        result = self.create(cdp, on_created=receipts.append)
        self.assertEqual(result["target_id"], "original-created")
        self.assertFalse(result["created"])
        self.assertTrue(result["recovered_existing_nonce"])
        self.assertEqual(cdp.create_count, 0)
        self.assertFalse(cdp.extension_loaded)

    def test_receipt_loss_recovers_candidate_and_never_repeats_creation(self):
        cdp = WindowCDP()
        cdp.raise_after_create = True
        receipts = []
        with self.assertRaises(TabCreationError) as caught:
            self.create(cdp, on_created=receipts.append)
        self.assertEqual(caught.exception.candidate["target_id"], "new-owned")
        self.assertEqual(receipts[0]["target_id"], "new-owned")
        self.assertEqual(cdp.create_count, 1)
        self.assertFalse(cdp.extension_loaded)
        self.assertTrue(caught.exception.candidate["extension_uninstalled"])

    def test_duplicate_nonce_preserves_all_pages_without_guess_or_creation(self):
        cdp = WindowCDP()
        for tid in ("duplicate-1", "duplicate-2"):
            cdp.targets[tid] = {"targetId": tid, "type": "page", "url": blank_url(NONCE), "window": 77}
        with self.assertRaisesRegex(TabCreationError, "多个页面"):
            self.create(cdp)
        self.assertEqual(cdp.create_count, 0)
        self.assertIn("duplicate-1", cdp.targets)
        self.assertIn("duplicate-2", cdp.targets)

    def test_paused_work_never_installs_extension_or_creates_page(self):
        cdp = WindowCDP()
        with self.assertRaisesRegex(TabCreationError, "已暂停"):
            self.create(cdp, stopping=lambda: True)
        self.assertEqual(cdp.calls, [])
        self.assertEqual(cdp.create_count, 0)

    def test_cleanup_failure_is_reported_with_source_preserved(self):
        cdp = WindowCDP()
        cdp.cleanup_fail = True
        result = self.create(cdp)
        self.assertFalse(result["extension_uninstalled"])
        self.assertIn("cannot unload", result["extension_cleanup_error"])
        self.assertTrue(Path(result["extension_source_path"]).is_dir())
        self.assertEqual(cdp.create_count, 1)

    def test_cleanup_failure_before_any_page_creation_is_still_reported(self):
        cdp = WindowCDP()
        cdp.cleanup_fail = True
        cdp.worker.evaluate = lambda expression: 2
        with self.assertRaises(TabCreationError) as caught:
            self.create(cdp, timeout=0)
        self.assertEqual(cdp.create_count, 0)
        self.assertIsNone(caught.exception.candidate)
        self.assertIn("cannot unload", caught.exception.extension_cleanup_error)
        self.assertTrue(Path(caught.exception.extension_source_path).is_dir())

    def test_metadata_probe_never_loads_or_creates(self):
        cdp = WindowCDP()
        result = probe_support(cdp.browser)
        self.assertEqual(result["state"], "metadata_available")
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["load_verified"])
        self.assertEqual(cdp.calls, [("Extensions.getExtensions", None), ("detach", None)])
        self.assertEqual(cdp.create_count, 0)

    def test_candidate_in_wrong_window_is_not_adopted_moved_or_closed(self):
        cdp = WindowCDP()
        cdp.created_window_id = 999
        user_before = {tid: dict(target) for tid, target in cdp.targets.items() if tid.startswith("user-")}
        receipts = []
        with self.assertRaisesRegex(TabCreationError, "不在原专用窗口") as caught:
            self.create(cdp, on_created=receipts.append)
        self.assertEqual(caught.exception.candidate["window_id"], 999)
        self.assertEqual(receipts, [])
        self.assertEqual(cdp.create_count, 1)
        self.assertIn("new-owned", cdp.targets)
        self.assertFalse(cdp.extension_loaded)
        self.assertEqual(user_before, {tid: target for tid, target in cdp.targets.items() if tid.startswith("user-")})

    def test_foreign_tab_enters_during_create_preserves_every_page_and_blocks_adoption(self):
        cdp = WindowCDP()
        cdp.foreign_enters_during_create = True
        receipts = []
        with self.assertRaisesRegex(TabCreationError, "专用窗口页面变化") as caught:
            self.create(cdp, on_created=receipts.append)
        self.assertEqual(caught.exception.candidate["target_id"], "new-owned")
        self.assertEqual(receipts[0]["target_id"], "new-owned")
        self.assertEqual(len(cdp.targets), 35)
        self.assertEqual(cdp.create_count, 1)
        self.assertFalse(cdp.extension_loaded)

    def test_unexpected_active_candidate_is_preserved_without_second_creation(self):
        cdp = WindowCDP()
        cdp.created_active = True
        with self.assertRaisesRegex(TabCreationError, "后台状态未通过") as caught:
            self.create(cdp)
        self.assertEqual(caught.exception.candidate["target_id"], "new-owned")
        self.assertEqual(cdp.create_count, 1)
        self.assertIn("new-owned", cdp.targets)
        self.assertFalse(cdp.extension_loaded)

    def test_invalid_nonce_cannot_be_interpolated_into_a_page_creation(self):
        cdp = WindowCDP()
        with self.assertRaises(TabCreationError):
            create_in_window(cdp.browser, 77, root=self.folder.name,
                             nonce="';chrome.tabs.create({});'", owned_ids=cdp.owned)
        self.assertEqual(cdp.calls, [])
        self.assertEqual(cdp.create_count, 0)


if __name__ == "__main__":
    unittest.main()
