"""Owned web pages, per-provider capacity, persisted failover and error cleanup."""
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import catalog__ROOT as ROOT
from core.api import services__atomic_json as atomic_json
from .upload_quota import visible_notice, _reset_timestamp

HOSTS={'chatgpt':{'chatgpt.com'},'qwen':{'chat.qwen.ai'},'deepseek':{'chat.deepseek.com'}}
URLS={'chatgpt':'https://chatgpt.com/','qwen':'https://chat.qwen.ai/','deepseek':'https://chat.deepseek.com/'}
PREPARE_GATE=threading.Lock()


def commit_submitted(path, attempt, *, prior_count, conversation_url):
    """Do not downgrade a reply saved while the send acknowledgement yielded."""
    current=json.loads(Path(path).read_text())
    if (current.get('created')!=attempt.get('created') or current.get('target_id')!=attempt.get('target_id')
            or current.get('actual_prompt_sha256')!=attempt.get('actual_prompt_sha256')):
        raise ValueError('Submission receipt binding changed; preserve original request')
    if current.get('state')=='response_saved':
        raw=Path(path).parent/'response-raw.txt'
        import hashlib
        if (current.get('conversation_url')!=conversation_url or
                hashlib.sha256(raw.read_bytes()).hexdigest()!=current.get('raw_sha256')):
            raise ValueError('Saved response receipt changed during send acknowledgement')
        attempt.update(current)
    else:
        if prior_count is None:raise ValueError('缺少发送确认；只能保留已经完整保存的原回答')
        attempt.update(state='submitted',conversation_url=conversation_url)
    if prior_count is not None:attempt['prior_count']=prior_count
    atomic_json(path,attempt)


class DeferredWeb(RuntimeError):pass
class UncertainWeb(RuntimeError):pass
class IncompleteWebAnswer(TimeoutError):pass
class UploadStageFailure(RuntimeError):
    """Native attachment never became ready or never settled, before any send click.

    Kept a RuntimeError subclass so every existing message and handler is
    unchanged; the stage only labels which upload segment proved it ended.
    """
    def __init__(self,message,stage):
        super().__init__(message);self.stage=stage
class ProviderFailure(RuntimeError):
    def __init__(self,message,provider,kind,unsent,reset=None,reset_evidence=None):
        super().__init__(message);self.provider=provider;self.kind=kind;self.unsent=unsent;self.reset=reset;self.reset_evidence=reset_evidence


def failure_kind(text):
    if re.search(r'Unusual activity has been detected|异常活动|设备异常',text,re.I):return 'unusual_activity'
    if re.search(r'访问验证|验证您是真人|人机验证|captcha|verify (?:you are|that you)|verification required',text,re.I):return 'verification'
    if re.search(r'quota|limit reached|too many|upload limit|usage limit|(?:附件|上传).*?(?:上限|限制)|(?:达到|已达).*?(?:上限|限制)|用量.*(?:上限|限制)',text,re.I):return 'quota'
    if re.search(r'ERR_(?:NETWORK|INTERNET|CONNECTION|NAME|TIMED)|net::|network|断网|连接失败|connection|socket|连接.*(?:断开|关闭)|CDP',text,re.I):return 'network'
    return 'other'


# Only a technical upload failure may reach the bounded backoff queue; an
# unreadable settle state stays unknown for inspection instead of a retry.
# `attach` stays accepted for receipts already on file: the kernel now names the
# two halves of that segment separately, so a write failure and an attachment
# that never showed up no longer share one backoff label.
UPLOAD_STAGE_BY_KIND={'missing_file_input':'entry','entry_not_ready':'entry','write_failed':'attach_write',
                      'attachment_not_shown':'attach_visible','settle_timeout':'settle',
                      'full_page_settle_timeout':'settle'}


class Router:
    def __init__(self,folder,policy=None):
        self.path=Path(folder)/'web-provider-control.json';self.lock=threading.Lock();self.policy=policy or {}
        try:self.state=json.loads(self.path.read_text())
        except (OSError,ValueError):self.state={}
    def choose(self,exclude=()):
        from core.api import control__provider_decisions as provider_decisions, control__read_record as read_record, control__InvalidControl as InvalidControl
        with self.lock:
            try:self.state=read_record(self.path)
            except InvalidControl as exc:raise DeferredWeb(str(exc)) from exc
            decisions=provider_decisions(self.path.parent,policy=self.policy,state=self.state)
            for provider in ('chatgpt','qwen','deepseek'):
                if provider not in exclude and decisions[provider].allowed:return provider
        reasons='；'.join(d.reason for d in decisions.values() if d.state!='disabled')
        raise DeferredWeb('所选网页通道尚未就绪或暂不可用：'+reasons)
    def block(self,error):
        from core.api import control__mutate_record as mutate_record
        if error.kind=='verification':
            path=self.path.parent/'web-channel-control.json'
            mutate_record(path,{error.provider:{'manual_verification_required':True,'reason':str(error)[:700],'observed':time.time()}},event='manual_verification_required');return
        if error.kind not in ('quota','network','unusual_activity'):return
        observed=time.time()
        default=3600 if error.kind=='unusual_activity' else 300 if error.kind=='network' else 900
        until=error.reset if isinstance(error.reset,(int,float)) and not isinstance(error.reset,bool) and error.reset>observed else observed+default
        evidence=error.reset_evidence or {}
        explicit=False
        try:
            explicit=(evidence.get('source')=='live_browser_notice' and bool(evidence.get('notice'))
                      and datetime.fromisoformat(evidence['not_before_utc']).timestamp()==error.reset and error.reset>observed)
        except (KeyError,ValueError,TypeError,AttributeError):pass
        with self.lock:
            if error.kind in ('network','unusual_activity'):
                from core.api import control__read_record as read_record
                current=read_record(self.path).get(error.provider,{})
                # A lesser error cannot shorten an account quota/device limit.
                if current.get('reason') in ('quota','unusual_activity') and current.get('blocked_until',0)>observed:
                    if error.kind!='unusual_activity' or current.get('reason')=='quota':
                        self.state=read_record(self.path);return
                until=max(until,current.get('blocked_until',0))
            record={'blocked_until':until,'reason':error.kind,'error':str(error)[:700],
                    'observed':time.time(),'explicit_reset':explicit,
                    'reset_source':'live_browser_notice' if explicit else 'cooldown_probe'}
            if explicit:record['reset_evidence']=evidence
            self.state=mutate_record(self.path,{error.provider:record},event='provider_blocked')


