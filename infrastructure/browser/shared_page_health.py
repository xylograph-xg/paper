"""Read-only health evidence for fixed shared pages; no close/create or writes.

The CDP owner must establish the page's window/ownership before calling
``snapshot_page``. ``classify`` only recommends a lifecycle action: the owner
must archive evidence and recheck it under its lock before replacing a page.
An error recommendation never authorizes resending or changing a sent attempt
to an unsent state. Scientific cards, controls and registries are untouched.
"""
import hashlib
import json
import re
import time
from .account_readiness import READINESS_UI_SCRIPT
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit


MIN_STABLE_SECONDS = 10
ACTIVE_STATES = frozenset(('busy', 'submitting', 'collecting', 'preparing'))
SENT_STATES = frozenset(('submitted', 'submission_started', 'needs_inspection'))
NETWORK_FAILURE = re.compile(r'ERR_(?:PROXY_CONNECTION_FAILED|INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|NETWORK_CHANGED|CONNECTION_(?:CLOSED|RESET|REFUSED|TIMED_OUT)|TIMED_OUT)')
SITE_BLOCK = re.compile(r'Unable to load site|If you are using a VPN|Check the status page for information on outages|\[IP:\s*\d', re.I)
SITE_BLOCK_ERROR = '站点加载失败：Unable to load site（Cloudflare/IP 拦截）'
MARKER = re.compile(r'web-card-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-[^\s]*|card-review-[a-f0-9]{24}')
QUOTA = re.compile(r'quota|limit reached|too many (?:files|uploads|requests|messages)|(?:upload|usage|message|request|file|attachment|rate).{0,40}limit|(?:reached|hit|exceeded).{0,50}(?:limit|quota)|(?:附件|上传|文件|用量|使用|请求|消息).{0,30}(?:上限|限制|额度)|(?:达到|已达|已用完).{0,30}(?:上限|限制|额度)', re.I)
PAGE_FAILURE = re.compile(r'ERR_(?:SSL|CERT|NETWORK|INTERNET|CONNECTION|NAME|TIMED)|net::|SSL(?:_|\s|error)|TLS error|certificate error|附件上传失败|附件仍在上传|upload failed|file upload failed', re.I)
TERMINAL_FAILURE = re.compile(r'(?:something|an error) went wrong|generation (?:failed|stopped)|response (?:failed|stopped)|error (?:generating|producing)|stopped (?:thinking|generating)|思考已停止|已停止思考|生成失败|回答失败|发生错误|出了点问题|未能生成|网页报错', re.I)
HOMEPAGE_FAILURE = re.compile(r'请(?:尝试重新加载|重试)[，,]\s*或退出登录后重新登录[。.!！]?')


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dense(text):
    return re.sub(r'\s+', '', text)


def _formal(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'chatgpt.com' and
            parsed.path.startswith('/c/') and len(parsed.path) > 3 and
            'local-chatgpt' not in parsed.path)


LOGIN_UI_SCRIPT = r'''() => {
  const visible = el => {
    if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]') ||
        ['hidden','collapse'].includes(getComputedStyle(el).visibility)) return false;
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
  };
  const excluded = el => !!el.closest('[data-message-author-role],[data-conversation-role],\
    [data-talvt-turn-state],[contenteditable="true"],textarea,pre,code');
  const label = el => (el.getAttribute('aria-label') || el.innerText || el.textContent || '')
    .replace(/\s+/g,' ').trim();
  const evidence = [];
  const add = (source, text) => { if (evidence.length < 6) evidence.push({source, text}); };
  const host = location.hostname;
  if ((host === 'chatgpt.com' && /^\/auth\/(?:login|signin|log-in)(?:\/|$)/.test(location.pathname)) ||
      (host === 'auth.openai.com' && /^\/(?:log-in|login|u\/login|authorize)(?:\/|$)/.test(location.pathname)))
    add('auth_location', host + location.pathname);
  const loginLabel = /^(?:log\s*in|sign\s*in|登录|登入|重新登录|再次登录|登录\s*[\/或]\s*注册)$/i;
  for (const el of document.querySelectorAll('a,button,[role="button"],input[type="submit"]')) {
    if (!visible(el) || excluded(el)) continue;
    const text = label(el);
    if (loginLabel.test(text)) { add('visible_login_control', text); continue; }
    if (el.matches('[data-testid="login-button"],[data-testid="login"]')) {
      add('visible_login_testid', 'login control'); continue;
    }
    if (el.matches('a[href]')) {
      try {
        const u = new URL(el.getAttribute('href'), location.href);
        if ((u.hostname === 'chatgpt.com' && /^\/auth\/(?:login|signin|log-in)(?:\/|$)/.test(u.pathname)) ||
            (u.hostname === 'auth.openai.com' && /^\/(?:log-in|login|u\/login|authorize)(?:\/|$)/.test(u.pathname)))
          add('visible_login_link', u.hostname + u.pathname);
      } catch (_) {}
    }
  }
  const notice = /^(?:log\s*in to (?:chatgpt|continue)|sign\s*in to (?:chatgpt|continue)|please (?:log|sign)\s*in(?: to continue)?|your session (?:has )?expired|session expired|登录\s*ChatGPT|请(?:先|重新)?登录(?:后继续|以继续)?|登录以继续|登录后继续|登录已过期|会话已过期)[.!。！]?$/i;
  for (const el of document.querySelectorAll('[role="dialog"],[role="alertdialog"],[role="alert"],h1,h2')) {
    if (visible(el) && !excluded(el) && notice.test(label(el)))
      add('visible_login_notice', label(el));
  }
  return {login: evidence.length > 0, login_detection_version: 2, login_evidence: evidence,
    ...(''' + READINESS_UI_SCRIPT + r''')()};
}'''


