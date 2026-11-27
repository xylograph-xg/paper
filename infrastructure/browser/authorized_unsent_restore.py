"""One-shot, explicitly authorized restoration on the resident owner's connection."""
import hashlib,json,time
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json
from .shared_page_health import snapshot_page,_uncollected_history
from .shared_browser_window import WindowIsolationError


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(item,record,snapshot,history):
    if (record.get('state')!='not_sent' or record.get('send_click_started') is not False
        or record.get('owner_pid')!=item['failed_owner_pid'] or record.get('target_id')!=item['target_id']
        or record.get('_ledger_sha256')!=item['ledger_sha256']
        or record.get('actual_prompt_sha256')!=item['prompt_sha256']):
        raise WindowIsolationError('原未发送证据或材料指纹变化')
    if _uncollected_history(item['target_id'],history):raise WindowIsolationError('原target仍有未知或未收取历史')
    if (snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False
        or snapshot.get('user_texts') or snapshot.get('answer_texts') or snapshot.get('login')
        or snapshot.get('verification') or snapshot.get('quota')
        or snapshot.get('url','').rstrip('/')!='https://chatgpt.com'):
        raise WindowIsolationError('原页有生成、消息、账户保护或归属变化')
    draft=snapshot.get('draft','')
    if hashlib.sha256(draft.encode()).hexdigest()!=item['draft_sha256']:
        raise WindowIsolationError('原页草稿变化，保留用户新输入')