def provider_page_count(browser,provider):
    import_root=os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright'))
    if import_root not in sys.path:sys.path.insert(0,import_root)
    from web_gpt.capacity import provider_page_count as count
    return count(browser,provider)


def require_no_verification(page):
    challenge=page.locator('#nocaptcha,[class*="captcha"]')
    if any(challenge.nth(i).is_visible() for i in range(challenge.count())):raise RuntimeError('访问验证：请在专用浏览器手动验证您是真人')
    text=page.locator('body').inner_text(timeout=3000)
    if failure_kind(text)=='verification':raise RuntimeError('访问验证：请在专用浏览器手动验证您是真人')


def collect_owned(page,prior,provider,selectors,timeout,stopping=lambda:False):
    """Poll completion and visible errors so failed tabs do not wait half an hour."""
    deadline=time.monotonic()+timeout;last='';stable=0
    previous_notices = set()
    while time.monotonic()<deadline:
        if stopping():raise RuntimeError('用户停止网页任务，保存原URL，不重新发送')
        require_no_verification(page)
        errors=page.locator('[role="alert"], [data-testid*="error"], .qwen-chat-v2-message-notice, #main-frame-error')
        current_notices = set()
        for i in range(errors.count()):
            node=errors.nth(i)
            if not node.is_visible():continue
            notice=node.inner_text().strip()
            if re.search(r'error|failed|went wrong|try again|无法|失败|断开|错误|上限|限制',notice,re.I):
                current_notices.add(notice)
                if notice in previous_notices or failure_kind(notice) in ('verification','quota','unusual_activity'):
                    raise RuntimeError('网页报错：'+notice[:700])
        previous_notices = current_notices
        answers=page.locator(selectors[0]);stop=page.locator(selectors[1])
        streaming=any(stop.nth(i).is_visible() for i in range(stop.count()))
        if answers.count()>prior:
            message=answers.last
            try:text=selectors[2](message)
            except RuntimeError:text=''
            # Completion controls sit outside GPT's markdown body in some versions.
            complete=message.evaluate('''(el) => {
              const container=el.closest('[data-talvt-turn-state]') || el.closest('[data-chatgpt-search-message-ids],article,[data-testid^="conversation-turn"],.qwen-chat-message-assistant') || el.parentElement?.parentElement || el;
              return container.getAttribute('data-talvt-turn-state')==='complete' || Array.from(container.querySelectorAll('[data-testid="copy-turn-action-button"],[data-testid="copy-response"],[aria-label*="Copy"],[aria-label*="复制"],.response-actionbar,.response-message-actions')).some(e=>e.getClientRects().length);
            }''')
            stable=stable+1 if text and text==last and complete and not streaming and message.get_attribute('aria-busy')!='true' else 0
            last=text
            if stable>=3:return text
        page.wait_for_timeout(500)
    raise IncompleteWebAnswer('网页未出现完整回答/完成标记；保存原会话，关闭本任务失败页，不返回部分答案')


def owned_error_cleanup(page,folder,attempt):
    """Archive diagnostics before closing even failed/uncertain owned pages."""
    if page is None:return
    try:
        if page.is_closed():attempt['tab_cleanup']='already_closed';return
        attempt['conversation_url']=page.url
        try:(folder/'error-page.txt').write_text(page.locator('body').inner_text(timeout=3000))
        except Exception:pass
        try:page.screenshot(path=str(folder/'error-page.png'),timeout=3000)
        except Exception:pass
        atomic_json(folder/'attempt.json',attempt)
        page.close();attempt['tab_cleanup']='closed_error_page'
    except Exception as exc:attempt['tab_cleanup_error']=type(exc).__name__


def release_gpt_pool(folder,page,attempt):
    path=Path(folder).parents[2]/'gpt-window-pool.json'
    from .shared_pool_store import load_pool,save_pool
    pool=load_pool(path)
    entry=pool['windows'][attempt['target_id']]
    if entry.get('active_paper_id') not in (None,Path(folder).parent.name) or entry.get('kind')=='review':
        raise UncertainWeb('原页池已属于其他材料，保留其归属，不释放')
    pool['windows'][attempt['target_id']].update(state='ready',conversation_url=page.url,raw_path=str((Path(folder)/'response-raw.txt').resolve()),raw_sha256=attempt['raw_sha256'])
    save_pool(path,pool)


def resume_known_response(provider,folder,policy,stopping=lambda:False):
    """Resume collection of one proven submitted target; never submit or navigate."""
    folder=Path(folder)
    if policy.get('shared_window',{}).get('enabled') or (len(folder.parents)>2 and (folder.parents[2]/'shared-gpt-window.json').exists()):
        raise UncertainWeb('共享专窗只能由原常驻所有者收取；遗留入口不另连CDP')
    import_root=os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright'))
    if import_root not in sys.path:sys.path.insert(0,import_root)
    from playwright.sync_api import sync_playwright
    from web_gpt.core import ANSWER,STOP_BUTTON,_message_text
    from web_gpt.submission import submission_lock
    from cards.api import web_card_inputs__digest as digest
    folder=Path(folder);attempt=json.loads((folder/'attempt.json').read_text())
    if attempt['state']!='submitted' or provider!='chatgpt':raise UncertainWeb('只收取确认已发送的GPT原页')
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'),no_defaults=True)
        pages=[x for c in browser.contexts for x in c.pages if c.new_cdp_session(x).send('Target.getTargetInfo')['targetInfo']['targetId']==attempt['target_id']]
        if len(pages)!=1:raise UncertainWeb('原提交页面已变化，不重发')
        page=pages[0]
        if page.url!=attempt['conversation_url']:
            # Chrome's new UI changes its local provisional URL after the first send.
            expected=(folder/'prompt-actual.txt').read_text()
            from web_gpt.core import _dense
            provisional='/c/local-chatgpt' in attempt['conversation_url']
            users=page.locator('[data-chatgpt-search-unit-key$=":user"], [data-chatgpt-search-message-ids]:has(> h4[data-conversation-role="user"]), [data-message-author-role="user"]')
            same_prompt=any(_dense(expected) in _dense(users.nth(i).inner_text()) for i in range(users.count()))
            if not provisional or not page.url.startswith('https://chatgpt.com/c/') or not same_prompt:raise UncertainWeb('原提交页面已变化，不重发')
            attempt['conversation_url']=page.url;atomic_json(folder/'attempt.json',attempt)
        raw=collect_owned(page,attempt.get('prior_count',0),provider,(ANSWER,STOP_BUTTON,_message_text),policy.get('answer_timeout_seconds',1800),stopping)
        with submission_lock():
            if page.url!=attempt['conversation_url'] or _message_text(page.locator(ANSWER).last)!=raw:raise UncertainWeb('原会话收取时变化')
            (folder/'response-raw.txt').write_text(raw)
            attempt.update(state='response_saved',raw_sha256=digest(folder/'response-raw.txt'),resumed_without_resending=True)
            atomic_json(folder/'attempt.json',attempt)
            if policy.get('background_no_create'):
                release_gpt_pool(folder,page,attempt);attempt['tab_cleanup']='preserved_reusable_window';attempt['reused_window']=True
            else:page.close();attempt['tab_cleanup']='closed_saved_response'
            atomic_json(folder/'attempt.json',attempt)
        return raw,attempt


