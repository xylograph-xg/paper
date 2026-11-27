"""Read-only window isolation and stable slots for the shared GPT page pool.

Chrome CDP exposes ``Browser.getWindowForTarget`` but ``Target.createTarget``
does not accept a destination window id.  This module therefore never opens,
moves, focuses or closes a page.  Missing slots wait for explicit, independently
verified enrollment instead of guessing the most recently used Chrome window.

Ownership is supplied by the caller's material/adoption ledger.  A ChatGPT URL
or matching window id alone never proves ownership.  Business readiness,
submission locks, response evidence and pause controls remain caller concerns.
The new shared mode limits the dedicated window to 20 slots; pages in other
windows are counted as metadata but do not consume those slots.  An explicit
``max_total_pages`` retains the former browser-wide limit for legacy callers.
"""
from copy import deepcopy
import time
from .owner_browser_calls import bounded_call, _metadata_session


SCHEMA_VERSION = 1
FIXED_SLOT_COUNT = 20


class WindowIsolationError(ValueError):
    """The observed window cannot safely be enrolled or used for new sends."""


def enabled(config):
    """Read the shared-window switch without changing pause or runtime state."""
    policy = config.get("web_cards", {}).get("shared_window", {})
    if not isinstance(policy, dict):
        raise WindowIsolationError("共享窗口配置损坏")
    if not policy.get("enabled", False):
        return False
    count = policy.get("slot_count", FIXED_SLOT_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or count != FIXED_SLOT_COUNT:
        raise WindowIsolationError("共享窗口固定槽位数必须为20")
    return True


def _valid_window_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _owned_set(owned_ids):
    return {str(tid) for tid in owned_ids if tid}


def snapshot_windows(session):
    """Read page ids and window ids through the owner's browser CDP session.

    Return a JSON-compatible snapshot.  Any failed per-page lookup marks the
    entire snapshot incomplete; successfully read targets remain available for
    original-response collection, while new submissions must wait.
    """
    result = {"targets": {}, "total_pages": 0, "complete": True, "errors": []}
    deadline=time.monotonic()+10
    try:
        infos = bounded_call(session,"send","Target.getTargets")["targetInfos"]
        if not isinstance(infos, list):
            raise WindowIsolationError("页面清单格式不正确")
    except Exception as exc:
        result.update(complete=False, errors=["窗口页面清单不可读：" + str(exc)[:200]])
        return result
    pages = [info for info in infos if info.get("type") == "page"]
    result["total_pages"] = len(pages)
    for info in pages:
        tid = info.get("targetId")
        try:
            if not isinstance(tid, str) or not tid or tid in result["targets"]:
                raise WindowIsolationError("缺少或重复页面 target_id")
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('窗口盘点超过10秒，保留未观测页面')
            response = bounded_call(session,"send","Browser.getWindowForTarget", {"targetId": tid},timeout=min(3,remaining))
            wid = response.get("windowId")
            if not _valid_window_id(wid):
                raise WindowIsolationError("窗口标识不可核对")
            result["targets"][tid] = {
                "target_id": tid, "window_id": wid,
                "url": info.get("url", ""), "type": "page",
            }
        except Exception as exc:
            result["complete"] = False
            result["errors"].append(str(tid) + "：" + str(exc)[:200])
    return result


def read_window_inventory(browser):
    """Read through the existing Playwright connection; never create a browser."""
    with _metadata_session(browser) as session:
        return snapshot_windows(session)


def _checked_inventory(inventory):
    targets = inventory.get("targets")
    if not isinstance(targets, dict):
        raise WindowIsolationError("窗口清单缺失")
    for tid, target in targets.items():
        if (not isinstance(tid, str) or not tid
                or not isinstance(target, dict)
                or target.get("target_id", tid) != tid
                or not _valid_window_id(target.get("window_id"))):
            raise WindowIsolationError("窗口清单损坏")
    total = inventory.get("total_pages")
    if isinstance(total, bool) or not isinstance(total, int) or total < len(targets):
        raise WindowIsolationError("浏览器页面总数不可核对")
    if inventory.get("complete") and total != len(targets):
        raise WindowIsolationError("完整清单的页面总数不一致")
    return targets, total


def validate_registry(registry):
    """Reject corrupt slot state before a caller dispatches any new material."""
    if (isinstance(registry.get("schema_version"), bool)
            or registry.get("schema_version") != SCHEMA_VERSION):
        raise WindowIsolationError("固定窗口登记版本不支持")
    if not _valid_window_id(registry.get("window_id")):
        raise WindowIsolationError("固定窗口标识缺失")
    slots = registry.get("slots")
    if not isinstance(slots, list) or len(slots) != FIXED_SLOT_COUNT:
        raise WindowIsolationError("固定槽位必须恰好20个")
    slot_ids = set()
    target_ids = set()
    for index, slot in enumerate(slots, 1):
        if not isinstance(slot, dict) or slot.get("slot_id") != f"{index:02d}":
            raise WindowIsolationError("固定槽位编号损坏")
        sid = slot["slot_id"]
        tid = slot.get("target_id")
        if sid in slot_ids or tid is not None and (
                not isinstance(tid, str) or not tid or tid in target_ids):
            raise WindowIsolationError("固定槽位目标重复或损坏")
        slot_ids.add(sid)
        if tid is not None:
            target_ids.add(tid)
    return registry


def register_window(inventory, owned_ids, *, window_id=None, max_total_pages=None):
    """Enroll an already verified exclusive window, preserving its page ids.

    Without ``window_id`` exactly one window containing live owned pages must
    exist.  The selected window may contain fewer than 20 pages: unfilled slots
    remain explicit waiting slots.  No foreign page is adopted or moved.  The
    caller must archive this first registration and separately verify material
    receipts before later binding a recovered target to an old slot.
    """
    targets, total = _checked_inventory(inventory)
    if not inventory.get("complete") or inventory.get("errors"):
        raise WindowIsolationError("实时窗口清单不完整，不登记专用窗口")
    if max_total_pages is not None and total > max_total_pages:
        raise WindowIsolationError("浏览器总页面超过上限，保留页面等待核对")
    owned = _owned_set(owned_ids)
    windows = {target["window_id"] for tid, target in targets.items() if tid in owned}
    if window_id is None:
        if len(windows) != 1:
            raise WindowIsolationError("本任务实时页面不在唯一窗口，不猜测专用窗口")
        window_id = next(iter(windows))
    if not _valid_window_id(window_id) or window_id not in windows:
        raise WindowIsolationError("指定窗口没有已核对的本任务页面")
    selected = sorted(tid for tid, target in targets.items()
                      if target["window_id"] == window_id)
    if any(tid not in owned for tid in selected):
        raise WindowIsolationError("指定窗口含其他项目或用户页面，不自动接管")
    if len(selected) > FIXED_SLOT_COUNT:
        raise WindowIsolationError("专用窗口页面超过20个，不自动关闭或合并")
    slots = [{"slot_id": f"{index + 1:02d}",
              "target_id": selected[index] if index < len(selected) else None}
             for index in range(FIXED_SLOT_COUNT)]
    registry = {"schema_version": SCHEMA_VERSION, "window_id": window_id,
                "slots": slots, "creation_policy": "explicit_verified_enrollment_only"}
    validate_registry(registry)
    return reconcile_window(registry, inventory, owned, max_total_pages=max_total_pages)


def reconcile_window(registry, inventory, owned_ids, *, max_total_pages=None):
    """Return stable slots and explicit dispatch/collection boundaries.

    ``eligible_target_ids`` only admits registered, owned pages still inside the
    enrolled window.  ``collect_only_target_ids`` identifies registered owned
    pages moved to another window; the caller may collect the original request
    after its usual identity checks but must never navigate/reuse those pages.
    No vanished id is silently replaced by a blank page.  A foreign page inside
    the enrolled window, an incomplete inventory or more than 20 pages in that
    window blocks all new sends while preserving collection targets and all
    original ids.  Other windows are observed through CDP metadata alone and
    do not consume the dedicated window's fixed slots.
    """
    validate_registry(registry)
    targets, total = _checked_inventory(inventory)
    owned = _owned_set(owned_ids)
    result = deepcopy(registry)
    window_id = result["window_id"]
    eligible = []
    collect_only = []
    collect = []
    missing = []
    ownership_lost = []
    assigned = {slot["target_id"] for slot in result["slots"] if slot.get("target_id")}
    for slot in result["slots"]:
        tid = slot.get("target_id")
        if tid is None or tid not in targets:
            slot["state"] = "unfilled" if tid is None else "missing"
            missing.append(slot["slot_id"])
        elif tid not in owned:
            slot["state"] = "ownership_lost"
            ownership_lost.append(tid)
        elif targets[tid]["window_id"] != window_id:
            slot["state"] = "outside_window"
            collect_only.append(tid)
            collect.append(tid)
        else:
            slot["state"] = "present"
            eligible.append(tid)
            collect.append(tid)
    foreign = sorted(tid for tid, target in targets.items()
                     if target["window_id"] == window_id and tid not in owned)
    unassigned = sorted(tid for tid, target in targets.items()
                        if target["window_id"] == window_id and tid in owned
                        and tid not in assigned)
    errors = list(inventory.get("errors", []))
    dedicated_count = sum(target["window_id"] == window_id for target in targets.values())
    if not inventory.get("complete"):
        errors.append("实时窗口清单不完整；暂停新增分配，保留原请求收取")
    if max_total_pages is not None and total > max_total_pages:
        errors.append("浏览器总页面超过上限；不关闭他人页面")
    if dedicated_count > FIXED_SLOT_COUNT:
        errors.append("专用窗口页面超过20个；不自动关闭或移动")
    if foreign:
        errors.append("专用窗口含非本任务页面；不接管或移动")
    if unassigned:
        errors.append("专用窗口出现未登记本任务页面；不自动替换固定槽位")
    if ownership_lost:
        errors.append("固定槽位页面归属无法确认")
    blocked = bool(errors)
    result.update(
        state="needs_inspection" if blocked else "waiting_window_mismatch" if collect_only
        else "waiting_missing_slots" if missing else "ready",
        eligible_target_ids=[] if blocked else eligible,
        collect_target_ids=collect, collect_only_target_ids=collect_only,
        missing_slot_ids=missing, foreign_window_target_ids=foreign,
        unassigned_owned_target_ids=unassigned, ownership_lost_target_ids=ownership_lost,
        live_total_pages=total, inventory_complete=bool(inventory.get("complete")),
        browser_total_pages=total, dedicated_window_pages=dedicated_count,
        other_window_pages=total - dedicated_count,
        errors=errors,
    )
    return result