def run_once(config,browser,pool,*,lock_factory,stopping,excluded_targets=()):
    root=Path(config['catalog_path']).parent;request=root/'authorized-unsent-restore.json'
    if not request.exists():return []
    data=json.loads(request.read_text());identity=data['id']
    if identity not in ('gray-input-failures-20261012','gray-input-failures-20261012-r2') or data.get('authorized') is not True:return []
    authorization=root.parent/'docs/authorizations/20261012-scoped-unsent-page-restore.md'
    if sha(authorization)!=data['authorization_sha256']:raise ValueError('限定恢复授权指纹变化')
    def needs_work(item):
        journal=root/'authorized-unsent-restores'/identity/item['target_id']/'journal.json'
        if not journal.exists():return True
        saved=json.loads(journal.read_text())
        return saved.get('state')=='clear_intent' or saved.get('state')=='blocked' and saved.get('error','').startswith('[Errno 2]')
    pending=[item for item in data['items'] if needs_work(item)]
    if not pending:return []
    from .attempt_history import index_attempts,read_attempt
    from .shared_page_repair import _archive,_allowed
    from .shared_window_owner import require_slot
    from .shared_pool_store import save_pool,mark_verified_blank
    records,_=index_attempts(root);results=[]
    for item in pending:
        tid=item['target_id'];journal=root/'authorized-unsent-restores'/identity/tid/'journal.json'
        saved=json.loads(journal.read_text()) if journal.exists() else None
        if saved and saved.get('state')=='blocked':saved=None
        if tid in excluded_targets:continue
        try:
            _allowed(config,stopping)
            path=Path(item['ledger_path'])
            if not path.exists():
                matches=[r for r in records.values() if r.get('_ledger_sha256')==item['ledger_sha256']
                         and r.get('target_id')==tid and r.get('owner_pid')==item['failed_owner_pid']]
                if len(matches)!=1:raise ValueError('原归档指纹未唯一定位，保留页面')
                path=Path(matches[0]['_ledger_path'])
            record=read_attempt(path)
            prompt=Path(item['prompt_path'])
            if not prompt.exists():prompt=path.parent/'prompt-actual.txt'
            text=prompt.read_text()
            if sha(prompt)!=item['prompt_sha256']:raise ValueError('原实际提示变化')
            history=[r for r in records.values() if r.get('target_id')==tid]
            # Recheck all frozen input and upload bytes, before taking the DOM lock.
            original_path=Path(item['ledger_path'])
            material=original_path.parent.parent if original_path.parent.name=='chatgpt' else original_path.parent
            if not record.get('inputs'):raise ValueError('材料输入指纹缺失')
            for name,expected in record['inputs'].items():
                if Path(name).name!=name or sha(material/name)!=expected:raise ValueError('冻结输入变化')
            bundle=record.get('upload_bundle') or json.loads((material/'packet.json').read_text())['upload_bundle']
            if sha(bundle['zip_path'])!=bundle['zip_sha256']:raise ValueError('ZIP指纹变化')
            with lock_factory(timeout=5):
                require_slot(config,browser,tid)
                from .browser_inventory import enumerate_pages
                page=enumerate_pages(browser)['pages'][tid]
                snapshot=snapshot_page(tid,page)
                checked_item=item
                if saved:
                    # Resume only the already archived deletion, with no new
                    # text and the same original attachment. Never send again.
                    if snapshot.get('draft','').strip():raise ValueError('归档后出现新草稿，保留')
                    checked_item={**item,'draft_sha256':hashlib.sha256(snapshot.get('draft','').encode()).hexdigest()}
                    for name,expected in saved['archive_hashes'].items():
                        if sha(journal.parent/'diagnostics'/name)!=expected:raise ValueError('原归档指纹变化')
                validate(checked_item,record,snapshot,history)
                # A partial input must be the exact first paragraph from this
                # identity-bound failed request; never accept arbitrary prefixes.
                if not saved and snapshot['draft'] not in (text,text.splitlines()[0]) and snapshot['draft'].strip():raise ValueError('草稿与原输入不符')
                from web_gpt.core import wait_prompt_box,_composer
                box=wait_prompt_box(page,timeout=3000);scope=_composer(page,box)
                attachment_text=scope.inner_text()
                allowed_names=item.get('allowed_attachments',[Path(bundle['zip_path']).name])
                if any(name not in allowed_names for name in snapshot.get('attachment_names',[])):
                    raise ValueError('有非原任务附件，保留')
                if snapshot.get('attachments') and Path(bundle['zip_path']).name not in attachment_text:
                    raise ValueError('附件与原材料ZIP不一致')
                def guard():
                    _allowed(config,stopping);require_slot(config,browser,tid)
                    fresh=read_attempt(path);validate(checked_item,fresh,snapshot_page(tid,page),history)
                folder=journal.parent/'diagnostics'
                hashes=saved['archive_hashes'] if saved else _archive(folder,page,{'evidence':{'snapshot':snapshot}},record,guard,
                                {r['_ledger_path']:r['_ledger_sha256'] for r in history})
                guard();atomic_json(journal,{'state':'clear_intent','item':item,'archive_hashes':hashes,'created':time.time()})
                # DOM-only removal, scoped to this original composer. Never send.
                labels=['移除 '+name for name in allowed_names]+['Remove '+name for name in allowed_names]
                import re
                buttons=scope.get_by_role('button',name=re.compile('^(?:'+'|'.join(re.escape(label) for label in labels)+')$'))
                for _ in range(10):
                    if not buttons.count():break
                    _allowed(config,stopping);require_slot(config,browser,tid)
                    buttons.first.evaluate('(el)=>el.click()');page.wait_for_timeout(200)
                from .web_editor_input import replace
                _allowed(config,stopping);require_slot(config,browser,tid);replace(box,'')
                after=snapshot_page(tid,page)
                if (not after.get('inspection_complete') or after.get('draft','').strip() or after.get('attachments')
                    or after.get('user_texts') or after.get('answer_texts') or after.get('streaming') is not False):
                    raise ValueError('清理后页面未完整空白，保留待核对')
                mark_verified_blank(pool['windows'][tid]);pool['windows'][tid]['authorized_restore']=str(journal)
                save_pool(root/'gpt-window-pool.json',pool)
                atomic_json(journal,{'state':'restored','item':item,'archive_hashes':hashes,'after':after,'finished':time.time()})
                results.append(tid)
        except Exception as exc:
            if not journal.exists():
                atomic_json(journal,{'state':'blocked','item':item,'error':str(exc),'updated':time.time()})
            else:
                prior=json.loads(journal.read_text())
                atomic_json(journal,{**prior,'state':'blocked_after_clear','error':str(exc),'updated':time.time()})
            atomic_json(root/'authorized-unsent-restore-status.json',{'updated':time.time(),'target_id':tid,'error':str(exc),'restored':results})
    return results