def formal_gpt_url(url):
    parsed=urlsplit(url)
    return parsed.scheme=='https' and parsed.hostname=='chatgpt.com' and parsed.path.startswith('/c/') and bool(parsed.path[3:]) and 'local-chatgpt' not in parsed.path





def attachment_option_disabled(page):
    """Return the visible upload option text when the native menu greys it out."""
    try:
        return page.evaluate(r"""() => {
          const visible = el => {
            if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]')) return false;
            const r=el.getBoundingClientRect(),s=getComputedStyle(el);
            return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';
          };
          const textRe=/^(上传文件|从计算机上传|上传照片和文件|添加照片和文件|Upload from computer|Upload files|Add photos and files)$/i;
          for (const el of document.querySelectorAll('[role="menuitem"],[role="menuitemradio"],[role="option"],button')) {
            if (!visible(el)) continue;
            const text=(el.innerText||el.textContent||'').trim().replace(/\s+/g,' ');
            if (!textRe.test(text)) continue;
            const disabled=el.disabled===true||el.getAttribute('aria-disabled')==='true'||
              /disabled|opacity-50|text-token-text-tertiary|pointer-events-none/i.test(el.className||'');
            if (disabled) return text;
          }
          return null;
        }""")
    except Exception:
        return None

# Keep the probe passive. The same predicate checks the element chosen by the
# upload library immediately before a formula ZIP is assigned to it.
_DOCUMENT_INPUT = r"""node => {
    const editors = [...document.querySelectorAll('#prompt-textarea,textarea,[contenteditable="true"][role="textbox"]')]
        .filter(el => el.getClientRects().length && !el.closest('[inert],[hidden],[aria-hidden="true"]'));
    if (editors.length !== 1) return false;
    const scope = editors[0].closest('form,[data-testid*="composer"]') || editors[0].parentElement;
    const isDocument = el => {
        if (!el || el.type !== 'file' || el.matches(':disabled,[aria-disabled="true"],[capture]')) return false;
        const label = el.getAttribute('aria-label') || '';
        const accepts = (el.accept || '').toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
        const documentLabel = /附加文件|添加文件|上传文件|attach files?|upload files?/i.test(label);
        if (!documentLabel && /相机|照片|camera|photo/i.test(label)) return false;
        if (accepts.length && !accepts.some(s => ['*/*','*','.zip','application/zip','application/octet-stream',
            'application/x-zip-compressed'].includes(s))) return false;
        return scope.contains(el) || (el.form && el.form === editors[0].closest('form')) ||
            (!el.closest('form') && (documentLabel || !!el.closest('[role="menu"]')));
    };
    if (node) return isDocument(node);
    return [...document.querySelectorAll('input[type="file"]')].some(isDocument);
}"""


def attachment_entry(page):
    """Read current document-upload controls without opening a menu or assigning a file."""
    require_no_verification(page)
    notice = visible_notice(page)
    if notice:
        return dict(ready=False, reason=notice.get('kind') or 'quota', notice=notice.get('notice', ''))
    disabled = attachment_option_disabled(page)
    if disabled:
        return dict(ready=False, reason='disabled', notice=disabled)
    ready = bool(page.evaluate(_DOCUMENT_INPUT))
    return dict(ready=ready, reason='document_input' if ready else 'no_document_input')


def upload_settle_ms(policy, size):
    seconds = policy.get('upload_settle_timeout_seconds',180)
    if isinstance(size,int) and size >= policy.get('parallel_uploads',{}).get('large_zip_threshold',8_000_000):
        seconds = policy.get('upload_large_settle_timeout_seconds',seconds)
    return seconds * 1000


def wait_gpt_upload_ready(page,timeout=30000):
    """Disabled during page hydration is not proof of exhausted quota."""
    from web_gpt.core import wait_prompt_box,_composer
    scope=_composer(page,wait_prompt_box(page));deadline=time.monotonic()+timeout/1000
    opened=False;disabled_hits=0
    while True:
        entry = attachment_entry(page)
        if entry['ready']:
            return
        if entry['reason'] == 'unusual_activity':
            raise RuntimeError('账户设备异常活动限制：' + entry['notice'])
        if entry['reason'] != 'disabled' and 'notice' in entry:
            raise RuntimeError('附件额度限制：' + entry['notice'])
        if entry['reason'] == 'disabled':
            disabled_hits+=1
            if disabled_hits>=3:
                raise RuntimeError('附件额度限制：加号菜单上传文件置灰，未发送')
        else:
            disabled_hits=0
        if not opened:
            # The current native menu lives outside main and exposes the reason
            # hidden disabled file inputs alone cannot provide.
            button=scope.locator('button[aria-label="添加文件等内容"],button[aria-label="Add files and more"]')
            if button.count()==1 and button.is_visible():
                if button.get_attribute('aria-expanded')!='true':button.evaluate('(el)=>el.click()')
                opened=True;page.wait_for_timeout(500)
                # The next pass reads the newly visible native menu directly;
                # never copy body/science text into a persistent quota gate.
        if time.monotonic()>=deadline:raise UploadStageFailure('附件入口暂未就绪，未发送','entry')
        page.wait_for_timeout(500)


def wait_gpt_upload_settled(page,timeout=180000,stopping=lambda:False):
    """Filename visibility is not upload completion; fail before any send click."""
    from web_gpt.core import PROGRESS_BAR
    deadline=time.monotonic()+timeout/1000
    while True:
        if stopping():raise DeferredWeb('已暂停，附件等待结束前不发送')
        require_no_verification(page)
        notice=visible_notice(page)
        if notice:raise RuntimeError('附件额度限制：'+notice.get('notice',''))
        bars=page.locator(PROGRESS_BAR)
        if not any(bars.nth(i).is_visible() for i in range(bars.count())):return
        if time.monotonic()>=deadline:raise UploadStageFailure('附件仍在上传，未点击发送；稍后重试','settle')
        page.wait_for_timeout(500)


