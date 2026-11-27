"""Create one inactive tab in an exact Chrome window through a temporary worker.

The caller is the existing CDP owner and must hold the shared submission lock,
archive/close the obsolete owned page first, and durably journal ``nonce`` before
calling.  The initial blank URL provides attribution after an uncertain reply or
crash.  This module never selects the current window, activates a tab, navigates
an existing page, sends materials, or falls back to ``window.open``.

The transient Manifest V3 extension has no permissions, host permissions,
content scripts or listeners that open pages.  ``chrome.tabs.create`` receives
an explicit windowId and active:false.  Extension removal is always attempted.
"""
import json
import re
import shutil
import tempfile
import time
from core.api import paths__WorkspacePath as Path

from .shared_browser_window import WindowIsolationError, snapshot_windows
from .owner_browser_calls import bounded_call


MANIFEST = {"manifest_version": 3, "name": "Paper fixed-window slot helper",
            "version": "1.0", "background": {"service_worker": "worker.js"}}
WORKER_SOURCE = "globalThis.paperSharedSlotVersion = 1; chrome.runtime.onInstalled.addListener(() => {});\n"
CREATE_EXPRESSION = """async (props) => {
  const tabs = await chrome.tabs.query({windowId: props.windowId});
  if (tabs.length >= 20) throw new Error('Dedicated window already has 20 pages');
  const tab = await chrome.tabs.create({windowId: props.windowId, active: false, url: props.url});
  return {id: tab.id, windowId: tab.windowId, active: tab.active};
}"""


class TabCreationError(WindowIsolationError):
    def __init__(self, message, candidate=None):
        super().__init__(message)
        self.candidate = candidate
        self.extension_cleanup_error = None
        self.extension_source_path = None


def blank_url(nonce):
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", nonce):
        raise TabCreationError("补页nonce必须为已持久保存的唯一12–80位标识")
    return "about:blank#paper-slot-" + nonce


def probe_support(browser):
    """Check protocol metadata only; do not install an extension or open a tab.

    A successful read does not prove that loadUnpacked is enabled in this Chrome
    configuration.  Creation still fails closed if actual installation fails.
    """
    session = bounded_call(browser,"new_browser_cdp_session")
    try:
        response = bounded_call(session,"send","Extensions.getExtensions")
        return {"state": "metadata_available", "metadata_only": True,
                "extension_count": len(response.get("extensions", [])),
                "load_verified": False}
    except Exception as exc:
        return {"state": "unavailable", "metadata_only": True,
                "load_verified": False, "error": str(exc)[:300]}
    finally:
        bounded_call(session,"detach")


def _candidate(inventory, url, window_id, nonce):
    matches = [target for target in inventory["targets"].values() if target.get("url") == url]
    if len(matches) > 1:
        raise TabCreationError("补页nonce出现多个页面，不猜测或关闭")
    if not matches:
        return None
    target = matches[0]
    if target["window_id"] != window_id:
        raise TabCreationError("补页候选不在原专用窗口，不接管或移动",
                               {**target, "nonce": nonce, "url": url})
    return {"target_id": target["target_id"], "window_id": window_id,
            "nonce": nonce, "url": url}


def _worker(browser, session, extension_id, timeout, stopping):
    expected = "chrome-extension://" + extension_id + "/worker.js"
    deadline = time.monotonic() + timeout
    while True:
        bounded_call(session,"send","Target.getTargets")  # Pump the owner loop.
        for context in browser.contexts:
            for worker in context.service_workers:
                if worker.url == expected and bounded_call(worker,"evaluate","() => globalThis.paperSharedSlotVersion") == 1:
                    return worker
        if stopping() or time.monotonic() >= deadline:
            raise TabCreationError("临时补页worker未就绪；不改用当前窗口开页")
        time.sleep(.05)


def _confirm_cleanup(browser, root, *, stopping=None):
    """Confirm/remove only the helper under one already-attributed journal root.

    Called by the original owner under its submission lock, after slot/nonce
    reconciliation. No extension install, page creation or worker evaluation.
    A complete unpacked-extension list with no matching path proves absence.
    """
    stopping = stopping or (lambda: False)
    root = Path(root)
    if stopping() or root.is_symlink():
        raise TabCreationError('暂停或扩展目录归属不明，保留卸载回执')
    root = root.resolve()
    session = bounded_call(browser, 'new_browser_cdp_session')
    try:
        def matching():
            reply = bounded_call(session, 'send', 'Extensions.getExtensions')
            items = reply.get('extensions') if isinstance(reply, dict) else None
            if not isinstance(items, list) or any(
                    not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
                    or not isinstance(item.get('path'), str) or not Path(item['path']).is_absolute()
                    for item in items):
                raise TabCreationError('扩展清单不完整，保留卸载回执')
            return [item for item in items if Path(item['path']).resolve().is_relative_to(root)]

        matches = matching()
        if len(matches) > 1:
            raise TabCreationError('原补页日志下扩展不唯一，保留待核对')
        removed_id = None
        if matches:
            item = matches[0]
            source = Path(item['path'])
            if (source.is_symlink() or source.resolve().parent != root
                    or not source.name.startswith('slot-extension-')
                    or (source/'manifest.json').is_symlink() or (source/'worker.js').is_symlink()
                    or json.loads((source/'manifest.json').read_text()) != MANIFEST
                    or (source/'worker.js').read_text() != WORKER_SOURCE):
                raise TabCreationError('扩展源码与原临时helper不一致，不卸载')
            if stopping():
                raise TabCreationError('任务已暂停，不卸载扩展')
            bounded_call(session, 'send', 'Extensions.uninstall', {'id': item['id']})
            removed_id = item['id']
            if matching():
                raise TabCreationError('原临时扩展仍在，保留卸载回执')
        return {'confirmed_at': time.time(), 'source_root': str(root),
                'method': 'Extensions.getExtensions', 'removed_extension_id': removed_id,
                'extension_uninstalled': True}
    finally:
        bounded_call(session, 'detach')