_HEALTH_SCRIPT = r'''({user, answer, stop, progress}) => {
          const visible = el => {
            if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]') ||
                ['hidden','collapse'].includes(getComputedStyle(el).visibility)) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          const text = el => el ? (el.innerText || el.textContent || '') : '';
          const users = Array.from(document.querySelectorAll(user));
          // ANSWER is a Playwright selector; :visible is not native CSS.
          const answerNodes = Array.from(document.querySelectorAll(answer.replace(/:visible\b/g, '')));
          const answers = answerNodes.filter(visible);
          const turns = Array.from(document.querySelectorAll('[data-talvt-turn-state]'));
          const last = turns.at(-1);
          const assistantMarker = '[data-message-author-role="assistant"],h4[data-conversation-role="assistant"],[data-chatgpt-search-unit-key$=":assistant"]';
          const systemMarker = '[data-message-author-role="system"],h4[data-conversation-role="system"]';
          const assistantTurn = last && (last.matches(assistantMarker) ||
            !!last.querySelector(assistantMarker) ||
            answers.some(a => last.contains(a)));
          const systemTurn = last && (last.matches(systemMarker) || !!last.querySelector(systemMarker));
          const complete = !!last && last.getAttribute('data-talvt-turn-state') === 'complete';
          const main = document.querySelector('main,[role="main"],#main');
          const visibleImages = main ? Array.from(main.querySelectorAll('img')).filter(visible) : [];
          const imageNotice = /图(?:像|片)(?:暂时)?不可用|(?:图像|图片)(?:无法加载|加载失败)|image (?:is )?(?:unavailable|not available)|could(?:n.t| not) load (?:the )?image/i;
          const noticeLines = main ? (main.innerText || '').split(/\n+/).map(s=>s.trim()).filter(s=>s.length<100 && imageNotice.test(s)) : [];
          const imageHealth = {visible_images:visibleImages.length,
            broken_images:visibleImages.filter(el=>el.complete && !el.naturalWidth && (el.currentSrc || el.getAttribute('src'))).length,
            notice_lines:noticeLines.slice(0,3),
            image_notice:noticeLines.length>0 || visibleImages.some(el=>imageNotice.test(el.alt))};
          const excluded = el => !!el.closest(user) ||
            !!el.closest('aside,nav,[role="navigation"],[data-testid*="sidebar"],footer');
          const errorNodes = Array.from(document.querySelectorAll('[role="alert"], [data-testid*="error"], #main-frame-error'))
            .filter(visible).filter(el => {
              if (el.id === 'main-frame-error') return true;
              if (!main || !main.contains(el) || excluded(el)) return false;
              const owner = el.closest('[data-talvt-turn-state]');
              return !owner || !!last && last.contains(el);
            });
          const errors = errorNodes.map(text).filter(Boolean);
          const statusScope = assistantTurn || systemTurn ? last : null;
          const statusSelector = '[role="status"],[role="alert"],[aria-live],[data-testid*="thinking"],[data-testid*="reasoning"],[data-testid*="generation"],[data-testid*="status"],button';
          const statusNodes = statusScope ? [statusScope, ...statusScope.querySelectorAll(statusSelector)] : [];
          // Role-less reasoning-only turns expose their own activity header,
          // before any assistant answer/role marker exists. Read only its live
          // UI status, never arbitrary text elsewhere in the combined turn.
          if (last) statusNodes.push(...last.querySelectorAll('[class~="group/activity-header"] [aria-live]'));
          const terminalStopped = statusNodes.filter(visible).filter(el => !excluded(el) && el.matches(statusSelector))
            .some(el => /^(?:stopped thinking|stopped generating|analysis paused|thinking paused|思考已停止|已停止思考|已停止生成|分析已暂停|已暂停分析|思考已暂停|已暂停思考)[\s.!。！]*$/i.test(text(el).trim()));
          // Match find_prompt_box: first selector with a visible candidate,
          // last visible candidate within that selector. A hidden duplicate or
          // an unrelated first textarea must not certify an empty composer.
          let box = null;
          // CSS locator visibility does not exclude aria-hidden/inert nodes;
          // get_by_role does. Match both branches of the submission reader.
          const composerVisible = el => {
            if (!el || ['hidden','collapse'].includes(getComputedStyle(el).visibility)) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          for (const [selector, check] of [
              ['#prompt-textarea',composerVisible],
              ['[role="textbox"],textarea:not([role]),input:not([role]):not([type]),input:not([role])[type="text"],input:not([role])[type="email"],input:not([role])[type="tel"],input:not([role])[type="url"]',visible],
              ['div[contenteditable="true"]',composerVisible],['textarea',composerVisible]]) {
            const candidates = Array.from(document.querySelectorAll(selector)).filter(check);
            if (candidates.length) { box = candidates.at(-1); break; }
          }
          const composer = box && (box.closest('form,[data-composer-body]') || box.parentElement?.parentElement);
          const messageContent = '[data-message-author-role="user"],[data-message-author-role="assistant"],[data-conversation-role="user"],[data-conversation-role="assistant"]';
          // Native stream failures are alerts rendered as <aside> within the
          // current transcript turn. Generic alerts exclude sidebars.
          const transcript = main?.querySelector('[data-thread-find-target="conversation"]');
          const currentTurn = transcript && Array.from(transcript.querySelectorAll('[data-turn-key]')).at(-1);
          const streamError = currentTurn && Array.from(currentTurn.querySelectorAll('aside[role="alert"].text-danger'))
            .filter(el => visible(el) && !excluded(el.parentElement) && !el.closest(messageContent) &&
              !el.closest('form,[contenteditable="true"],pre,code') &&
              !answerNodes.some(a => a.contains(el) || el.contains(a)))
            .map(el => text(el).trim().replace(/\s+/g, ' '))
            .find(label => /^(?:消息传输超时。请重试。|消息流中的错误)(?:\s*重试)?$/.test(label));
          const pageErrorNotices = errorNodes.filter(el => main && main.contains(el) &&
            !el.closest('[data-talvt-turn-state]') && !el.closest(messageContent) && !el.querySelector(messageContent) &&
            !users.some(u => u === el || u.contains(el) || el.contains(u)) &&
            !answerNodes.some(a => a === el || a.contains(el) || el.contains(a)) &&
            !(composer && (composer === el || composer.contains(el) || el.contains(composer))))
            .map(el => ({text: text(el).trim(), source: 'visible_main_notice_ui'})).filter(n => n.text);
          const attachments = composer ? Array.from(composer.querySelectorAll('[data-testid*="attachment"], [data-testid*="file-thumbnail"], [data-testid*="file-upload"], [data-testid="attachment-preview"], [data-composer-attachments] button[aria-label^="移除 "], [data-composer-attachments] button[aria-label^="Remove "]'))
            .filter(visible).length : 0;
          const attachmentNames = composer ? Array.from(composer.querySelectorAll('[data-composer-attachments] button[aria-label^="移除 "], [data-composer-attachments] button[aria-label^="Remove "]'))
            .map(el => el.getAttribute('aria-label').replace(/^(?:移除|Remove)\s+/,'')) : [];
          const uploading = !!composer && Array.from(composer.querySelectorAll(progress || '[role="progressbar"], [data-testid*="progress"], [aria-label*="Uploading"], [aria-label*="上传中"]')).some(visible);
          // Science, quotations, drafts and old conversation turns are not UI
          // notices. In particular "达到…限制" and "too many" in a paper must
          // never freeze a completed page or fabricate a quota reset time.
          const quotaPattern = /quota|limit reached|too many (?:files|uploads|requests|messages)|(?:upload|usage|message|request|file|attachment|rate).{0,40}limit|(?:reached|hit|exceeded).{0,50}(?:limit|quota)|(?:附件|上传|文件|用量|使用|请求|消息).{0,30}(?:上限|限制|额度)|(?:达到|已达|已用完).{0,30}(?:上限|限制|额度)/i;
          const quotaExcluded = el => excluded(el) || !!el.closest(messageContent) ||
            answers.some(a => a === el || a.contains(el) || el.contains(a)) ||
            users.some(u => el.contains(u)) || !!el.querySelector(messageContent) ||
            !!box && (el === box || el.contains(box) || box.contains(el));
          const noticeSelector = '[role="alert"],[role="alertdialog"],[role="dialog"],[role="status"],[role="menu"],[role="tooltip"],[data-radix-popper-content-wrapper],[data-sonner-toast],[data-testid*="toast"],[data-testid*="notification"],[data-testid*="quota"],[data-testid*="limit"],[data-testid*="error"]';
          const noticeNodes = Array.from(document.querySelectorAll(noticeSelector))
            .filter(visible).filter(el => !quotaExcluded(el)).filter(el => {
              const owner = el.closest('[data-talvt-turn-state]');
              return !owner || !!last && owner === last;
            });
          // A current explicit system turn may carry a terminal limit message
          // without a toast/ARIA wrapper. Assistant text never gets this path.
          if (systemTurn && visible(last) && !quotaExcluded(last)) noticeNodes.push(last);
          const quotaNotices = [];
          const seenNotices = new Set();
          for (const el of noticeNodes) {
            const notice = text(el).trim();
            if (!notice || !quotaPattern.test(notice) || seenNotices.has(notice)) continue;
            seenNotices.add(notice);
            quotaNotices.push({text: notice.slice(0,2000),
              source: el === last && systemTurn ? 'current_system_turn' : 'visible_notice_ui',
              role: el.getAttribute('role'), testid: el.getAttribute('data-testid')});
            if (quotaNotices.length >= 8) break;
          }
          const body = document.body ? text(document.body) : '';
          const account = (''' + LOGIN_UI_SCRIPT + r''')();
          const verification = Array.from(document.querySelectorAll('#nocaptcha,[class*="captcha"]')).some(visible) ||
            /verify (?:you are|that you)|verification required|验证您是真人|人机验证|访问验证/i.test(body);
          const modelControls = composer ? Array.from(composer.querySelectorAll('button'))
            .filter(visible).map(el => (el.getAttribute('aria-label') || text(el)).trim())
            .filter(label => /GPT|模型|model|思考|thinking|High|高/i.test(label)).slice(0,12) : [];
          const effortButtons = composer ? Array.from(composer.querySelectorAll('button')).filter(el =>
            visible(el) && (el.hasAttribute('data-selected-reasoning-effort') ||
              /^(选择 ChatGPT 模型|Select ChatGPT model|思考强度|Thinking effort)$/i.test(el.getAttribute('aria-label') || ''))) : [];
          const effortButton = effortButtons.length === 1 ? effortButtons[0] : null;
          const pickerState = effortButton ? {label:(effortButton.innerText || '').trim().slice(0,80),
            effort:effortButton.getAttribute('data-selected-reasoning-effort'),
            disabled:effortButton.disabled || effortButton.getAttribute('aria-disabled') === 'true'} : null;
          const navigation = globalThis.performance?.getEntriesByType?.('navigation')?.[0];
          const errorPage = (document.documentURI || '').startsWith('chrome-error://');
          const load = {ready_state:document.readyState, was_discarded:document.wasDiscarded === true,
            navigation_type:navigation?.type || '', started_at:globalThis.performance?.timeOrigin / 1000,
            browser_error:errorPage, error_code:errorPage ?
              (document.querySelector('.error-code')?.textContent || '').trim().slice(0,100) : ''};
          return {url: location.href, page_load:load, image_health:imageHealth, user_texts: users.map(text), composer_available: !!box,
            model_controls: modelControls, effort_control:pickerState,
            answer_element_count: answerNodes.length,
            answer_variants: answers.map(el => [el.textContent || '',el.innerText || '']),
            draft: box ? (/^(TEXTAREA|INPUT)$/.test(box.tagName) ? (box.value || '') :
              (box.textContent || box.innerText || '')) : '',
            attachments: Math.max(attachments, attachmentNames.length),
            attachment_names: attachmentNames, uploading, streaming: Array.from(document.querySelectorAll(stop)).some(visible),
            terminal_complete: complete && assistantTurn,
            user_turn_complete: complete && !assistantTurn,
            terminal_stopped: terminalStopped,
            terminal_stream_error: streamError || '',
            login: account.login, login_detection_version: account.login_detection_version,
            login_evidence: account.login_evidence,
            account_ready: account.account_ready, account_authenticated: account.account_authenticated,
            authenticated_evidence: account.authenticated_evidence, account_ui_blocked: account.account_ui_blocked,
            verification, errors, body, page_error_detection_version: 1, page_error_notices: pageErrorNotices,
            quota_detection_version: 1, quota_notices: quotaNotices,
            quota_notice: quotaNotices.map(n => n.text).join('\n\n').slice(0,4000),
            quota: quotaNotices.length > 0};
        }'''


