import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from browser.shared_browser_window import WindowIsolationError, enabled, read_window_inventory, reconcile_window, register_window, snapshot_windows, validate_registry


def inventory(count=20, window_id=77):
    targets = {f"target-{index:02d}": {
        "target_id": f"target-{index:02d}", "window_id": window_id,
        "url": "https://chatgpt.com/", "type": "page",
    } for index in range(count)}
    return {"targets": targets, "total_pages": count, "complete": True, "errors": []}


class SharedBrowserWindow(unittest.TestCase):
    def test_switch_keeps_fixed_twenty_slot_contract(self):
        self.assertFalse(enabled({}))
        self.assertTrue(enabled({"web_cards": {"shared_window": {"enabled": True, "slot_count": 20}}}))
        with self.assertRaisesRegex(WindowIsolationError, "必须为20"):
            enabled({"web_cards": {"shared_window": {"enabled": True, "slot_count": 19}}})

    def test_existing_twenty_owned_pages_enroll_without_cdp_mutations(self):
        live = inventory()
        result = register_window(live, set(live["targets"]))
        self.assertEqual(result["state"], "ready")
        self.assertEqual(len(result["slots"]), 20)
        self.assertEqual(result["eligible_target_ids"], sorted(live["targets"]))
        self.assertEqual(result["slots"][0]["slot_id"], "01")
        self.assertEqual(result["window_id"], 77)

    def test_foreign_page_in_same_window_cannot_be_adopted_even_chatgpt(self):
        live = inventory()
        with self.assertRaisesRegex(WindowIsolationError, "其他项目或用户页面"):
            register_window(live, set(live["targets"]) - {"target-00"})

    def test_multiple_owned_windows_requires_explicit_enrollment(self):
        live = inventory(4)
        live["targets"]["target-00"]["window_id"] = 88
        with self.assertRaisesRegex(WindowIsolationError, "不在唯一窗口"):
            register_window(live, set(live["targets"]))
        registered = register_window(live, set(live["targets"]), window_id=77)
        self.assertNotIn("target-00", registered["eligible_target_ids"])
        self.assertEqual(len(registered["slots"]), 20)

    def test_missing_page_preserves_target_and_slot_never_refills_by_blank_url(self):
        before = inventory()
        original = register_window(before, set(before["targets"]))
        live = inventory()
        live["targets"].pop("target-04")
        live["total_pages"] -= 1
        result = reconcile_window(original, live, set(before["targets"]))
        self.assertEqual(result["state"], "waiting_missing_slots")
        self.assertEqual(result["slots"][4], {
            "slot_id": "05", "target_id": "target-04", "state": "missing"})
        self.assertEqual(result["missing_slot_ids"], ["05"])
        self.assertEqual(len(result["eligible_target_ids"]), 19)
        live["targets"]["replacement"] = {"target_id": "replacement", "window_id": 77,
                                             "url": "https://chatgpt.com/"}
        live["total_pages"] += 1
        blocked = reconcile_window(original, live, set(before["targets"]))
        self.assertEqual(blocked["state"], "needs_inspection")
        self.assertEqual(blocked["eligible_target_ids"], [])
        self.assertEqual(blocked["slots"][4]["target_id"], "target-04")

    def test_moved_original_page_is_collect_only_and_keeps_its_target(self):
        live = inventory()
        owned = set(live["targets"])
        registered = register_window(live, owned)
        live["targets"]["target-00"]["window_id"] = 88
        result = reconcile_window(registered, live, owned)
        self.assertEqual(result["collect_only_target_ids"], ["target-00"])
        self.assertIn("target-00", result["collect_target_ids"])
        self.assertNotIn("target-00", result["eligible_target_ids"])
        self.assertEqual(result["slots"][0]["target_id"], "target-00")
        self.assertEqual(result["slots"][0]["state"], "outside_window")
        self.assertEqual(result["state"], "waiting_window_mismatch")

    def test_incomplete_inventory_blocks_new_submissions_but_preserves_collection(self):
        live = inventory()
        owned = set(live["targets"])
        registered = register_window(live, owned)
        live["complete"] = False
        live["errors"] = ["target vanished"]
        result = reconcile_window(registered, live, owned)
        self.assertEqual(result["eligible_target_ids"], [])
        self.assertEqual(len(result["collect_target_ids"]), 20)
        self.assertEqual(result["state"], "needs_inspection")
        with self.assertRaisesRegex(WindowIsolationError, "不完整"):
            register_window(live, owned)

    def test_user_page_elsewhere_is_untouched_and_legacy_global_cap_is_optional(self):
        live = inventory(19)
        owned = set(live["targets"])
        registered = register_window(live, owned)
        live["targets"]["user"] = {"target_id": "user", "window_id": 999,
                                     "url": "https://chatgpt.com/c/user"}
        live["total_pages"] = 20
        result = reconcile_window(registered, live, owned, max_total_pages=20)
        self.assertEqual(len(result["eligible_target_ids"]), 19)
        self.assertNotIn("user", result["collect_target_ids"])
        live["targets"]["other-project"] = {"target_id": "other-project", "window_id": 999}
        live["total_pages"] = 21
        result = reconcile_window(registered, live, owned, max_total_pages=20)
        self.assertEqual(result["eligible_target_ids"], [])
        self.assertEqual(len(result["collect_target_ids"]), 19)

    def test_fifteen_user_pages_elsewhere_do_not_consume_twenty_dedicated_slots(self):
        live = inventory()
        owned = set(live["targets"])
        for index in range(15):
            tid = f"user-{index:02d}"
            live["targets"][tid] = {"target_id": tid, "window_id": 999,
                                     "url": "https://chatgpt.com/c/user"}
        live["total_pages"] = 35
        registered = register_window(live, owned)
        result = reconcile_window(registered, live, owned)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(len(result["eligible_target_ids"]), 20)
        self.assertEqual(result["browser_total_pages"], 35)
        self.assertEqual(result["dedicated_window_pages"], 20)
        self.assertEqual(result["other_window_pages"], 15)
        self.assertFalse(any(tid.startswith("user-") for tid in result["collect_target_ids"]))

    def test_new_owned_unregistered_page_cannot_silently_replace_slot(self):
        live = inventory(19)
        owned = set(live["targets"])
        registered = register_window(live, owned)
        live["targets"]["new"] = {"target_id": "new", "window_id": 77}
        live["total_pages"] = 20
        result = reconcile_window(registered, live, owned | {"new"})
        self.assertEqual(result["eligible_target_ids"], [])
        self.assertEqual(result["unassigned_owned_target_ids"], ["new"])
        self.assertIsNone(result["slots"][-1]["target_id"])

    def test_corrupt_duplicate_slot_id_fails_closed(self):
        live = inventory()
        registered = register_window(live, set(live["targets"]))
        registered["slots"][1]["target_id"] = registered["slots"][0]["target_id"]
        with self.assertRaisesRegex(WindowIsolationError, "重复"):
            validate_registry(registered)

    def test_snapshot_reads_exact_window_ids_and_ignores_worker_targets(self):
        session = Mock()
        session.send.side_effect = [
            {"targetInfos": [{"targetId": "a", "type": "page", "url": "https://chatgpt.com/"},
                             {"targetId": "worker", "type": "service_worker"}]},
            {"windowId": 123},
        ]
        result = snapshot_windows(session)
        self.assertEqual(result["targets"]["a"]["window_id"], 123)
        self.assertEqual(result["total_pages"], 1)
        self.assertTrue(result["complete"])
        self.assertEqual([call.args[0] for call in session.send.call_args_list],
                         ["Target.getTargets", "Browser.getWindowForTarget"])

    def test_unsupported_window_lookup_blocks_without_creation_focus_or_close(self):
        session = Mock()
        session.send.side_effect = [
            {"targetInfos": [{"targetId": "a", "type": "page"}]},
            RuntimeError("method unavailable"),
        ]
        browser = SimpleNamespace(new_browser_cdp_session=lambda: session)
        result = read_window_inventory(browser)
        self.assertFalse(result["complete"])
        self.assertEqual(result["total_pages"], 1)
        session.detach.assert_called_once()
        self.assertEqual([call.args[0] for call in session.send.call_args_list],
                         ["Target.getTargets", "Browser.getWindowForTarget"])


if __name__ == "__main__":
    unittest.main()
