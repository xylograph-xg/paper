"""Read full user DOM text and expand bound messages through the existing owner."""
import re
import hashlib
from core.api import paths__WorkspacePath as Path

VARIANTS_JS = "el=>[el.textContent||'',el.innerText||'']"


def select_user_text(variants, expected=''):
    if not isinstance(variants, (list, tuple)) or not all(isinstance(x, str) for x in variants):
        raise ValueError('原用户提示DOM文本不可核对')
    dense = lambda text: re.sub(r'\s+', '', text)
    if expected:
        match = next((text for text in variants if dense(expected) in dense(text)), None)
        if match is not None:
            return match
    return next((text for text in variants if text.strip()), '')


def read_user_text(locator, expected=''):
    return select_user_text(locator.evaluate(VARIANTS_JS), expected)


async def read_user_text_async(locator, expected=''):
    return select_user_text(await locator.evaluate(VARIANTS_JS), expected)


EXPAND_JS = r'''({user, expectedPrefix, url}) => {
  const visible = el => !!el && !el.closest('[hidden],[aria-hidden="true"],[inert]') &&
    el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
  const dense = s => s.replace(/\s+/g,'');
  const users = Array.from(document.querySelectorAll(user));
  if (location.href !== url || users.length !== 1) return false;
  const node = users[0];
  if (!dense(node.textContent || '').includes(dense(expectedPrefix))) return false;
  if (Array.from(document.querySelectorAll('button[data-testid="stop-button"],button[aria-label="Stop generating"],button[aria-label="停止生成"]')).some(visible)) return false;
  if (Array.from(document.querySelectorAll('#nocaptcha,[class*="captcha"]')).some(visible)) return false;
  const buttons = Array.from(node.querySelectorAll('button[aria-expanded="false"]')).filter(el =>
    visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' &&
    ['显示更多','Show more'].includes((el.innerText || el.textContent || '').trim()));
  if (buttons.length !== 1) return false;
  buttons[0].click(); return true;
}'''


def expand_original_user(page, record, snapshot, *, target_id):
    """Owner only, under its existing submission lock; expands one bound turn.

    A prefix authorizes only a local display expansion. All collection still
    requires the complete prompt hash/text, unique material and formal URL.
    """
    if (not record or not record.get('actual_prompt_sha256') or record.get('target_id') != target_id
            or record.get('state') not in ('submitted', 'submission_started', 'needs_inspection', 'response_saved')
            or not snapshot.get('inspection_complete') or snapshot.get('streaming') is not False
            or snapshot.get('draft','').strip()
            or any(snapshot.get(k) for k in ('attachments', 'login', 'verification', 'quota', 'errors'))
            or len(snapshot.get('user_texts', [])) != 1):
        return None
    url = page.url
    if (not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url
            or record.get('conversation_url') != url or snapshot.get('url') != url):
        return None
    path = Path(record['_ledger_path']).parent/'prompt-actual.txt'
    try: expected = path.read_text()
    except OSError: return None
    if not expected or hashlib.sha256(expected.encode()).hexdigest() != record.get('actual_prompt_sha256'):
        return None
    text = snapshot['user_texts'][0];dense = lambda s: re.sub(r'\s+', '', s)
    if dense(expected) in dense(text) or dense(expected[:200]) not in dense(text):
        return None
    from .web_card_pool import USER
    clicked = page.evaluate(EXPAND_JS, {'user': USER, 'expectedPrefix': expected[:200], 'url': url})
    return {'state': 'expanded' if clicked else 'no_unique_expand_button',
            'target_id': target_id, 'url': url, 'actual_prompt_sha256': record['actual_prompt_sha256']}