def snapshot_page(target_id, page):
    """Read one already-owned page; never focus, navigate, click or wait on it.

    ``terminal_complete`` is an assistant completion indicator. A user turn's
    ``complete`` attribute is recorded separately and cannot prove termination.
    Exceptions produce inspection evidence and never permission to replace.
    """
    from web_gpt.core import ANSWER, STOP_BUTTON, PROGRESS_BAR, _parses_as_json
    from .web_card_pool import USER
    try:
        from .owner_browser_calls import bounded_call
        result = bounded_call(page, 'evaluate', _HEALTH_SCRIPT,
                              {'user': USER, 'answer': ANSWER, 'stop': STOP_BUTTON,'progress':PROGRESS_BAR}, timeout=3)
        return _snapshot_result(target_id, result)
    except Exception as exc:
        return {'target_id': target_id, 'url': page.url, 'checked_at': time.time(),
                'inspection_complete': False, 'inspection_error': str(exc)[:500]}


def _snapshot_result(target_id, result):
    from web_gpt.core import _parses_as_json
    if not isinstance(result, dict):
        raise ValueError('页面快照不是对象')
    if 'answer_variants' in result:
        result['answer_texts'] = [next((text for text in variants if text and _parses_as_json(text)),
                                      next((text for text in variants if text), ''))
                                  for variants in result.pop('answer_variants')]
        result['answer_texts'] = [text for text in result['answer_texts'] if text.strip()]
    if SITE_BLOCK.search(str(result.get('body') or '')):
        result['site_blocked'] = True
        errors = list(result.get('errors') or [])
        if SITE_BLOCK_ERROR not in errors:
            errors.append(SITE_BLOCK_ERROR)
        result['errors'] = errors
    return {**result, 'target_id': target_id, 'checked_at': time.time(), 'inspection_complete': True}

