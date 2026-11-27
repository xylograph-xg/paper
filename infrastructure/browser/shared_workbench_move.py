"""One explicitly authorized background workbench move on the original owner."""
import json
import shutil
import tempfile
import time
from core.api import paths__WorkspacePath as Path

from core.api import services__atomic_json as atomic_json
from .owner_browser_calls import bounded_call
from .shared_browser_window import read_window_inventory, WindowIsolationError
from .shared_window_tabs import MANIFEST, WORKER_SOURCE, _worker

MOVE = """async props => {
  const tabs = await chrome.tabs.query({windowId: props.windowId});
  const matches = tabs.filter(tab => tab.url === props.url);
  if (matches.length !== 1) throw new Error('Workbench tab attribution is not unique');
  const result = await chrome.windows.create({tabId: matches[0].id, focused: false, type: 'normal'});
  return {windowId: result.id, focused: result.focused, tabId: matches[0].id};
}"""


def pending(config):
    """Completed journals need no submission lock or browser operation."""
    path = Path(config['catalog_path']).parent/'shared-workbench-move.json'
    return path.exists() and json.loads(path.read_text()).get('state') not in ('verified','cancelled_target_missing')


def run_once(config, browser, *, stopping):
    root=Path(config['catalog_path']).parent
    path=root/'shared-workbench-move.json'
    if not path.exists():return None
    journal=json.loads(path.read_text())
    if journal.get('state') in ('verified','cancelled_target_missing'):return journal
    if journal.get('authorized') is not True:raise WindowIsolationError('工作台移窗尚未授权')
    from .shared_page_repair import _allowed, _registry
    _allowed(config,stopping)
    registry,sha=_registry(config)
    if sha!=journal['registry_sha256'] or registry['window_id']!=journal['window_id']:
        raise WindowIsolationError('移窗前任务槽位登记变化，不移动')
    target_id=journal['target_id']; url=journal['url']
    # Exact local workbench origin only; never navigation or unknown user tabs.
    if url!='http://127.0.0.1:8767/' or target_id in {s['target_id'] for s in registry['slots']}:
        raise WindowIsolationError('授权对象不是独立工作台页面')
    inventory=read_window_inventory(browser)
    if not inventory['complete'] or inventory.get('errors'):raise WindowIsolationError('移窗清单不完整')
    target=inventory['targets'].get(target_id)
    if not target:
        journal.update(state='cancelled_target_missing',checked_at=time.time(),reason='授权原target已不在实时清单，不新建或操作其他页面')
        atomic_json(path,journal)
        return journal
    if target['url']!=url:raise WindowIsolationError('工作台原target或URL变化')
    moved=target['window_id']!=registry['window_id']
    if not moved and journal.get('state') in ('move_intent','move_unknown'):
        raise WindowIsolationError('工作台移窗回执未知，只核对原target，不重复移动')
    session=bounded_call(browser,'new_browser_cdp_session')
    try:
        if not moved and journal.get('state')=='install_intent':
            raise WindowIsolationError('临时扩展安装回执未知，保留记录不重复安装')
        if not moved:
            inside={tid for tid,t in inventory['targets'].items() if t['window_id']==registry['window_id']}
            if inside!={s['target_id'] for s in registry['slots']}|{target_id}:
                raise WindowIsolationError('专窗还有其他非授权页面，不移动')
            folder=root/'workbench-move-evidence';folder.mkdir(exist_ok=True)
            atomic_json(folder/'inventory-before.json',inventory)
            extension=Path(tempfile.mkdtemp(prefix='workbench-move-',dir=folder))
            (extension/'manifest.json').write_text(json.dumps({**MANIFEST, 'host_permissions':['http://127.0.0.1:8767/*']}))
            (extension/'worker.js').write_text(WORKER_SOURCE)
            journal.update(extension_source=str(extension),state='install_intent')
            atomic_json(path,journal)
            extension_id=bounded_call(session,'send','Extensions.loadUnpacked',{'path':str(extension)},timeout=5)['id']
            journal.update(extension_id=extension_id,state='installed');atomic_json(path,journal)
            worker=_worker(browser,session,extension_id,5,stopping)
            _allowed(config,stopping)
            journal.update(state='move_intent',intent_at=time.time());atomic_json(path,journal)
            try:
                receipt=bounded_call(worker,'evaluate',MOVE,{'windowId':registry['window_id'],'url':url},timeout=5)
                journal.update(receipt=receipt,state='moved');atomic_json(path,journal)
                if receipt.get('focused') is not False:raise WindowIsolationError('后台移窗回执未通过')
            except Exception as exc:
                journal.update(state='move_unknown',error=str(exc)[:500]);atomic_json(path,journal)
                raise
        after=read_window_inventory(browser)
        target=after.get('targets',{}).get(target_id)
        inside={tid for tid,t in after.get('targets',{}).items() if t['window_id']==registry['window_id']}
        if (not after.get('complete') or after.get('errors') or not target or target['url']!=url or
                target['window_id']==registry['window_id'] or inside!={s['target_id'] for s in registry['slots']}):
            raise WindowIsolationError('工作台移窗后原target或20任务槽未通过')
        if journal.get('extension_id'):
            bounded_call(session,'send','Extensions.uninstall',{'id':journal['extension_id']})
        if journal.get('extension_source'):shutil.rmtree(journal['extension_source'],ignore_errors=True)
        journal.update(state='verified',checked_at=time.time(),new_window_id=target['window_id'],fixed_slots=len(inside),extension_uninstalled=True)
        atomic_json(path,journal)
        return journal
    finally:
        bounded_call(session,'detach')
