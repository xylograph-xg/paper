"""Exercise owner guards using temporary ledgers and read-only CDP doubles."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from core.api import paths__WorkspacePath as Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from browser import shared_window_owner as owner
from browser.shared_browser_window import WindowIsolationError


def inventory():
    targets = {f"owned-{index:02d}": {
        "target_id": f"owned-{index:02d}", "window_id": 77,
        "url": "https://chatgpt.com/", "type": "page",
    } for index in range(20)}
    return {"targets": targets, "total_pages": 20, "complete": True, "errors": []}


class SharedWindowOwner(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {"catalog_path": str(self.root / "catalog.sqlite"),
                       "web_cards": {"shared_window": {"enabled": True, "slot_count": 20}}}
        self.entries = {tid: {"state": "ready_blank"} for tid in inventory()["targets"]}
        self.browser = Mock(spec=["new_browser_cdp_session"])
        self.environment = patch.dict(os.environ, {"WEB_GPT_CDP_URL": "http://127.0.0.1:9222"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def observe(self, live=None):
        with patch.object(owner, "read_window_inventory", return_value=deepcopy(live or inventory())):
            return owner.observe(self.config, self.browser, self.entries)

    def manifest(self):
        return json.loads(owner.registry_path(self.config).read_text())

    def test_first_registration_preserves_existing_twenty_pages(self):
        report = self.observe()
        registry = self.manifest()
        self.assertEqual(registry["window_id"], 77)
        self.assertEqual(registry["endpoint"], "http://127.0.0.1:9222")
        self.assertEqual(len(registry["slots"]), 20)
        self.assertEqual([slot["target_id"] for slot in registry["slots"]], sorted(self.entries))
        self.assertEqual(report["state"], "ready")
        self.assertEqual(report["live_fixed_slots"], 20)
        self.assertTrue((self.root / "shared-gpt-window-status.json").is_file())
        self.browser.new_browser_cdp_session.assert_not_called()

    def test_fifteen_other_window_user_pages_do_not_consume_fixed_slots(self):
        live = inventory()
        for index in range(15):
            tid = f"user-{index:02d}"
            live["targets"][tid] = {"target_id": tid, "window_id": 999,
                                     "url": "https://chatgpt.com/c/user"}
        live["total_pages"] = 35
        report = self.observe(live)
        self.assertEqual(report["state"], "ready")
        self.assertEqual(len(report["eligible_target_ids"]), 20)
        self.assertEqual(report["other_window_pages"], 15)
        self.assertEqual(report["browser_total_pages"], 35)
        self.assertFalse(any(tid.startswith("user-") for tid in report["collect_target_ids"]))
        self.assertFalse(any(slot["target_id"].startswith("user-") for slot in self.manifest()["slots"]))

    def test_missing_page_keeps_original_manifest_and_waits_without_create(self):
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        live = inventory()
        live["targets"].pop("owned-03")
        live["total_pages"] = 19
        report = self.observe(live)
        self.assertEqual(report["state"], "waiting_missing_slots")
        self.assertEqual(report["missing_slot_ids"], ["04"])
        self.assertEqual(report["slots"][3]["target_id"], "owned-03")
        self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)
        self.assertEqual(report["live_fixed_slots"], 19)
        self.browser.new_browser_cdp_session.assert_not_called()

    def test_moved_page_keeps_fixed_target_and_is_collect_only(self):
        self.entries["owned-00"]["state"] = "busy"
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        live = inventory()
        live["targets"]["owned-00"]["window_id"] = 999
        report = self.observe(live)
        self.assertEqual(report["state"], "waiting_window_mismatch")
        self.assertEqual(report["collect_only_target_ids"], ["owned-00"])
        self.assertNotIn("owned-00", report["eligible_target_ids"])
        self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)

    def test_malformed_registry_is_preserved_instead_of_automatically_rebuilt(self):
        path = owner.registry_path(self.config)
        original_bytes = b'{"schema_version":'
        path.write_bytes(original_bytes)
        with self.assertRaises(ValueError):
            self.observe()
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertFalse((self.root / "shared-gpt-window-status.json").exists())

    def test_duplicate_target_registry_blocks_and_preserves_prior_status(self):
        self.observe()
        status = (self.root / "shared-gpt-window-status.json").read_bytes()
        registry = self.manifest()
        registry["slots"][1]["target_id"] = registry["slots"][0]["target_id"]
        path = owner.registry_path(self.config)
        path.write_text(json.dumps(registry))
        original_bytes = path.read_bytes()
        with self.assertRaisesRegex(WindowIsolationError, "重复"):
            self.observe()
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual((self.root / "shared-gpt-window-status.json").read_bytes(), status)

    def test_endpoint_change_blocks_observation_without_replacing_registry(self):
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        with patch.dict(os.environ, {"WEB_GPT_CDP_URL": "http://127.0.0.1:9333"}):
            with self.assertRaisesRegex(WindowIsolationError, "连接地址.*变化"):
                self.observe()
        self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)

    def test_require_slot_rejects_moved_original_page_and_detaches_read_session(self):
        self.observe()
        session = self.browser.new_browser_cdp_session.return_value
        session.send.return_value = {"windowId": 999}
        with self.assertRaisesRegex(WindowIsolationError, "移出专用窗口"):
            owner.require_slot(self.config, self.browser, "owned-00")
        session.send.assert_called_once_with("Browser.getWindowForTarget", {"targetId": "owned-00"})
        session.detach.assert_called_once()

    def test_require_slot_never_looks_up_unregistered_user_page(self):
        self.observe()
        with self.assertRaisesRegex(WindowIsolationError, "不在20个固定槽位"):
            owner.require_slot(self.config, self.browser, "user-page")
        self.browser.new_browser_cdp_session.assert_not_called()

    def test_other_slot_replacement_during_position_query_does_not_revoke_original_slot(self):
        self.observe();session=self.browser.new_browser_cdp_session.return_value
        def position(*args):
            path=owner.registry_path(self.config);record=json.loads(path.read_text())
            record['revision']=record.get('revision',0)+1;record['slots'][1]['target_id']='verified-replacement'
            path.write_text(json.dumps(record));return {'windowId':77}
        session.send.side_effect=position
        self.assertTrue(owner.require_slot(self.config,self.browser,'owned-00'))

    def test_original_slot_change_during_position_query_still_blocks(self):
        self.observe();session=self.browser.new_browser_cdp_session.return_value
        def position(*args):
            path=owner.registry_path(self.config);record=json.loads(path.read_text())
            record['slots'][0]['target_id']='different-original';path.write_text(json.dumps(record))
            return {'windowId':77}
        session.send.side_effect=position
        with self.assertRaisesRegex(WindowIsolationError,'登记变化'):
            owner.require_slot(self.config,self.browser,'owned-00')

    def test_require_slot_rechecks_endpoint_before_reading_or_mutating_page(self):
        self.observe()
        self.browser.new_browser_cdp_session.return_value.send.return_value = {"windowId": 77}
        with patch.dict(os.environ, {"WEB_GPT_CDP_URL": "http://127.0.0.1:9333"}):
            with self.assertRaisesRegex(WindowIsolationError, "连接地址.*变化"):
                owner.require_slot(self.config, self.browser, "owned-00")
        self.browser.new_browser_cdp_session.assert_not_called()

    def test_missing_or_non_string_endpoint_blocks_observation_without_rebuild(self):
        self.observe()
        original_registry = self.manifest()
        path = owner.registry_path(self.config)
        for value in (None, 9222, {"url": "http://127.0.0.1:9222"}):
            with self.subTest(endpoint=value):
                malformed = deepcopy(original_registry)
                if value is None:
                    malformed.pop("endpoint")
                else:
                    malformed["endpoint"] = value
                path.write_text(json.dumps(malformed))
                original_bytes = path.read_bytes()
                with self.assertRaisesRegex(WindowIsolationError, "连接地址缺失或变化"):
                    self.observe()
                self.assertEqual(path.read_bytes(), original_bytes)

    def test_missing_or_non_string_endpoint_blocks_slot_before_cdp_lookup(self):
        self.observe()
        original_registry = self.manifest()
        path = owner.registry_path(self.config)
        for value in (None, False, ["http://127.0.0.1:9222"]):
            with self.subTest(endpoint=value):
                malformed = deepcopy(original_registry)
                if value is None:
                    malformed.pop("endpoint")
                else:
                    malformed["endpoint"] = value
                path.write_text(json.dumps(malformed))
                with self.assertRaisesRegex(WindowIsolationError, "连接地址缺失或变化"):
                    owner.require_slot(self.config, self.browser, "owned-00")
        self.browser.new_browser_cdp_session.assert_not_called()

    def test_moved_finished_or_blank_slot_is_metadata_only_without_dom_requests(self):
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        live = inventory()
        live["targets"]["owned-00"]["window_id"] = 999

        def send(method, params=None):
            if method == "Target.getTargets":
                return {"targetInfos": [{"targetId": tid, "type": "page", "url": target["url"]}
                                        for tid, target in live["targets"].items()]}
            if method == "Browser.getWindowForTarget":
                return {"windowId": live["targets"][params["targetId"]]["window_id"]}
            self.fail("Unexpected CDP mutation or DOM request: " + method)

        for state in ("ready_blank", "ready"):
            with self.subTest(state=state):
                self.entries["owned-00"]["state"] = state
                session = Mock()
                session.send.side_effect = send
                self.browser.new_browser_cdp_session.return_value = session
                report = owner.observe(self.config, self.browser, self.entries)
                self.assertNotIn("owned-00", report["eligible_target_ids"])
                self.assertNotIn("owned-00", report["collect_target_ids"])
                self.assertNotIn("owned-00", report["collect_only_target_ids"])
                self.assertEqual(report["slots"][0]["target_id"], "owned-00")
                self.assertEqual(report["slots"][0]["state"], "outside_window")
                self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)
                self.assertEqual({call.args[0] for call in session.send.call_args_list},
                                 {"Target.getTargets", "Browser.getWindowForTarget"})
                session.detach.assert_called_once()

    def test_historical_sent_page_is_collect_only_never_reused_or_added_to_slots(self):
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        live = inventory()
        live["targets"]["historical"] = {"target_id": "historical", "window_id": 999,
                                           "url": "https://chatgpt.com/c/original"}
        live["total_pages"] = 21
        self.entries["historical"] = {"state": "submission_started", "paper_id": "original-paper"}
        report = self.observe(live)
        self.assertIn("historical", report["collect_target_ids"])
        self.assertIn("historical", report["collect_only_target_ids"])
        self.assertNotIn("historical", report["eligible_target_ids"])
        self.assertFalse(any(slot["target_id"] == "historical" for slot in report["slots"]))
        self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)

    def test_maintenance_request_checks_manifest_without_creating_any_page(self):
        self.observe()
        original_bytes = owner.registry_path(self.config).read_bytes()
        request = self.root / "shared-window-maintenance-request.json"
        request.write_text(json.dumps({"state": "pending",
                                       "manifest_sha256": hashlib.sha256(original_bytes).hexdigest()}))
        self.observe()
        receipt = json.loads(request.read_text())
        self.assertEqual(receipt["state"], "checked")
        self.assertEqual(receipt["created_pages"], 0)
        self.assertEqual(owner.registry_path(self.config).read_bytes(), original_bytes)
        self.browser.new_browser_cdp_session.assert_not_called()

    def reusable_page(self, *, url="https://chatgpt.com/c/original", users=1,
                      answers=("完整原回答 α",), draft="", streaming=False):
        """Only expose read operations; navigation/close calls cannot succeed."""
        from browser.web_card_pool import USER
        page = Mock(spec=["url", "locator"])
        page.url = url
        user_locator = Mock()
        user_locator.count.return_value = users
        answer_locator = Mock()
        answer_locator.count.return_value = len(answers)
        answer_locator.last = SimpleNamespace(text=answers[-1] if answers else "")
        stop_locator = Mock()
        stop_locator.count.return_value = 1 if streaming else 0
        stop_locator.nth.return_value.is_visible.return_value = streaming
        page.locator.side_effect = {"test-answer": answer_locator,
                                    "test-stop": stop_locator, USER: user_locator}.__getitem__
        core = ModuleType("web_gpt.core")
        core.ANSWER = "test-answer"
        core.STOP_BUTTON = "test-stop"
        core._message_text = lambda answer: answer.text
        core.wait_prompt_box = lambda current, timeout: SimpleNamespace(text=draft)
        core._box_text = lambda box: box.text
        package = ModuleType("web_gpt")
        package.core = core
        modules = {"web_gpt": package, "web_gpt.core": core}
        return page, modules

    def saved_entry(self):
        raw = self.root / "response-raw.txt"
        raw.write_text("完整原回答 α", encoding="utf-8")
        return {"state": "ready", "raw_path": str(raw),
                "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "conversation_url": "https://chatgpt.com/c/original"}

    def test_saved_reply_is_reusable_only_with_unchanged_file_live_hash_and_url(self):
        page, modules = self.reusable_page()
        entry = self.saved_entry()
        with patch.dict(sys.modules, modules):
            self.assertTrue(owner.require_reusable(page, entry))

    def test_empty_saved_file_and_matching_empty_element_are_not_reusable(self):
        page, modules = self.reusable_page(answers=("",))
        entry = self.saved_entry()
        Path(entry['raw_path']).write_bytes(b'')
        entry['raw_sha256'] = hashlib.sha256(b'').hexdigest()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, '空占位'):
                owner.require_reusable(page, entry)

    def test_new_draft_blocks_reuse_of_completed_response(self):
        page, modules = self.reusable_page(draft="用户正在写的新问题")
        entry = self.saved_entry()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "有草稿"):
                owner.require_reusable(page, entry)

    def test_streaming_blocks_reuse_even_if_current_answer_matches_saved_file(self):
        page, modules = self.reusable_page(streaming=True)
        entry = self.saved_entry()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "生成或未收齐"):
                owner.require_reusable(page, entry)

    def test_ready_blank_with_user_history_is_not_proof_of_unused_page(self):
        page, modules = self.reusable_page(url="https://chatgpt.com/", users=1, answers=())
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "未收齐回执"):
                owner.require_reusable(page, {"state": "ready_blank"})

    def test_ready_blank_requires_absence_of_draft_and_answers(self):
        cases = [{"draft": "新草稿", "answers": ()},
                 {"draft": "", "answers": ("旧回答",)}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                page, modules = self.reusable_page(url="https://chatgpt.com/", users=0, **kwargs)
                with patch.dict(sys.modules, modules):
                    with self.assertRaises(WindowIsolationError):
                        owner.require_reusable(page, {"state": "ready_blank"})

    def test_actual_unused_blank_page_can_be_reused(self):
        page, modules = self.reusable_page(url="https://chatgpt.com/", users=0, answers=())
        with patch.dict(sys.modules, modules):
            self.assertTrue(owner.require_reusable(page, {"state": "ready_blank"}))

    def test_temporary_home_only_with_formula_opt_in_and_no_history(self):
        url = "https://chatgpt.com/?temporary-chat=true"
        for users in (0,1):
            page, modules = self.reusable_page(url=url, users=users, answers=())
            with patch.dict(sys.modules, modules):
                with self.assertRaises(WindowIsolationError):
                    owner.require_reusable(page, {"state":"ready_blank"})
                if users:
                    with self.assertRaises(WindowIsolationError):
                        owner.require_reusable(page, {"state":"ready_blank"},allow_temporary_home=True)
                else:
                    self.assertTrue(owner.require_reusable(page, {"state":"ready_blank"},allow_temporary_home=True))

    def test_saved_response_live_text_change_blocks_reuse(self):
        page, modules = self.reusable_page(answers=("原回答被修改",))
        entry = self.saved_entry()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "未收齐回执"):
                owner.require_reusable(page, entry)

    def test_saved_response_file_change_blocks_reuse(self):
        page, modules = self.reusable_page()
        entry = self.saved_entry()
        Path(entry["raw_path"]).write_text("存档文件被修改", encoding="utf-8")
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "原回答指纹"):
                owner.require_reusable(page, entry)

    def test_missing_saved_file_protects_this_page_with_an_isolation_error(self):
        page, modules = self.reusable_page()
        entry = self.saved_entry()
        Path(entry['raw_path']).unlink()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError,'路径不可读取'):
                owner.require_reusable(page,entry)

    def test_original_conversation_url_change_blocks_reuse(self):
        page, modules = self.reusable_page(url="https://chatgpt.com/c/different")
        entry = self.saved_entry()
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowIsolationError, "会话URL变化"):
                owner.require_reusable(page, entry)


if __name__ == "__main__":
    unittest.main()