def _snapshot_pages(pages, *, reader=snapshot_page):
    """Read only already-window-verified targets concurrently on their owner loop.

    Each renderer has the same three-second deadline. No new CDP connection,
    navigation, sending or cancellation of uploads is performed. Late or failed
    reads remain inspection failures; destructive steps still recheck live pages.
    """
    from playwright._impl._sync_base import SyncBase
    if not pages or not all(isinstance(p,SyncBase) for p in pages.values()):
        results={}
        for tid,page in pages.items():
            try:results[tid]=reader(tid,page)
            except Exception as exc:
                results[tid]={'target_id':tid,'url':page.url,'checked_at':time.time(),
                              'inspection_complete':False,
                              'inspection_error':type(exc).__name__+': '+str(exc)[:500]}
        return results
    import asyncio
    from web_gpt.core import ANSWER,STOP_BUTTON,PROGRESS_BAR
    from .web_card_pool import USER
    async def read(tid,page):
        try:
            result=await asyncio.wait_for(page._impl_obj.evaluate(_HEALTH_SCRIPT,
                {'user':USER,'answer':ANSWER,'stop':STOP_BUTTON,'progress':PROGRESS_BAR}),3)
            return tid,_snapshot_result(tid,result)
        except Exception as exc:
            return tid,{'target_id':tid,'url':page.url,'checked_at':time.time(),
                        'inspection_complete':False,
                        'inspection_error':type(exc).__name__+': '+str(exc)[:500]}
    async def gather():return dict(await asyncio.gather(*(read(tid,p) for tid,p in pages.items())))
    return next(iter(pages.values()))._sync(gather())

def _normal(snapshot):
    users = snapshot.get('user_texts', [])
    answers = snapshot.get('answer_texts', [])
    if (not isinstance(users, list) or not all(isinstance(v, str) for v in users) or
            not isinstance(answers, list) or not all(isinstance(v, str) for v in answers)):
        raise ValueError('用户或回答快照不可核对')
    # Empty assistant DOM containers and whitespace placeholders are evidence
    # of an element, not a reply. Keep every nonempty answer's original bytes.
    return users, [answer for answer in answers if answer.strip()]