_COMPOSER_ATTACHMENT_BUTTONS = (
    '[data-composer-attachments] button[aria-label^="移除 "], '
    '[data-composer-attachments] button[aria-label^="Remove "]'
)


def _dismiss_chat_only_notice(page, detail, *, already_dismissed=False):
    """Acknowledge the account-library notice for the current settled ZIP."""
    if detail is None:
        return False
    filename = (detail.get('bundle') or {}).get('zip_name')
    outcome = page.evaluate(r"""({filename, settled, alreadyDismissed, attachmentButtons}) => {
      const text = el => (el?.textContent || '').trim().replace(/\s+/g, ' ');
      const visible = el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 &&
               !['hidden', 'collapse'].includes(getComputedStyle(el).visibility);
      };
      const dialogs = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')]
        .filter(visible);
      const named = dialogs.filter(el =>
        text(document.getElementById(el.getAttribute('aria-labelledby'))) === '文件仅添加到聊天');
      if (!named.length) return 'absent';
      if (dialogs.length !== 1 || named.length !== 1 || !settled || !filename || alreadyDismissed)
        return 'unbound';
      if ([...document.querySelectorAll('#nocaptcha,[class*="captcha"]')].some(visible))
        return 'unbound';
      const dialog = named[0];
      const description = text(document.getElementById(dialog.getAttribute('aria-describedby')));
      if (!/^剩余存储空间不足，无法保存此文件。请移除文件以腾出空间。?$/.test(description))
        return 'unbound';
      const names = [...document.querySelectorAll(attachmentButtons)]
        .filter(visible).map(el => el.getAttribute('aria-label').replace(/^(?:移除|Remove)\s+/, ''));
      const previews = [...dialog.querySelectorAll('span')].filter(el =>
        !el.childElementCount && visible(el) && text(el) === filename);
      if (names.length !== 1 || names[0] !== filename || previews.length !== 1) return 'unbound';
      const buttons = [...dialog.querySelectorAll('button')].filter(el =>
        visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' &&
        ['关闭对话框', 'Close dialog'].includes(el.getAttribute('aria-label') || text(el)));
      if (buttons.length !== 1) return 'unbound';
      buttons[0].click();
      return 'dismissed';
    }""", {'filename': filename, 'settled': detail.get('receipt_sufficient') is True,
           'alreadyDismissed': already_dismissed, 'attachmentButtons': _COMPOSER_ATTACHMENT_BUTTONS})
    if outcome == 'absent':
        return False
    if outcome != 'dismissed':
        raise DeferredWeb('聊天附件提示未唯一绑定本次已结算ZIP，保留原页待核对，未发送')
    page.get_by_role('dialog', name='文件仅添加到聊天', exact=True).wait_for(state='hidden', timeout=3000)
    return True


def _zip_identity(path):
    from cards.api import web_card_inputs__digest as digest
    item = Path(path)
    try:
        return {'zip_name': item.name, 'zip_bytes': item.stat().st_size, 'zip_sha256': digest(item)}
    except (OSError, ValueError):
        return {'zip_name': item.name}


def _upload_failure(exc, detail):
    """Attribute one unsent upload stop. Pause, quota, verification, model checks
    and frozen-input changes are never a retryable upload failure."""
    text = str(exc)
    if isinstance(exc, DeferredWeb) or '已暂停' in text:
        return 'paused', False
    if '访问验证' in text or '验证您是真人' in text:
        return 'verification', False
    if '额度限制' in text or '上限' in text:
        return 'quota', False
    if '冻结材料' in text:
        return 'input_changed', False
    source = detail if (detail and detail.get('failure_kind')) else getattr(exc, 'upload_detail', None)
    if source:
        return source.get('failure_kind') or 'unknown', bool(source.get('retryable_upload'))
    if '附件入口暂未就绪' in text:
        return 'entry_not_ready', True
    if '附件仍在上传' in text:
        return 'full_page_settle_timeout', True
    if '附件上传失败' in text:
        return 'unknown', False
    return type(exc).__name__, False


