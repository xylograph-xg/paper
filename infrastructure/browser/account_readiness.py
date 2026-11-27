"""Recheck an already authenticated account; never authenticate or solve challenges."""
import hashlib
import json
import os
import time


READINESS_UI_SCRIPT = r'''() => {
  const visible = el => !!el && !el.closest('[hidden],[aria-hidden="true"],[inert]') &&
    !['hidden','collapse'].includes(getComputedStyle(el).visibility) &&
    el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
  const excluded = el => !!el.closest('[data-message-author-role],[data-conversation-role],[data-talvt-turn-state],[contenteditable="true"],textarea,pre,code');
  const profile = Array.from(document.querySelectorAll('[data-testid="accounts-profile-button"],[data-testid="profile-button"],[data-testid="user-menu-button"],button[aria-label="打开个人资料菜单"],button[aria-label="Open profile menu"],button[aria-label="Open account menu"]')).find(el => visible(el) && !excluded(el));
  const box = Array.from(document.querySelectorAll('#prompt-textarea,[role="textbox"][contenteditable="true"],div[contenteditable="true"],textarea')).find(el => visible(el) && !el.closest('[data-message-author-role],[data-conversation-role],[data-talvt-turn-state]'));
  const notices = Array.from(document.querySelectorAll('[role="alert"],[role="dialog"],[role="alertdialog"],[data-testid*="error"],[data-testid*="quota"],[data-testid*="limit"],#nocaptcha,[class*="captcha"]')).filter(el => visible(el) && !excluded(el));
  const notice = notices.map(el => el.innerText || el.textContent || '').join('\n');
  const blocked = notices.some(el => el.matches('#nocaptcha,[class*="captcha"]')) ||
    /quota|limit|too many|error|failed|verify|verification|额度|上限|限制|失败|错误|验证|重新加载/i.test(notice);
  const authenticated = location.hostname === 'chatgpt.com' && !!profile;
  return {account_authenticated: authenticated,
    authenticated_evidence: authenticated ? [{source:'visible_account_control',control:profile.getAttribute('data-testid') || profile.getAttribute('aria-label')}] : [],
    account_ready: authenticated && !!box && !blocked,
    composer_available: !!box, account_ui_blocked: blocked};
}'''


def recheck(root, pages, *, at=None, formula_window=False):
    """Two fresh checks of all original slots clear only an observed account gate."""
    from core.api import catalog__load_config as load_config,control__read_record as read_record
    from core.api import control__mutate_record as mutate_record,services__atomic_json as atomic_json
    from cards.api import web_card_service__owner_enabled as owner_enabled
    at=time.time() if at is None else at
    path=root/'web-channel-control.json';channel=read_record(path).get('chatgpt',{})
    if channel.get('manual_verification_required') is not True:return
    registry_path=root/'shared-gpt-window.json';registry=read_record(registry_path)
    slots=registry.get('slots',[]);targets={s.get('target_id') for s in slots};by_target={p.get('target_id'):p for p in pages}
    # The formula owner uses shared_page_repair._manual_block. Recognize only
    # that exact record for a still-registered target, never a generic user hold.
    base_fields = {'manual_verification_required','reason','target_id','observed'}
    # The producer merges a new DOM login hold over a prior successful recheck.
    # Recognize that exact provenance without accepting unrelated manual holds.
    renewed = (set(channel)==base_fields|{'source','recovered_at','recovery_proof'}
               and channel.get('source')=='resident_dom_authenticated_recheck'
               and channel.get('recovery_proof')==str(root/'account-recovery.json')
               and isinstance(channel.get('recovered_at'),(int,float))
               and isinstance(channel.get('observed'),(int,float)) and channel['observed']>=channel['recovered_at'])
    shared_gate = (formula_window and (set(channel)==base_fields or renewed)
                   and channel['reason']=='共享页检查发现登录或访问验证'
                   and channel['target_id'] in targets and isinstance(channel['observed'],(int,float)))
    if not shared_gate and channel.get('source') not in ('user_report_current_chat','resident_dom_login_ui'):
        return
    def verified(tid):
        p = by_target.get(tid,{})
        return (p.get('account_ready') is True and p.get('account_authenticated') is True
                and p.get('login') is False and not p.get('verification')
                and (not formula_window or (p.get('inspection_complete') is True and p.get('verification') is False))
                and p.get('window_observed') is True and p.get('window_id')==registry.get('window_id')
                and 0<=at-p.get('checked_at',0)<30 and 0<=at-p.get('window_checked_at',0)<30)
    waiting = [tid for tid in targets if tid and not verified(tid)]
    eligible = len(slots)==20 and len(targets)==20 and None not in targets and not waiting
    proof_path=root/'account-recovery.json';previous=read_record(proof_path)
    fingerprint=hashlib.sha256(json.dumps([channel,registry],sort_keys=True).encode()).hexdigest()
    same=(previous.get('fingerprint')==fingerprint and previous.get('owner_pid')==os.getpid()
          and 0<=at-previous.get('checked_at',0)<=35)
    first=previous.get('first_ready_at',at) if same and previous.get('state')=='confirming' else at
    proof={'owner_pid':os.getpid(),'fingerprint':fingerprint,'checked_at':at,
           'state':'confirming' if eligible else 'blocked','first_ready_at':first,
           'waiting_targets':sorted(waiting)}
    atomic_json(proof_path,proof)
    if not eligible or at-first<30 or not owner_enabled(load_config()):return
    after={**channel,'manual_verification_required':False,'source':'resident_dom_authenticated_recheck',
           'reason':'原专窗全部20页已确认有效登录及输入就绪，两次真实检查相隔至少30秒',
           'recovered_at':at,'recovery_proof':str(proof_path)}
    def guard(_):
        if read_record(path).get('chatgpt',{})!=channel or read_record(registry_path)!=registry:
            raise ValueError('账户控制或原固定槽位变化，保留等待')
        if not owner_enabled(load_config()):raise ValueError('用户暂停优先')
    mutate_record(path,{'chatgpt':after},event='owner_account_ready_reverified',validate=guard)
    proof['state']='verified';atomic_json(proof_path,proof)