def _fingerprint(snapshot):
    users, answers = _normal(snapshot)
    value = {k: snapshot.get(k) for k in ('target_id', 'url', 'streaming', 'terminal_complete',
             'terminal_stopped', 'terminal_stream_error', 'user_turn_complete', 'login', 'verification', 'quota', 'quota_notice',
             'attachments', 'attachment_names', 'uploading', 'errors',
             'page_error_detection_version', 'page_error_notices', 'login_detection_version', 'login_evidence')}
    value.update(user_hashes=[_sha(v) for v in users], answer_hashes=[_sha(v) for v in answers],
                 draft_sha256=_sha(snapshot.get('draft', '')))
    return _sha(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _stable(snapshot, previous, checked_at):
    if not previous:
        return False
    prior = previous.get('evidence', previous)
    fingerprint = prior.get('fingerprint')
    at = prior.get('checked_at')
    if not fingerprint:
        try:
            fingerprint = _fingerprint(previous)
        except (ValueError, TypeError, KeyError):
            return False
        at = previous.get('checked_at')
    return (type(at) in (int, float) and checked_at - at >= MIN_STABLE_SECONDS and
            fingerprint == _fingerprint(snapshot))


def _records(attempt, record_paths):
    records = []
    if isinstance(attempt, dict):
        records.append(dict(attempt))
    for path in record_paths:
        try:
            record = json.loads(Path(path).read_text(encoding='utf-8'))
            if isinstance(record, dict):
                records.append({**record, '_ledger_path': str(Path(path).resolve())})
        except (OSError, ValueError):
            continue
    unique = {}
    for record in records:
        key = (record.get('_ledger_path'), record.get('target_id'), record.get('state'),
               record.get('raw_sha256'), record.get('actual_prompt_sha256'), record.get('conversation_url'))
        unique[key] = record
    return list(unique.values())


def _prompt(record, expected_prompt=None):
    if expected_prompt is not None:
        text = expected_prompt
    elif record.get('_ledger_path'):
        text = (Path(record['_ledger_path']).parent / 'prompt-actual.txt').read_text(encoding='utf-8')
    else:
        raise ValueError('缺少原实际提示文件')
    if not isinstance(text, str) or not text or _sha(text) != record.get('actual_prompt_sha256'):
        raise ValueError('原实际提示指纹缺失或变化')
    return text


def _receipt(snapshot, record, urls, expected_prompt=None):
    users, _ = _normal(snapshot)
    url = snapshot.get('url', '')
    if (record.get('target_id') != snapshot.get('target_id') or not _formal(url) or
            list(urls).count(url) != 1 or len(users) != 1):
        raise ValueError('原target、正式唯一URL或唯一用户消息未证实')
    recorded_url = record.get('conversation_url', '')
    if _formal(recorded_url) and recorded_url != url:
        raise ValueError('原正式会话URL变化')
    prompt = _prompt(record, expected_prompt)
    expected_marker = MARKER.findall(prompt)
    live_marker = MARKER.findall(users[0])
    if (len(expected_marker) != 1 or expected_marker != live_marker or
            _dense(prompt) not in _dense(users[0])):
        raise ValueError('原提示与唯一用户材料标识不一致')
    return {'actual_prompt_sha256': _sha(prompt), 'user_sha256': _sha(users[0]),
            'conversation_url': url, 'target_id': snapshot['target_id'],
            'ledger_path': record.get('_ledger_path'), 'ledger_state': record.get('state')}


def _uncollected_history(target_id, records):
    """A later unsent attempt cannot erase an older uncertain sent request."""
    outstanding = []
    for prior in records:
        if prior.get('target_id') != target_id or prior.get('state') not in SENT_STATES:
            continue
        completed = False
        for saved in records:
            if (saved.get('state') != 'response_saved' or saved.get('target_id') != target_id or
                    not prior.get('inputs') or saved.get('inputs') != prior.get('inputs') or
                    not prior.get('actual_prompt_sha256') or
                    saved.get('actual_prompt_sha256') != prior.get('actual_prompt_sha256') or
                    not _formal(prior.get('conversation_url', '')) or
                    saved.get('conversation_url') != prior.get('conversation_url') or
                    not saved.get('_ledger_path') or not saved.get('raw_sha256')):
                continue
            try:
                if (_prompt(saved) == _prompt(prior) and
                        _file_sha(Path(saved['_ledger_path']).parent / 'response-raw.txt') == saved['raw_sha256']):
                    completed = True
                    break
            except (OSError, ValueError):
                continue
        if not completed:
            outstanding.append(prior.get('_ledger_path') or prior.get('conversation_url') or '未收请求')
    return outstanding


def _saved(snapshot, entry, records, urls, expected_prompt, history_roots):
    """Find the completed original request even if latest is a new unsent review."""
    _, answers = _normal(snapshot)
    if not answers:
        return None
    wanted = entry.get('raw_sha256')
    url = snapshot.get('url', '')
    if not wanted:
        saved = [r for r in records if r.get('state') == 'response_saved' and
                 r.get('conversation_url') == url and r.get('target_id') == snapshot.get('target_id')]
        if len({r.get('raw_sha256') for r in saved}) == 1 and saved:
            wanted = saved[0].get('raw_sha256')
    if not wanted:
        return None
    if (entry.get('conversation_url') and entry['conversation_url'] != url) or _sha(answers[-1]) != wanted:
        raise ValueError('原已保存回答的实时指纹或URL变化')
    matching = []
    for record in records:
        if (record.get('state') != 'response_saved' or record.get('raw_sha256') != wanted or
                record.get('conversation_url') != url):
            continue
        try:
            # Explicit expected_prompt belongs only to the directly supplied
            # current record; archived originals use their own hashed prompt.
            receipt = _receipt(snapshot, record, urls,
                               expected_prompt if not record.get('_ledger_path') else None)
        except (OSError, ValueError):
            continue
        matching.append((record, receipt))
    if not matching:
        raise ValueError('未找到原已收取回答与实际提示绑定的完成账本')
    direct = Path(entry['raw_path']) if entry.get('raw_path') else None
    if direct and direct.is_file():
        if _file_sha(direct) != wanted:
            raise ValueError('原回答文件存在但指纹变化，不用备份覆盖')
        return {'raw_path': str(direct.resolve()), 'raw_sha256': wanted,
                'repair_raw_path': None, 'receipt': matching[0][1]}
    roots = {Path(record['_ledger_path']).parent.resolve() for record, _ in matching
             if record.get('_ledger_path')}
    candidates = set()
    expected_bytes = len(answers[-1].encode('utf-8'))
    for root in roots:
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                if path.stat().st_size != expected_bytes:
                    continue
                if _file_sha(path) != wanted:
                    continue
                # Its directory must have a hash/URL/prompt-bound original
                # ledger. Matching contents elsewhere are not identity proof.
                if any(record.get('_ledger_path') and
                       Path(record['_ledger_path']).parent.resolve() in path.resolve().parents
                       for record, _ in matching):
                    candidates.add(str(path.resolve()))
            except OSError:
                continue
    if len(candidates) != 1:
        raise ValueError('原回答归档文件未唯一匹配：' + str(len(candidates)))
    recovered = next(iter(candidates))
    return {'raw_path': recovered, 'raw_sha256': wanted, 'repair_raw_path': recovered,
            'receipt': matching[0][1]}


def _saved_prefix(snapshot, entry, records, urls):
    """An invalid JSON prefix may be completed, never a changed valid answer."""
    _, answers = _normal(snapshot)
    if len(answers) != 1 or snapshot.get('terminal_complete') is not True or snapshot.get('streaming') is not False:
        return None
    live = answers[0]
    try:
        if not isinstance(json.loads(live), dict):return None
    except ValueError:return None
    matches=[]
    for record in records:
        if (record.get('state') != 'response_saved' or record.get('target_id') != snapshot.get('target_id')
                or record.get('conversation_url') != snapshot.get('url') or not record.get('_ledger_path')
                or entry.get('conversation_url') != snapshot.get('url')
                or entry.get('raw_sha256') != record.get('raw_sha256')):
            continue
        try:
            receipt = _receipt(snapshot,record,urls)
            raw_path=Path(record['_ledger_path']).parent/'response-raw.txt'
            prefix_path=raw_path
            if _file_sha(raw_path) != record['raw_sha256']:
                # Resume only this journaled capture if a crash happened between
                # durable raw replacement and ledger replacement.
                journal=json.loads((raw_path.parent/'capture-completion.json').read_text())
                prefix_path=Path(journal['prefix_path'])
                if (journal['original_ledger_sha256'] != _file_sha(Path(record['_ledger_path']))
                        or journal['complete_sha256'] != _sha(live) or _file_sha(raw_path) != _sha(live)
                        or not prefix_path.resolve().is_relative_to(raw_path.parent.resolve())):
                    continue
            if prefix_path.is_symlink() or _file_sha(prefix_path) != record['raw_sha256']:continue
            prefix=prefix_path.read_text()
            if not prefix.strip().startswith('{') or len(prefix)>=len(live) or not live.startswith(prefix):continue
            try:json.loads(prefix)
            except ValueError:pass
            else:continue
            matches.append({'raw_path':str(raw_path.resolve()),'prefix_path':str(prefix_path.resolve()),
                'prefix_sha256':record['raw_sha256'],'complete_sha256':_sha(live),'receipt':receipt})
        except (OSError,ValueError,KeyError):continue
    return matches[0] if len(matches)==1 else None


def _empty_saved(snapshot, entry, records, urls):
    """Bind an existing empty artifact to its unique original saved receipt.

    A missing file, changed hash or nonempty saved answer is never interpreted
    as an empty response. Keep the original artifact and ledger untouched.
    """
    matching = []
    for record in records:
        if (record.get('state') != 'response_saved' or record.get('target_id') != snapshot.get('target_id') or
                record.get('conversation_url') != snapshot.get('url')):
            continue
        try:
            receipt = _receipt(snapshot, record, urls)
        except (OSError, ValueError):
            continue
        matching.append((record, receipt))
    if len(matching) != 1:
        raise ValueError('空保存物未绑定唯一原完成账本与实际提示')
    record, receipt = matching[0]
    if (entry.get('conversation_url') and entry['conversation_url'] != snapshot.get('url') or
            entry.get('raw_sha256') and entry['raw_sha256'] != record.get('raw_sha256')):
        raise ValueError('原页池的已保存回答指纹或URL与空保存物不同')
    if not record.get('_ledger_path') or not Path(record['_ledger_path']).is_file():
        raise ValueError('原完成账本文件不存在，不能证明空保存物')
    path = Path(record['_ledger_path']).parent / 'response-raw.txt'
    if not path.is_file() or path.is_symlink():
        raise ValueError('原回答文件不存在，不能因缺失当作空回答')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record.get('raw_sha256'):
        raise ValueError('原回答文件指纹变化，保留原页')
    if raw.decode('utf-8').strip():
        raise ValueError('原非空科学回答仍已保存；实时回答消失须保留原页')
    return {'empty_saved_artifact': True, 'raw_path': str(path.resolve()),
            'raw_sha256': record['raw_sha256'], 'receipt': receipt}


def _homepage_idle(snapshot):
    """Require a fully observed homepage without any request or account block."""
    if (snapshot.get('url', '').rstrip('/') != 'https://chatgpt.com' or
            snapshot.get('inspection_complete') is not True or
            snapshot.get('streaming') is not False or snapshot.get('login') or
            snapshot.get('verification') or snapshot.get('quota') or
            snapshot.get('draft', '').strip() or snapshot.get('attachments', 0)):
        return False
    users, answers = _normal(snapshot)
    return not users and not answers and not snapshot.get('answer_element_count', 0)


def _completed_target_history(target_id, records):
    relevant = [r for r in records if r.get('target_id') == target_id]
    if not relevant or _uncollected_history(target_id, relevant):
        return False
    saved = False
    for record in relevant:
        if record.get('state') in SENT_STATES:
            continue  # _uncollected_history already proved its matching completion.
        if record.get('state') in ('not_sent', 'deferred', 'ready') and record.get('send_click_started') is False:
            continue
        if record.get('state') != 'response_saved' or not record.get('_ledger_path') or not _formal(record.get('conversation_url', '')):
            return False
        try:
            _prompt(record)
            raw = Path(record['_ledger_path']).parent / 'response-raw.txt'
            if raw.is_symlink() or not raw.read_text().strip() or _file_sha(raw) != record.get('raw_sha256'):
                return False
        except (OSError, ValueError):
            return False
        saved = True
    return saved


def completed_homepage(snapshot, records):
    """A clean homepage is reusable only after the entire target history ends.

    The caller supplies the complete target index, including archives. URL or
    blank DOM alone never clears submitted/unknown requests. Verify saved bytes
    and prompts on disk; an empty artifact is not a completed scientific reply.
    """
    return (_homepage_idle(snapshot) and not snapshot.get('errors') and
            snapshot.get('composer_available') is not False and
            _completed_target_history(snapshot.get('target_id'), records))


def _homepage_error_notice(snapshot):
    """Only a scoped homepage UI loading notice may use the history proof."""
    if (type(snapshot.get('page_error_detection_version')) is not int or
            snapshot['page_error_detection_version'] != 1 or not _homepage_idle(snapshot)):
        return False
    notices = snapshot.get('page_error_notices')
    errors = snapshot.get('errors')
    if not isinstance(notices, list) or not notices or not isinstance(errors, list) or not errors:
        return False
    for notice in notices:
        if (not isinstance(notice, dict) or notice.get('source') != 'visible_main_notice_ui' or
                not isinstance(notice.get('text'), str) or not HOMEPAGE_FAILURE.fullmatch(notice['text'].strip())):
            return False
    if (not all(isinstance(error, str) for error in errors) or
            {error.strip() for error in errors} != {notice['text'].strip() for notice in notices}):
        return False
    return True


def _completed_homepage_error(snapshot, records):
    if not _homepage_error_notice(snapshot):return False
    if any(not record.get('_ledger_path') or not Path(record['_ledger_path']).is_file()
           for record in records if record.get('target_id') == snapshot.get('target_id')):
        return False
    return _completed_target_history(snapshot.get('target_id'), records)


def classify(snapshot, entry, attempt=None, *, urls=(), previous=None, record_paths=(),
             history_roots=(), expected_prompt=None, checked_at=None, target_history_complete=False):
    """Classify immutable evidence; never change a task, ledger or saved card.

    Pass all live URLs for uniqueness. ``record_paths`` includes original and
    history attempt records; each archive uses its own actual-prompt file.
    ``previous`` can be the prior snapshot or classification result. Stable
    error/assistant completion observations must be at least ten seconds apart.
    The latest ``not_sent`` attempt cannot replace an earlier saved response's
    prompt or identity. ``never_submitted=True`` is an explicit owner assertion
    for an enrolled blank page with complete submit-history inspection.
    """
    now = time.time() if checked_at is None else checked_at
    if checked_at is None and type(snapshot.get('checked_at')) in (int, float):
        now = snapshot['checked_at']
    evidence = {'checked_at': now, 'target_id': snapshot.get('target_id'),
                'url': snapshot.get('url'), 'entry_state': entry.get('state'),
                'ledger_state': attempt.get('state') if isinstance(attempt, dict) else None,
                'send_click_started': attempt.get('send_click_started') if isinstance(attempt, dict) else None}

    def result(health, reason, allowed=False, **extra):
        return {'health': health, 'replace_allowed': allowed, 'reason': reason,
                'evidence': dict(evidence), 'requeue_allowed': False,
                'collect_allowed': False, 'matched_record_path': None, **extra}

    if entry.get('owned') is False:
        return result('protected', '页面不属于本任务')
    if snapshot.get('inspection_complete') is not True:
        return result('inspection_required', '页面快照未完整读取')
    try:
        users, answers = _normal(snapshot)
        if not isinstance(snapshot.get('draft', ''), str) or type(snapshot.get('attachments', 0)) is not int:
            raise ValueError('草稿或附件状态不可核对')
        evidence.update(fingerprint=_fingerprint(snapshot), user_count=len(users), answer_count=len(answers),
                        streaming=snapshot.get('streaming'), terminal_complete=snapshot.get('terminal_complete'),
                        terminal_stopped=snapshot.get('terminal_stopped'),
                        user_turn_complete=snapshot.get('user_turn_complete'),
                        user_hashes=[_sha(v) for v in users], answer_hashes=[_sha(v) for v in answers],
                        draft_sha256=_sha(snapshot.get('draft', '')), attachments=snapshot.get('attachments', 0),
                        errors=snapshot.get('errors', []))
        evidence['snapshot'] = {k: snapshot.get(k) for k in ('target_id', 'url', 'checked_at', 'inspection_complete',
            'user_texts', 'answer_texts', 'draft', 'attachments', 'attachment_names', 'uploading', 'streaming', 'terminal_complete',
            'terminal_stopped', 'terminal_stream_error', 'user_turn_complete', 'login', 'login_detection_version', 'login_evidence', 'verification', 'quota', 'quota_detection_version',
            'quota_notice', 'quota_notices', 'errors', 'page_error_detection_version', 'page_error_notices',
            'composer_available', 'model_controls', 'site_blocked')}
        evidence['quota_notice'] = snapshot.get('quota_notice', '')
        evidence['quota_notices'] = snapshot.get('quota_notices', [])
    except (TypeError, ValueError):
        return result('inspection_required', '用户、回答、草稿或附件状态不可核对')
    if snapshot.get('verification'):
        return result('verification', '访问验证页面必须保留')
    if snapshot.get('login'):
        return result('login', '登录页面必须保留')
    current_notices = type(snapshot.get('quota_detection_version')) is int and snapshot['quota_detection_version'] == 1
    failure = '\n'.join(str(v) for v in snapshot.get('errors', []))
    attempt_error = str(attempt.get('error', '')) if isinstance(attempt, dict) else ''
    attempt_quota = bool(QUOTA.search(attempt_error))
    if attempt_error:
        evidence['historical_attempt_error'] = {
            'error': attempt_error[:2000], 'quota': attempt_quota,
            'state': attempt.get('state'), 'send_click_started': attempt.get('send_click_started'),
            'target_id': attempt.get('target_id'), 'ledger_path': attempt.get('_ledger_path')}
    # A fresh scoped reader is the authority for current UI notices. A previous
    # attempt's transport error remains immutable history, not evidence that a
    # now-clean page is still limited or broken. Old snapshots fail closed.
    if not current_notices:
        failure += '\n' + attempt_error
    legacy_quota = not current_notices and QUOTA.search(failure)
    if snapshot.get('quota') or legacy_quota:
        evidence['quota_source'] = 'live_notice_ui' if snapshot.get('quota') else 'attempt_error' if attempt_quota else 'legacy_error'
        return result('quota', '额度限制不是坏页，换页不能解除限制')
    if (snapshot.get('streaming') is False and (snapshot.get('terminal_complete') is True or
            snapshot.get('terminal_stopped') is True and entry.get('state') in ACTIVE_STATES or
            snapshot.get('terminal_stream_error') and not entry.get('submission_unknown'))
            and not answers and not snapshot.get('draft', '').strip()
            and not snapshot.get('attachments') and snapshot.get('uploading') is False
            and isinstance(attempt, dict) and attempt.get('state') in SENT_STATES
            and attempt.get('send_click_started') is True):
        try:
            evidence['receipt'] = _receipt(snapshot, attempt, urls, expected_prompt)
            return result('terminal_empty', '原唯一请求已终态但没有回答；只归档恢复页面，不重发原请求')
        except (OSError, ValueError):
            pass
    # A stale busy flag may outlive a durably saved answer. Only the owner's
    # complete target history and the normal saved-answer guards can clear it.
    stale_busy_candidate = (
        entry.get('state') == 'busy' and target_history_complete
        and snapshot.get('terminal_complete') is True
        and snapshot.get('uploading') is False and bool(answers)
        and isinstance(attempt, dict) and attempt.get('target_id') == snapshot.get('target_id')
        and (attempt.get('state') == 'response_saved' or
             (attempt.get('state') == 'not_sent' and attempt.get('send_click_started') is False
              and bool(attempt.get('finished'))))
    )
    if snapshot.get('streaming') is not False or (
            entry.get('state') in ACTIVE_STATES and not stale_busy_candidate):
        return result('busy', '生成或活动页面必须保留')
    if 'local-chatgpt' in snapshot.get('url', ''):
        return result('unknown', '临时会话不能证明已发送或未发送，保留原页')
    if entry.get('submission_unknown'):
        return result('unknown', '提交回执明确标为未知，保留原页')
    if (isinstance(attempt, dict) and attempt.get('state') == 'not_sent' and
            attempt.get('send_click_started') is not False):
        return result('unknown', '未发送标签缺少明确发送前证据，保留原页')
    if snapshot.get('uploading') is True:
        return result('uploading', '原页面仍真实上传附件，保留页面')
    if snapshot.get('draft', '').strip() or snapshot.get('attachments', 0):
        return result('dirty', '页面含草稿或附件，不能替换')
    if isinstance(attempt, dict) and attempt.get('state') in SENT_STATES and answers:
        try:
            _receipt(snapshot, attempt, urls, expected_prompt)
        except (OSError, ValueError):
            return result('unknown', '最新已发送/未知请求尚未绑定，不能借旧已保存回答释放页面')
    raw_path = Path(entry['raw_path']) if entry.get('raw_path') else None
    search_history = entry.get('state') == 'needs_inspection' or bool(entry.get('raw_sha256') and
                     (raw_path is None or not raw_path.is_file()))
    # Explicit history evidence must not disappear merely because a stale pool
    # entry calls a page ready/blank. Directory discovery remains conditional.
    paths = list(record_paths)
    if search_history:
        for root in history_roots:
            folder = Path(root)
            if folder.is_dir():
                paths.extend(folder.rglob('attempt.json'))
    elif raw_path:
        # Existing keeper format pairs the reply with its original attempt.
        # The name only finds metadata; hashes/URL/prompt establish identity.
        paths.append(raw_path.parent / 'attempt.json')
    records = _records(attempt, paths)
    if stale_busy_candidate and _uncollected_history(snapshot.get('target_id'), records):
        return result('busy', '同页仍有未收取的原请求，保留忙碌页')
    if completed_homepage(snapshot, records):
        evidence['completed_history_paths'] = [r.get('_ledger_path') for r in records]
        return result('healthy_blank', '原target全量历史均已结束且保存物指纹一致；当前主页无消息或草稿')
    stable = _stable(snapshot, previous, now)
    evidence['stable'] = stable
    if _completed_homepage_error(snapshot, records):
        evidence['completed_history_paths'] = [str(Path(r['_ledger_path']).resolve()) for r in records
                                               if r.get('target_id') == snapshot.get('target_id')]
        evidence['homepage_error_notice'] = '\n'.join(notice['text'] for notice in snapshot['page_error_notices'])
        if not stable:
            return result('waiting_stable', '主页UI加载错误与全量已结束历史已核对，等待第二次稳定检查')
        return result('completed_homepage_error', '主页UI加载错误已稳定且全量历史已结束，先归档再换页', True)
    try:
        saved = _saved(snapshot, entry, records, urls, expected_prompt, history_roots)
    except (OSError, ValueError) as exc:
        prefix = None if stale_busy_candidate else _saved_prefix(snapshot,entry,records,urls)
        if prefix:
            evidence.update(prefix)
            if stable:
                return result('saved_prefix_completion','原落盘为完整原回答的逐字JSON前缀，可保留旧物后补收',
                    collect_allowed=True,matched_record_path=prefix['receipt']['ledger_path'])
            return result('waiting_stable','原落盘JSON前缀与完整回答已绑定，等待第二次稳定核对')
        return result('saved_response_protected', str(exc))
    if saved:
        evidence.update(saved)
        matched = saved['receipt']['ledger_path']
        if stale_busy_candidate:
            original = next((r for r in records if r.get('_ledger_path') == matched), None)
            if (not original or not matched
                    or (entry.get('review_id') and entry['review_id'] != original.get('review_id'))):
                return result('busy', '已保存回答与原忙碌任务归属不一致')
            return result('raw_path_repair', '忙碌页原回答已完整保存并核对，可恢复原槽位',
                          repair_raw_path=saved['raw_path'], matched_record_path=matched)
        if saved['repair_raw_path']:
            return result('raw_path_repair', '唯一原回答归档文件已匹配，可修复路径',
                          repair_raw_path=saved['repair_raw_path'], matched_record_path=matched)
        visible_failure = '\n'.join(str(v) for v in snapshot.get('errors', []))
        if (PAGE_FAILURE.search(visible_failure) or TERMINAL_FAILURE.search(visible_failure)
                or SITE_BLOCK.search(visible_failure)):
            if stable:
                return result('completed_saved', '原回答、URL与提示已核对，稳定错误页可归档后替换', True,
                              matched_record_path=matched)
            return result('waiting_stable', '原回答已核对，等待第二次稳定错误证据',
                          matched_record_path=matched)
        return result('completed_saved', '原完整回答、URL与提示一致', matched_record_path=matched)
    if stale_busy_candidate:
        return result('busy', '原忙碌页尚未证明已有完整保存回答')
    if not answers and isinstance(attempt, dict) and attempt.get('state') == 'not_sent' and attempt.get('send_click_started') is False:
        outstanding = _uncollected_history(snapshot.get('target_id'), records)
        if outstanding:
            evidence['uncollected_history'] = outstanding
            return result('unknown', '同页仍有历史已发送或未知未收请求；新未发送记录不能释放原页面')
    # An unrelated old saved URL must not shadow a current terminated request.
    current_saved = any(r.get('state') == 'response_saved' and
                        r.get('target_id') == snapshot.get('target_id') and
                        r.get('conversation_url') == snapshot.get('url') for r in records)
    sent_current = isinstance(attempt, dict) and attempt.get('state') in SENT_STATES
    saved_history = any(r.get('state') == 'response_saved' and
                        r.get('target_id') == snapshot.get('target_id') for r in records)
    if not answers and (current_saved or (entry.get('raw_sha256') or saved_history) and not sent_current):
        try:
            empty = _empty_saved(snapshot, entry, records, urls)
            # A newer unknown request cannot be released using an old receipt.
            if isinstance(attempt, dict) and attempt.get('state') in SENT_STATES:
                current_receipt = _receipt(snapshot, attempt, urls, expected_prompt)
                if current_receipt['actual_prompt_sha256'] != empty['receipt']['actual_prompt_sha256']:
                    raise ValueError('新未知请求与原空保存物提示不同，保留原页')
        except (OSError, ValueError) as exc:
            return result('saved_response_protected', str(exc))
        evidence.update(empty)
        matched = empty['receipt']['ledger_path']
        if snapshot.get('terminal_complete') is not True:
            return result('saved_response_protected', '空保存物未有当前assistant完成证据', matched_record_path=matched)
        if not stable:
            return result('waiting_stable', '原空保存物与assistant完成已绑定，等待第二次稳定检查',
                          matched_record_path=matched)
        return result('terminal_no_response', '原已保存物为空且当前assistant已稳定完成；保留空物与账本归档后换页', True,
                      matched_record_path=matched,
                      terminal_error={'target_id': snapshot['target_id'], 'conversation_url': snapshot['url'],
                                      'original_state': 'response_saved', 'empty_saved_artifact': True,
                                      'requeue_allowed': False})
    if isinstance(attempt, dict) and attempt.get('state') in SENT_STATES:
        try:
            evidence['receipt'] = _receipt(snapshot, attempt, urls, expected_prompt)
        except (OSError, ValueError) as exc:
            return result('unknown', str(exc))
        if answers:
            if snapshot.get('terminal_complete') is not True:
                return result('unknown', '已有回答但缺少assistant完成证据，只保留原页')
            if not stable:
                return result('waiting_stable', '等待第二次原完整回答与assistant完成证据')
            evidence.update(raw=answers[-1], raw_sha256=_sha(answers[-1]))
            return result('completed_unsaved', '原唯一请求与正式完整回答已稳定核对，可原样收取',
                          collect_allowed=True, matched_record_path=evidence['receipt']['ledger_path'])
        visible_failure = '\n'.join(str(v) for v in snapshot.get('errors', []))
        terminal = (snapshot.get('terminal_stopped') is True or TERMINAL_FAILURE.search(visible_failure) or
                    snapshot.get('terminal_complete') is True)
        if not terminal:
            return result('unknown', '只有用户turn完成或空白回答，不能证明原请求终止')
        if not stable:
            return result('waiting_stable', '原唯一正式请求已核对，等待第二次终止失败/完成证据')
        return result('terminal_no_response', '原唯一正式请求已稳定终止且无正式回答，先归档错误再换页', True,
                      matched_record_path=evidence['receipt']['ledger_path'],
                      terminal_error={'target_id': snapshot['target_id'], 'conversation_url': snapshot['url'],
                                      'original_state': attempt['state'], 'send_click_started': attempt.get('send_click_started'),
                                      'requeue_allowed': False})
    unused_owned_repair = (entry.get('never_submitted') is True and not records
        and target_history_complete is True and entry.get('origin') == 'shared_page_health_repair'
        and bool(entry.get('repair_id')))
    # Startup tabs are enrolled as ``opening`` before any material is attached.
    # They must be replaceable after a stable proxy/network error too; otherwise
    # a whole batch of failed startup tabs has no legal recovery path.  A real
    # attempt record, unknown submission or incomplete history still wins.
    startup_never_submitted = (entry.get('state') == 'opening'
        and entry.get('never_submitted') is True and not records
        and target_history_complete is True and entry.get('submission_unknown') is not True)
    unused_owned_page = unused_owned_repair or startup_never_submitted
    if entry.get('submission_unknown') or entry.get('state') == 'needs_inspection' and not isinstance(attempt, dict) and not unused_owned_page:
        return result('unknown', '没有原提交账本，不能因空白或错误释放页面')
    known_unsent = (isinstance(attempt, dict) and attempt.get('state') == 'not_sent' and
                   attempt.get('send_click_started') is False)
    never_submitted = (entry.get('state') == 'ready_blank' and entry.get('never_submitted') is True and not records) or unused_owned_page
    if known_unsent or never_submitted:
        outstanding = _uncollected_history(snapshot.get('target_id'), records)
        if outstanding:
            evidence['uncollected_history'] = outstanding
            return result('unknown', '同页仍有历史已发送或未知未收请求；新未发送记录不能释放原页面')
    if users or answers:
        return result('unknown', '页面有未绑定原请求或回答，保留待核对')
    page_failure = (PAGE_FAILURE.search(failure) or snapshot.get('url', '').startswith('chrome-error://')
                    or _homepage_error_notice(snapshot))
    if (page_failure and entry.get('state') == 'opening' and never_submitted
            and NETWORK_FAILURE.search(failure)):
        # The startup owner reloads this same page when the route returns; a
        # proxy outage is not a broken tab and must not churn twenty tabs.
        return result('network_unavailable', '网络/代理不可用，保留启动页等待重新加载')
    if page_failure and (known_unsent or never_submitted):
        if not stable:
            return result('waiting_stable', '明确未发送且空白的错误页，等待第二次稳定检查')
        return result('not_sent_error', '明确发送前失败且无消息/草稿/附件/生成，可归档后替换', True)
    if known_unsent or never_submitted or entry.get('state') == 'ready_blank' and not records:
        if snapshot.get('errors') or snapshot.get('composer_available') is False:
            return result('protected', '页面错误或输入框不可用，不能当作健康空白页；缺少已核对故障证据时保留')
        if never_submitted and target_history_complete is True:
            evidence['never_submitted_verified']=True
        return result('healthy_blank', '空白页面没有新请求，不需要更换')
    return result('protected', '缺少安全替换所需的原请求/终态证据')
