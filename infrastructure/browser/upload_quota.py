"""Read visible upload-limit reset times and guard retries of unsent requests."""
from __future__ import annotations
import re
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
LIMIT = re.compile(r'(?:文件|附件|上传).{0,24}(?:数量限制|上限|额度|次数限制)|(?:upload|attachment|file).{0,35}(?:limit|quota)|too many files', re.I)
UNUSUAL = re.compile(r'Unusual activity has been detected from your device', re.I)


def reset_time(text, observed=None):
    """Return an explicit page reset in UTC; unknown/ambiguous wording stays unknown."""
    observed = observed or datetime.now(timezone.utc)
    local = observed.astimezone(SHANGHAI)
    if not LIMIT.search(text):
        return None
    # Only read a reset/retry sentence, not unrelated clocks in conversation text.
    match = re.search(r'(?:请于|请在|请等待|重试时间|try again(?:\s+(?:after|at|in))?|retry(?:\s+(?:after|at|in))?|resets?(?:\s+at)?)[^\n]{0,140}', text, re.I)
    if not match:
        # Native upgrade offers use "或在 <time> 后重试" (including repeated
        # 后). Require the retry instruction in the same bounded clause so an
        # unrelated offer/account clock cannot become a reset deadline.
        match = re.search(r'(?:或|可)(?:在|于)\s*[^\n。！？]{0,100}?(?:重试|再上传)', text)
    if not match:
        return None
    line = match.group(0)
    relative = re.search(r'(\d+)\s*(分钟|小时|minutes?|hours?)', line, re.I)
    if relative:
        count = int(relative[1])
        if count <= 0:return None  # Rounded zero does not prove that uploads are available.
        return observed + timedelta(minutes=count * (60 if relative[2].lower().startswith(('小时', 'hour')) else 1))
    clock = re.search(r'(?<!\d)(\d{1,2})[:：](\d{2})\s*(AM|PM)?', line, re.I)
    if not clock:
        return None
    hour, minute = int(clock[1]), int(clock[2])
    if clock[3]:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if clock[3].upper() == 'PM' else 0)
    day = re.search(r'(?:(\d{4})年\s*)?(\d{1,2})月\s*(\d{1,2})日', line)
    english = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:,?\s+(\d{4}))?', line, re.I)
    try:
        result = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day:
            result = result.replace(year=int(day[1] or local.year), month=int(day[2]), day=int(day[3]))
        elif english:
            months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
            result = result.replace(year=int(english[3] or local.year), month=months.index(english[1][:3].lower())+1, day=int(english[2]))
        elif '明天' in line or 'tomorrow' in line.lower():
            result += timedelta(days=1)
        elif result < local:
            # Time-only reset is ambiguous after that clock has passed.
            return None
        return result.astimezone(timezone.utc)
    except ValueError:
        return None


# Install before uploading: capture short visible notices even when a toast expires.
OBSERVER = r'''() => {
  window.__paperUploadNotices = [];
  if (window.__paperUploadObserver) window.__paperUploadObserver.disconnect();
  const capture = () => {
    for (const el of document.querySelectorAll('[role="alert"], [role="dialog"], [data-testid*="toast"], main')) {
      if (!el.getClientRects().length) continue;
      const text = el.innerText || '';
      if (/文件附件数量限制|上传.{0,15}(上限|限制|额度)|upload.{0,20}(limit|quota)|too many files/i.test(text)) {
        const lines = text.split('\n');
        for (let i = 0; i < lines.length; i++) {
          if (/文件附件数量限制|上传.{0,15}(上限|限制|额度)|upload.{0,20}(limit|quota)|too many files/i.test(lines[i])) {
            const notice = lines.slice(Math.max(0,i-1), i+4).join('\n');
            if (!window.__paperUploadNotices.includes(notice)) window.__paperUploadNotices.push(notice);
          }
        }
      }
    }
  };
  window.__paperUploadObserver = new MutationObserver(capture);
  window.__paperUploadObserver.observe(document.body, {childList:true, subtree:true, characterData:true});
  capture();
}'''