def submit_gpt_background(session,prompt,files,on_before_send=lambda:None,*,upload_timeout=180000,stopping=lambda:False,lock_factory=None,page_guard=None,parallel_upload=False,upload_context=None):
    """CDP DOM input and one click; no OS focus or system clipboard."""
    files=[str(Path(value)) for value in files]
    from web_gpt.core import (upload_files_detailed,implementation_identity,wait_prompt_box,_composer,
                              _box_text,_dense,_wait_send_ready,_button_enabled,_sent,count_answers)
    from web_gpt.submission import submission_lock
    from . import upload_trace
    context=upload_context if isinstance(upload_context,dict) else {}
    original_stopping=stopping
    def stopping():
        if original_stopping():return True
        data=upload_trace.root()
        if data is None or not context.get('paper_id'):return False
        from core.api import seed_focus__allowed as seed_allowed
        return not seed_allowed({'catalog_path':str(Path(data)/'catalog.sqlite3')},context['paper_id'])
    def mark(name):
        callback=context.get('on_stage')
        if callback:callback(name)
    if session._pending_answer is not None:raise RuntimeError('已有待收取请求，不重发')
    from contextlib import nullcontext
    lock=lock_factory or submission_lock
    detail=None
    notice_dismissed=False
    def acknowledge_upload_notice():
        nonlocal notice_dismissed
        if _dismiss_chat_only_notice(session.page,detail,already_dismissed=notice_dismissed):
            notice_dismissed=True
            diagnostic['chat_only_notice']='dismissed_for_settled_zip'
            wait_gpt_upload_settled(session.page,min(upload_timeout,1000),stopping)
            return True
        return False
    mark('model_identity_preflight')
    with (nullcontext() if parallel_upload else lock()):
        if stopping():raise DeferredWeb('已暂停，未设置或上传材料')
        if page_guard:page_guard()
        session.verify_settings()
    with (nullcontext() if parallel_upload else lock()):
        if files:
            mark('attachment_upload')
            kernel=implementation_identity()
            bundle=context.get('bundle') or {}
            identity=_zip_identity(files[0])
            from .web_upload_bundle import check_zip_size
            check_zip_size({'size':identity.get('zip_bytes',0)})
            try:
                attempt=upload_trace.begin(lane=context.get('lane'),job_id=context.get('job_id'),
                    paper_id=context.get('paper_id'),target_id=context.get('target_id'),zip_path=files[0],
                    zip_sha256=bundle.get('zip_sha256') or identity.get('zip_sha256'),
                    zip_bytes=bundle['size'] if bundle.get('size') is not None else identity.get('zip_bytes'),
                    sdk_version=kernel.get('sdk_version'),external_sha256=kernel.get('source_sha256'),
                    timeout_ms=upload_timeout)
            except (OSError,ValueError,RuntimeError) as exc:
                raise DeferredWeb('上传诊断意图未能持久保存，未上传材料：'+str(exc)[:200]) from exc
            diagnostic=upload_trace.identity_fields(attempt);diagnostic.update(
                state='in_progress',started_at=attempt['started_at'])
            context['upload_attempt_id']=attempt['upload_attempt_id']
            context['upload_diagnostic']=diagnostic
            if callable(context.get('on_identified')):
                context['on_identified'](attempt['upload_attempt_id'],diagnostic)
            print(json.dumps({'event':'upload_started','at':attempt['started_at'],'file_count':len(files),
                  **{key:attempt[key] for key in ('upload_attempt_id','lane','job_id','target_id','zip_sha256',
                     'zip_bytes','sdk_version','external_sha256')}},ensure_ascii=False),flush=True)
            upload_started=time.monotonic();ready_started=time.monotonic();upload_result='failed';ready_stage=None
            detail=None;kind='unknown';result='unknown';retryable=False;receipt=None;exception=None
            try:
                wait_gpt_upload_ready(session.page)
                ready_stage={'stage':'upload_ready_gate','outcome':'ready',
                             'elapsed_seconds':round(time.monotonic()-ready_started,3)}
                if stopping():raise DeferredWeb('已暂停，未上传材料')
                if page_guard:page_guard()
                from .original_upload_http1 import armed
                def transfer_guard():
                    if stopping():raise DeferredWeb('已暂停，未转发原上传')
                    if page_guard:page_guard()
                from .local_file_upload import writer_for
                writer=writer_for(session.page,context,transfer_guard)
                if context.get('lane') == 'formula_only':
                    assigned_writer = writer
                    def write_document(locator, filename):
                        if not locator.evaluate(_DOCUMENT_INPUT):
                            raise ValueError('当前控件无法接收 ZIP，保留原页')
                        transfer_guard()
                        if assigned_writer is None:
                            locator.set_input_files(filename)
                        else:
                            assigned_writer(locator, filename)
                    writer = write_document
                with armed(session.page,context,transfer_guard):
                    detail=upload_files_detailed(session.page,files,timeout=upload_timeout,
                        **({'file_writer':writer} if writer is not None else {}))
                if diagnostic.get('local_file_write_state')=='unknown':
                    raise UncertainWeb('原本机附件赋值回执不确定，保留原页，不回退或重传')
                if diagnostic.get('original_put_unknown') is True:
                    raise UncertainWeb('原始附件PUT回执不确定，保留材料，不重传')
                if not detail['ok']:
                    kind=detail.get('failure_kind') or 'unknown'
                    retryable=bool(detail.get('retryable_upload'));result='failed'
                    # The kernel's own flag decides whether this counts toward a
                    # backoff; a stage label alone never makes a failure retryable.
                    stage=UPLOAD_STAGE_BY_KIND.get(kind) if retryable else None
                    raise UploadStageFailure('附件上传失败',stage) if stage else RuntimeError('附件上传失败')
                wait_gpt_upload_settled(session.page,upload_timeout,stopping)
                from .original_upload_http1 import native_settled
                native_settled(context)
                result='ok';kind='none';retryable=False;upload_result='settled'
                receipt=bool(detail.get('receipt_sufficient'))
            except Exception as exc:
                exception=exc
                if result=='unknown':
                    kind,retryable=_upload_failure(exc,detail)
                    result='deferred' if isinstance(exc,DeferredWeb) else ('failed' if kind!='unknown' else 'unknown')
                raise
            finally:
                stages=[ready_stage or {'stage':'upload_ready_gate','outcome':'failed',
                         'elapsed_seconds':round(time.monotonic()-ready_started,3)}]
                stages+=list((detail or {}).get('stages') or [])
                try:
                    closed=upload_trace.finish(attempt['upload_attempt_id'],result=result,
                        failure_kind=kind,retryable_upload=retryable,
                        stage=(detail or {}).get('stage') or kind,
                        exception_type=(type(exception).__name__ if exception else None),
                        exception_message=(str(exception) if exception else None),
                        receipt_sufficient=receipt,
                        bundle=(detail or {}).get('bundle'),stages=stages,
                        settle=(detail or {}).get('settle'),attachment=(detail or {}).get('attachment'))
                except Exception as exc:
                    raise DeferredWeb('上传结束回执未能持久保存，保留原页面待核对，不发送') from exc
                diagnostic.update(state=closed['state'],result=result,failure_kind=kind,
                                  retryable_upload=retryable,zip_sha256=closed['zip_sha256'],
                                  zip_bytes=closed['zip_bytes'],sdk_version=closed['sdk_version'],
                                  external_sha256=closed['external_sha256'],
                                  upload_failure_detail=((detail or {}).get('exception_message') or
                                      (type(exception).__name__+': '+str(exception) if exception else None)))
                context['upload_diagnostic']=diagnostic
                print(json.dumps({'event':'upload_finished','at':time.time(),'result':upload_result,
                      'duration_seconds':time.monotonic()-upload_started,
                      'upload_attempt_id':attempt['upload_attempt_id'],'lane':attempt['lane'],
                      'job_id':attempt['job_id'],'target_id':attempt['target_id'],
                      'zip_sha256':closed['zip_sha256'],'zip_bytes':closed['zip_bytes'],
                      'sdk_version':closed['sdk_version'],'external_sha256':closed['external_sha256'],
                      'upload_state':closed['state'],'failure_kind':kind,
                      'retryable_upload':retryable,'receipt_sufficient':receipt,
                      'zip_identity_mismatch':closed['zip_identity_mismatch']},ensure_ascii=False),flush=True)
    mark('post_upload_window_guard')
    with (nullcontext() if parallel_upload else lock()):
        if stopping():raise DeferredWeb('已暂停，未填入提示')
        if page_guard:page_guard()
        acknowledge_upload_notice()
        mark('prompt_input')
        box=wait_prompt_box(session.page);scope=_composer(session.page,box)
        from .web_editor_input import replace
        replace(box,prompt)
        if _dense(_box_text(box))!=_dense(prompt):raise RuntimeError('后台输入核对失败，未发送')
    # Read-only readiness polling yields on the original owner loop without
    # holding the shared send lock for up to 90 seconds. The target remains
    # exclusively owned by this upload job, and the prompt is checked again.
    mark('send_readiness')
    button,_,_=_wait_send_ready(session.page,scope,90000)
    if parallel_upload:
        if stopping():raise DeferredWeb('已暂停，未点击发送')
        if page_guard:page_guard()
        acknowledge_upload_notice()
        session.verify_settings()
    mark('final_send_lock')
    with lock():
        if stopping():raise DeferredWeb('已暂停，未点击发送')
        if page_guard:page_guard()
        dismissed_now=acknowledge_upload_notice()
        if _dense(_box_text(box))!=_dense(prompt):raise RuntimeError('后台输入核对失败，未发送')
        button,_,_=_wait_send_ready(session.page,scope,1000)
        if button is None or not _button_enabled(button):raise RuntimeError('后台发送按钮不可用，未发送')
        if not parallel_upload or dismissed_now:session.verify_settings()
        if notice_dismissed:
            filenames = session.page.locator(_COMPOSER_ATTACHMENT_BUTTONS).evaluate_all(
                r"buttons => buttons.map(el => el.getAttribute('aria-label').replace(/^(?:移除|Remove)\s+/, ''))"
            )
            if filenames != [detail['bundle']['zip_name']]:
                raise DeferredWeb('关闭聊天附件提示后，原附件清单已变化，未发送')
        prior=count_answers(session.page)
        users=session.page.locator('[data-chatgpt-search-unit-key$=":user"], [data-message-author-role="user"]');users_before=users.count()
        if stopping():raise DeferredWeb('已暂停，未点击发送')
        if page_guard:page_guard()
        mark('send_click_intent')
        on_before_send()
        if stopping():raise DeferredWeb('已暂停，保留原发送意图，未执行点击')
        session._pending_answer=prior
        button.evaluate('(el)=>el.click()',timeout=3000)
    mark('submission_acknowledgement')
    if not _sent(session.page,scope,box):raise RuntimeError('后台提交回执不确定，保留原会话，不重发')
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        from .web_message_text import read_user_text
        if users.count()>users_before and formal_gpt_url(session.page.url):
            text=read_user_text(users.last,prompt)
            if _dense(prompt) in _dense(text):return prior
            # Display expansion only; no prompt edits, clicks on send, or retries.
            if users.count()==1 and _dense(prompt[:200]) in _dense(text):
                from .web_message_text import EXPAND_JS
                expansion='\n'.join(line for line in EXPAND_JS.splitlines() if not ('stop-button' in line and '.some(visible)' in line))
                session.page.evaluate(expansion,{'user':'[data-chatgpt-search-unit-key$=":user"], [data-message-author-role="user"]','expectedPrefix':prompt[:200],'url':session.page.url})
        session.page.wait_for_timeout(250)
    raise RuntimeError('提交回执或正式会话URL尚未确认，保留页面，不重发')