def create_in_window(browser, window_id, *, root, nonce, owned_ids,
                     on_created=None, stopping=None, timeout=5):
    """Create one blank inactive candidate, then remove the temporary extension.

    Return its target/window/nonce plus cleanup status.  ``on_created(candidate)``
    runs after exact target attribution and again with the final cleanup receipt,
    before detach; the caller must persist both before navigating the new page.
    A nonce already
    present in the exact window is recovered without another creation.

    Failures never repeat create and never close arbitrary targets.  A candidate
    found after an uncertain reply is attached to ``TabCreationError.candidate``
    and passed to the callback, so the owner's journal can preserve it.  Failed
    extension removal leaves its local source for diagnosis and reports cleanup
    separately; the extension has no automatic page-creation behavior.
    """
    if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id < 0:
        raise TabCreationError("专用窗口ID无效")
    url = blank_url(nonce)
    stopping = stopping or (lambda: False)
    if stopping():
        raise TabCreationError("任务已暂停，不补页")
    owned = set(owned_ids)
    session = bounded_call(browser,"new_browser_cdp_session")
    extension_id = None
    extension_dir = None
    result = None
    failure = None
    installation_started = False
    try:
        before = snapshot_windows(session)
        if not before["complete"]:
            raise TabCreationError("实时窗口清单不完整，不补页")
        existing = _candidate(before, url, window_id, nonce)
        inside = {tid for tid, target in before["targets"].items() if target["window_id"] == window_id}
        allowable = owned | ({existing["target_id"]} if existing else set())
        if not inside or not inside.issubset(allowable):
            raise TabCreationError("原专用窗口缺失或混入用户页面，不补页")
        if existing:
            if len(inside) > 20:
                raise TabCreationError("专用窗口超过20页，保留候选等待检查", existing)
            result = {**existing, "created": False, "recovered_existing_nonce": True,
                      "extension_uninstalled": True}
            if on_created:
                on_created(dict(result))
            return result
        if len(inside) >= 20:
            raise TabCreationError("专用窗口已满20页；先归档并关闭坏页，不额外补开")
        destination = Path(root)
        destination.mkdir(parents=True, exist_ok=True)
        extension_dir = Path(tempfile.mkdtemp(prefix="slot-extension-", dir=destination))
        (extension_dir / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        (extension_dir / "worker.js").write_text(WORKER_SOURCE, encoding="utf-8")
        installation_started = True
        extension_id = bounded_call(session,"send","Extensions.loadUnpacked", {"path": str(extension_dir)},timeout=timeout)["id"]
        worker = _worker(browser, session, extension_id, timeout, stopping)
        if stopping():
            raise TabCreationError("任务已暂停，尚未补页")
        tab = bounded_call(worker,"evaluate",CREATE_EXPRESSION, {"windowId": window_id, "url": url},timeout=timeout)
        after = snapshot_windows(session)
        candidate = _candidate(after, url, window_id, nonce)
        if not candidate:
            raise TabCreationError("补页回执尚未出现；保留nonce等待原请求核对，不重复创建")
        result = {**candidate, "tab_id": tab.get("id"), "created": True,
                  "recovered_existing_nonce": False, "extension_uninstalled": False}
        if on_created:
            on_created(dict(result))
        if tab.get("windowId") != window_id or tab.get("active") is not False:
            raise TabCreationError("补页窗口或后台状态未通过，保留候选等待核对", result)
        if not after["complete"]:
            raise TabCreationError("补页后窗口清单不完整，保留候选等待核对", result)
        final_inside = {tid for tid, target in after["targets"].items() if target["window_id"] == window_id}
        if final_inside != inside | {candidate["target_id"]} or len(final_inside) > 20:
            raise TabCreationError("补页期间专用窗口页面变化，保留候选等待核对", result)
        return result
    except Exception as exc:
        if result is None and extension_id:
            try:
                recovered = _candidate(snapshot_windows(session), url, window_id, nonce)
                if recovered:
                    result = {**recovered, "created": True, "uncertain_reply": True,
                              "extension_uninstalled": False}
                    if on_created:
                        on_created(dict(result))
            except Exception:
                pass
        if isinstance(exc, TabCreationError):
            if exc.candidate is None:
                exc.candidate = result
            failure = exc
            raise
        failure = TabCreationError("定向补页失败；不使用其他窗口或重复创建：" + str(exc)[:300], result)
        raise failure from exc
    finally:
        removed = extension_id is None and not installation_started
        if installation_started and extension_id is None and failure is not None:
            failure.extension_cleanup_error = '扩展安装回执未知，保留源码等待核对，不重复安装'
            failure.extension_source_path = str(extension_dir)
        if extension_id:
            try:
                bounded_call(session,"send","Extensions.uninstall", {"id": extension_id})
                removed = True
            except Exception as exc:
                if result is not None:
                    result["extension_cleanup_error"] = str(exc)[:300]
                    result["extension_source_path"] = str(extension_dir)
                if failure is not None:
                    failure.extension_cleanup_error = str(exc)[:300]
                    failure.extension_source_path = str(extension_dir)
        if result is not None:
            result["extension_uninstalled"] = removed
            if on_created:
                on_created(dict(result))
        if extension_dir and removed:
            shutil.rmtree(extension_dir)
        try:
            bounded_call(session,"detach")
        except Exception as exc:
            raise TabCreationError('补页会话断开回执失败；保留原候选及卸载回执：' + str(exc)[:300], result) from exc