LIVE_NOTICE_SCRIPT = r'''() => {
  const visible = el => {
    if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]')) return false;
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    return style.display !== 'none' && !['hidden','collapse'].includes(style.visibility)
      && rect.width > 0 && rect.height > 0;
  };
  const excluded = '[data-message-author-role],[data-conversation-role],[data-talvt-turn-state],'
    + '[data-chatgpt-search-unit-key$=":user"],[data-chatgpt-search-unit-key$=":assistant"],'
    + 'aside,nav,[role="navigation"],[data-testid*="sidebar"],[contenteditable="true"],textarea,pre,code';
  const pattern = /(?:文件|附件|上传).{0,24}(?:数量限制|上限|额度|次数限制)|(?:upload|attachment|file).{0,35}(?:limit|quota)|too many files|Unusual activity has been detected from your device/i;
  const selectors = '[role="alert"],[role="alertdialog"],[role="dialog"],[role="status"],'
    + '[role="menu"],[role="tooltip"],[data-radix-popper-content-wrapper],[data-sonner-toast],'
    + '[data-testid*="toast"],[data-testid*="notification"],[data-testid*="quota"],[data-testid*="limit"]';
  // The old string ring is historical diagnostic data, never a live gate.
  // Keep the anchor only while this exact node and notice remain visible.
  let state = window.__paperQuotaLiveState;
  if (!state || state.version !== 2) state = window.__paperQuotaLiveState = {
    version: 2, epoch: String(Date.now()) + ':' + Math.random().toString(36).slice(2), sequence: 0, active: []};
  const now = Date.now() / 1000, active = [], seen = new Set();
  for (const node of document.querySelectorAll(selectors)) {
    if (!visible(node) || node.closest(excluded) || node.querySelector(excluded)) continue;
    const lines = (node.innerText || '').split('\n');
    for (let i = 0; i < lines.length; i++) {
      if (!pattern.test(lines[i])) continue;
      const text = lines.slice(Math.max(0,i-1),i+4).join('\n').trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      const previous = state.active.find(item => item.node === node && item.text === text);
      active.push({node, text, first: previous ? previous.first : now,
        id: previous ? previous.id : state.epoch + ':' + (++state.sequence)});
    }
  }
  state.active = active;
  return {version: 2, notices: active.map(item => ({text: item.text,
    first_seen_at: item.first, notice_id: item.id}))};
}'''


def visible_notice(page):
    """Current quota UI only; cached strings never block or renew a deadline.

    A still-visible limit with no future reset remains a quota notice. Callers
    must use the existing unknown-time cooldown, not infer availability.
    """
    snapshot = page.evaluate(LIVE_NOTICE_SCRIPT)
    if not isinstance(snapshot, dict) or snapshot.get('version') != 2 or not isinstance(snapshot.get('notices'), list):
        raise ValueError('当前附件额度界面观测不完整')
    observed = datetime.now(timezone.utc)
    for item in snapshot['notices']:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise ValueError('当前附件额度提示证据损坏')
        text = item['text'];anchor = item.get('first_seen_at')
        if (type(anchor) not in (int,float) or not math.isfinite(anchor) or anchor <= 0
                or anchor > observed.timestamp()+1 or not isinstance(item.get('notice_id'),str)):
            raise ValueError('当前附件额度提示时间或身份不可核对')
        if UNUSUAL.search(text):
            return dict(kind='unusual_activity',notice=text[:1200],observed_at=observed.isoformat(),
                first_observed_at=datetime.fromtimestamp(anchor,timezone.utc).isoformat(),
                notice_id=item['notice_id'],evidence_version=2,read_kind='current_visible_ui',
                not_before_utc=None,retry_after_shanghai=None,source='live_browser_notice')
        if not LIMIT.search(text):continue
        if (type(anchor) not in (int,float) or not math.isfinite(anchor) or anchor <= 0
                or anchor > observed.timestamp()+1 or not isinstance(item.get('notice_id'),str)):
            raise ValueError('当前附件额度提示时间或身份不可核对')
        first = datetime.fromtimestamp(anchor,timezone.utc)
        reset = reset_time(text,first)
        if reset is not None and reset <= observed:reset = None
        return dict(notice=text[:1200], observed_at=observed.isoformat(),
                    first_observed_at=first.isoformat(),notice_id=item['notice_id'],evidence_version=2,
                    read_kind='current_visible_ui',
                    not_before_utc=reset.isoformat() if reset else None,
                    retry_after_shanghai=reset.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M') if reset else None,
                    source='live_browser_notice')
    return None


def _reset_timestamp(notice):
    value = notice.get('not_before_utc') if isinstance(notice,dict) else None
    return datetime.fromisoformat(value).timestamp() if value else None


def unsent_page(page):
    """Strict blank-chat proof; draft attachments can remain, sent messages cannot."""
    if page.url.rstrip('/') != 'https://chatgpt.com':
        return False
    if page.locator('[data-message-author-role="user"], [data-message-author-role="assistant"]').count():
        return False
    stop = page.locator('button[data-testid="stop-button"], button[aria-label="停止"], button[aria-label="Stop"]')
    return not any(stop.nth(i).is_visible() for i in range(stop.count()))