def request(provider,packet,folder,policy,stopping=lambda:False,on_submitted=lambda:None):
    """Exactly one send per owned page. No shared-profile/anonymous fallback."""
    folder=Path(folder)
    if policy.get('shared_window',{}).get('enabled') or (len(folder.parents)>2 and (folder.parents[2]/'shared-gpt-window.json').exists()):
        raise DeferredWeb('共享专窗只允许原常驻所有者派发；遗留入口不另连CDP')
    import_root=str(Path(os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright'))))
    if import_root not in sys.path:sys.path.insert(0,import_root)
    from playwright.sync_api import sync_playwright
    from web_gpt import create_session
    from web_gpt.submission import submission_lock
    from web_gpt.core import ANSWER,STOP_BUTTON,_message_text
    from web_gpt.core import _ensure_cdp_page,wait_prompt_box
    from web_gpt.settings import configure_settings
    from web_gpt.qwen import ANSWER as QANSWER,USER as QUSER,STOP as QSTOP,message_text
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    from . import upload_trace
    # The owner that first registers the evidence directory owns that choice;
    # this legacy entry may fill an empty registration but never re-home the
    # durable evidence of a running owner.
    if upload_trace.root() is None:
        upload_trace.configure(folder.parents[2])
    if (folder/'attempt.json').exists():
        import shutil
        archive=folder/'history'/str(time.time_ns());archive.mkdir(parents=True)
        for name in ('attempt.json','error-page.txt','error-page.png'):
            if (folder/name).exists():shutil.copy2(folder/name,archive/name)
    attempt={'provider':provider,'state':'preflight','created':time.time(),'inputs':packet['input_hashes']}
    atomic_json(folder/'attempt.json',attempt)
    page=None;sent=False;send_started=False;browser=None
    pooled=provider=='chatgpt' and policy.get('background_no_create',False)
    reuse=provider=='qwen' and policy.get('reuse_single_window',False)
    window_path=folder.parents[2]/'qwen-window.json'
    window=None
    pw=sync_playwright().start()
    try:
        endpoint=os.environ.get({'qwen':'WEB_QWEN_CDP_URL','deepseek':'WEB_DEEPSEEK_CDP_URL'}.get(provider,'WEB_GPT_CDP_URL'),os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'))
        parsed=urlsplit(endpoint)
        if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('CDP必须是本机专用浏览器')
        import urllib.request
        with urllib.request.urlopen(endpoint+'/json/list',timeout=5) as stream:targets=json.load(stream)
        if not any(t.get('type')=='page' for t in targets):raise DeferredWeb('专用浏览器无页面；保持隐藏/关闭状态，不自动弹出窗口')
        try:browser=pw.chromium.connect_over_cdp(endpoint,timeout=10000,no_defaults=True)
        except Exception as exc:raise ProviderFailure('CDP连接失败：'+str(exc)[:500],provider,'network',True) from exc
        with submission_lock():
            if stopping():raise DeferredWeb('用户停止服务')
            try:control=json.loads((folder.parents[2]/'web-channel-control.json').read_text())
            except FileNotFoundError:control={}
            if control.get(provider,{}).get('manual_verification_required'):raise DeferredWeb('该网页通道等待用户手动访问验证')
            if not browser.contexts:raise ProviderFailure('CDP无浏览器上下文',provider,'network',True)
            if reuse:
                window=json.loads(window_path.read_text())
                if window.get('state')!='ready':raise DeferredWeb('Qwen 复用窗口待核对，暂停新提交')
                matches=[]
                for context in browser.contexts:
                    for candidate in context.pages:
                        target=context.new_cdp_session(candidate).send('Target.getTargetInfo')['targetInfo']['targetId']
                        if target==window['target_id']:matches.append(candidate)
                if len(matches)!=1:raise DeferredWeb('Qwen 固定窗口已关闭或不可唯一确认；不自动开新窗口')
                page=matches[0]
                attempt['reused_window']=True
                require_no_verification(page)
                from cards.api import web_card_inputs__digest as digest
                raw_path=Path(window['raw_path'])
                if page.url!=window['conversation_url'] or not raw_path.is_file() or digest(raw_path)!=window['raw_sha256']:raise DeferredWeb('Qwen 固定窗口或上次回答记录变化，暂停核对')
                answers=page.locator(QANSWER)
                if not answers.count() or message_text(answers.last)!=raw_path.read_text() or any(x.is_visible() for x in page.locator(QSTOP).all()):raise DeferredWeb('Qwen 上次回答未稳定或正文变化')
                window['state']='busy';atomic_json(window_path,window)
                page.get_by_role('button',name='新建对话',exact=True).click()
                page.wait_for_timeout(600)
                attempt['reused_window']=True
            elif pooled:
                from .shared_pool_store import load_pool,save_pool
                pool_path=folder.parents[2]/'gpt-window-pool.json';pool=load_pool(pool_path)
                candidates=[]
                for context in browser.contexts:
                    for candidate in context.pages:
                        target=context.new_cdp_session(candidate).send('Target.getTargetInfo')['targetInfo']['targetId']
                        entry=pool['windows'].get(target,{})
                        if entry.get('state')=='ready':candidates.append((candidate,target,entry))
                if not candidates:raise DeferredWeb('后台复用页均忙碌；不创建会弹出的窗口')
                page,target,entry=candidates[0]
                from cards.api import web_card_inputs__digest as digest
                raw=Path(entry['raw_path']);answers=page.locator(ANSWER)
                if page.url!=entry['conversation_url'] or not raw.is_file() or digest(raw)!=entry['raw_sha256'] or not answers.count() or _message_text(answers.last)!=raw.read_text():raise DeferredWeb('GPT后台复用页变化，等待核对')
                from .shared_pool_store import mark_verified_blank
                mark_verified_blank(entry)
                entry.update(state='busy',active_paper_id=folder.parent.name,kind='cards');save_pool(pool_path,pool);attempt['reused_window']=True
            else:
                if sum(len(c.pages) for c in browser.contexts)>=policy.get('max_total_pages',20):raise DeferredWeb('专用浏览器总页数已达20页，等待收取释放')
                if provider_page_count(browser,provider)>=policy.get('max_pages_per_provider',20):raise DeferredWeb(provider+' 已达20页，等待本任务页收取/关闭')
                context=browser.contexts[0]
                with context.expect_page(timeout=10000) as created:
                    browser.new_browser_cdp_session().send('Target.createTarget',{'url':'about:blank','background':True})
                page=created.value
            attempt['target_id']=page.context.new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId']
            atomic_json(folder/'attempt.json',attempt)
            if not reuse:page.goto(URLS[provider],wait_until='domcontentloaded',timeout=60000)
            require_no_verification(page)
            session=create_session(provider,thinking_high=False if provider=='chatgpt' else True,
                                   model=policy.get('qwen_model','Qwen3.8-Max') if provider=='qwen' else None)
            session.page=page
            if provider=='deepseek':session._browser=browser
            if provider=='chatgpt':
                # New-page navigation must remain empty; never inherit old scientific inputs.
                wait_prompt_box(page,timeout=30000)
                if page.locator(ANSWER).count() or page.locator('[data-message-author-role="user"]:visible').count():raise ValueError('GPT新页恢复了历史，禁止混用')
                session.settings=configure_settings(page,thinking_high=False)
            else:
                session._require_login();session._box();session._require_blank();session._configure();session.settings=session.verify_settings()
            attempt.update(settings=session.settings,conversation_url=page.url,state='ready')
            from .upload_quota import OBSERVER
            page.evaluate(OBSERVER)
            atomic_json(folder/'attempt.json',attempt)
        # The tool owns the global submit lock. Do not nest flock around submit.
        if stopping():raise DeferredWeb('用户停止服务')
        for name,expected in packet['input_hashes'].items():
            from cards.api import web_card_inputs__digest as digest
            if digest(folder.parent/name)!=expected:raise ValueError('提交前冻结材料改变')
        def before_send():
            nonlocal send_started
            send_started=True;attempt.update(state='submission_started',send_click_started=True)
            atomic_json(folder/'attempt.json',attempt)
        attempt['send_click_started']=False;atomic_json(folder/'attempt.json',attempt)
        actual_prompt=(folder.parent/'prompt.txt').read_text()
        bundle=None
        if provider=='chatgpt':
            from .web_upload_bundle import prepare_web_upload
            bundle,actual_prompt=prepare_web_upload(folder.parent,packet)
            attempt['upload_bundle']=bundle;atomic_json(folder/'attempt.json',attempt)
        if provider=='deepseek':
            actual_prompt+='\n本站图形视觉识别尚未通过实测。仅提取可读原文中的科学内容，不依据文件名或常识猜图形、曲线、颜色与子图结果。图形未核验和缺失视觉输入必须明确写入warnings及对应条目，不宣称已经核对图形。'
        (folder/'prompt-actual.txt').write_text(actual_prompt)
        attempt['actual_prompt_sha256']=digest(folder/'prompt-actual.txt');atomic_json(folder/'attempt.json',attempt)
        try:
            files=[bundle['zip_path']] if bundle else [str(folder.parent/n) for n in packet['files']]
            if provider=='chatgpt':
                def identified(identifier,detail):
                    attempt.update(upload_attempt_id=identifier,upload_diagnostic=detail)
                    atomic_json(folder/'attempt.json',attempt)
                prior=submit_gpt_background(session,actual_prompt,files,on_before_send=before_send,
                    upload_timeout=upload_settle_ms(policy,(packet.get('upload_bundle') or {}).get('size')),stopping=stopping,
                    upload_context={'lane':'cards','paper_id':folder.parent.name,'job_id':packet.get('job_id'),
                        'target_id':attempt.get('target_id'),'bundle':bundle,'on_identified':identified})
            else:
                before_send();prior=session.submit(actual_prompt,files=files)
        except Exception as exc:
            try:
                user_selector=QUSER if provider=='qwen' else '.ds-message:visible' if provider=='deepseek' else '[data-message-author-role="user"]:visible'
                users=page.locator(user_selector).count()
                answers=page.locator(session.answer_selector if provider=='deepseek' else QANSWER if provider=='qwen' else ANSWER).count()
                stop=page.locator(session.stop_selector if provider=='deepseek' else QSTOP if provider=='qwen' else STOP_BUTTON)
                unsent=not send_started and not users and not answers and not any(stop.nth(i).is_visible() for i in range(stop.count())) and urlsplit(page.url).path in ('','/')
                notice=visible_notice(page)
                error_text=str(exc)+' '+page.locator('body').inner_text(timeout=3000)[-4000:]
            except Exception:unsent=False;notice=None;error_text=str(exc)
            reset=_reset_timestamp(notice)
            raise ProviderFailure(error_text[:1200],provider,'quota' if notice else failure_kind(error_text),unsent,reset,reset_evidence=notice) from exc
        sent=True;attempt.update(state='submitted',prior_count=prior,conversation_url=page.url);atomic_json(folder/'attempt.json',attempt)
        on_submitted()
        selectors=(session.answer_selector,session.stop_selector,session.message_text) if provider=='deepseek' else (QANSWER,QSTOP,message_text) if provider=='qwen' else (ANSWER,STOP_BUTTON,_message_text)
        answer=session.collect(prior,answer_timeout=policy.get('answer_timeout_seconds',1800),stopping=stopping) if provider=='deepseek' else collect_owned(page,prior,provider,selectors,policy.get('answer_timeout_seconds',1800),stopping)
        (folder/'response-raw.txt').write_text(answer)
        answers=page.locator(selectors[0]);stop=page.locator(selectors[1])
        if any(stop.nth(i).is_visible() for i in range(stop.count())) or not answers.count() or selectors[2](answers.last)!=answer:raise ValueError('回答仍生成或正文不一致，保留原始文本但不当正式结果')
        if urlsplit(page.url).hostname not in HOSTS[provider] or not urlsplit(page.url).path.startswith('/a/chat/s/' if provider=='deepseek' else '/c/'):raise ValueError('缺少正式独立会话URL')
        attempt.update(state='response_saved',conversation_url=page.url,raw_sha256=digest(folder/'response-raw.txt'))
        atomic_json(folder/'attempt.json',attempt)
        # Response is safely persisted even if its JSON subsequently needs repair.
        try:
            with submission_lock():
                if reuse:
                    if sum(x.url==page.url for c in browser.contexts for x in c.pages)!=1:raise ValueError('Qwen会话URL不唯一')
                    window.update(state='ready',conversation_url=page.url,raw_path=str((folder/'response-raw.txt').resolve()),raw_sha256=attempt['raw_sha256'])
                    atomic_json(window_path,window)
                    attempt['tab_cleanup']='preserved_reusable_window'
                elif pooled:
                    release_gpt_pool(folder,page,attempt);attempt['tab_cleanup']='preserved_reusable_window'
                else:
                    page.close();attempt['tab_cleanup']='closed_saved_response'
        except Exception as exc:attempt['tab_cleanup_error']=type(exc).__name__
        atomic_json(folder/'attempt.json',attempt)
        return answer,attempt
    except Exception as exc:
        if isinstance(exc,DeferredWeb):attempt['state']='deferred'
        else:attempt['state']='needs_inspection' if sent or send_started and not isinstance(exc,ProviderFailure) or isinstance(exc,ProviderFailure) and not exc.unsent else 'not_sent'
        error_text=str(exc)
        reset=None;notice=None
        if page is not None:
            try:
                error_text+=' '+page.locator('body').inner_text(timeout=3000)[-4000:]
                notice=visible_notice(page)
                reset=_reset_timestamp(notice)
            except Exception:pass
        attempt.update(error=type(exc).__name__+': '+str(exc)[:1200],finished=time.time())
        if failure_kind(error_text)=='verification':
            attempt['tab_cleanup']='preserved_verification'
            if page is not None:attempt['conversation_url']=page.url
            exc=ProviderFailure('访问验证：请在专用浏览器手动验证；保留本任务页',provider,'verification',getattr(exc,'unsent',not sent and not send_started))
        elif reuse or pooled:
            attempt['tab_cleanup']='preserved_reusable_window'
            if window is not None and window.get('state')=='busy':
                window.update(state='needs_inspection',error=str(exc));atomic_json(window_path,window)
                error=ProviderFailure('固定Qwen窗口需要核对：'+str(exc),provider,'verification',False)
                Router(window_path.parent).block(error)
        else:
            with submission_lock():owned_error_cleanup(page,folder,attempt)
        atomic_json(folder/'attempt.json',attempt)
        if isinstance(exc,(DeferredWeb,ProviderFailure)):raise
        kind=failure_kind(error_text)
        if not send_started and 'goto' in str(exc) and 'Timeout' in str(exc):kind='network'
        raise ProviderFailure(str(exc)[:1200],provider,kind,not sent and not send_started,reset,reset_evidence=notice if page is not None else None) from exc
    finally:
        pw.stop()


def run_with_failover(router,packet,folder,policy,request_fn=request,stopping=lambda:False):
    excluded=[]
    while True:
        # Avoid forty threads timing out on the shared lock or dispatching a
        # provider chosen before another worker observed its account limit.
        held=False
        def release():
            nonlocal held
            if held:held=False;PREPARE_GATE.release()
        if request_fn is request:
            while not PREPARE_GATE.acquire(timeout=1):
                if stopping():raise DeferredWeb('用户停止服务')
            held=True
        try:
            provider=router.choose(excluded)
            if request_fn is request:return request_fn(provider,packet,Path(folder)/provider,policy,stopping,on_submitted=release),provider
            return request_fn(provider,packet,Path(folder)/provider,policy,stopping),provider
        except ProviderFailure as exc:
            router.block(exc)
            if not exc.unsent:raise UncertainWeb('原请求可能已发送；错误页面已归档/关闭，保存原URL待核对，不跨模型重发') from exc
            if exc.kind not in ('quota','network'):raise
            excluded.append(provider)
            if len(excluded)>=2:raise DeferredWeb('两个网页通道均暂不可用，已关闭本任务错误页，等待通道恢复') from exc
        finally:release()
