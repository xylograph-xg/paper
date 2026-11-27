"""Use a verified empty homepage without resetting its hydrated UI."""
import hashlib
import re
from core.api import paths__WorkspacePath as Path
from .shared_page_health import snapshot_page

MODEL_TRIGGER = re.compile(r'^(思考强度|Thinking effort|选择 ChatGPT 模型|Select ChatGPT model)$')


def _archived_reply(snapshot, saved):
    """Prove this page still shows one archived reply byte-for-byte.

    Only that proof permits leaving a page whose visible error notice is not
    part of the reply. No other page state may be abandoned this way.
    """
    if not isinstance(saved, dict) or saved.get('state') != 'ready':
        return False
    url = saved.get('conversation_url')
    raw_hash = saved.get('raw_sha256')
    raw_path = saved.get('raw_path')
    if not url or not raw_hash or not raw_path or snapshot.get('url') != url:
        return False
    users = snapshot.get('user_texts') or []
    answers = snapshot.get('answer_texts') or []
    if len(users) != 1 or len(answers) != 1:
        return False
    if hashlib.sha256(str(answers[0]).encode()).hexdigest() != raw_hash:
        return False
    try:
        return Path(raw_path).is_file() and hashlib.sha256(Path(raw_path).read_bytes()).hexdigest() == raw_hash
    except OSError:
        return False


def _blocked_state(snapshot):
    """Short, non-content evidence of why reuse was refused."""
    import json
    reason = {key: bool(snapshot.get(key)) for key in
              ('attachments','uploading','streaming','login','verification','quota','errors')}
    reason.update(inspection_complete=snapshot.get('inspection_complete'),
                  draft_length=len(str(snapshot.get('draft') or '').strip()))
    if snapshot.get('inspection_error'):
        reason['inspection_error'] = str(snapshot['inspection_error'])[:200]
    return json.dumps(reason, ensure_ascii=False)


def prepare(page, *, saved=None):
    """Called after owned-page reuse guard, under the original submission lock."""
    from web_gpt.core import wait_prompt_box
    from .shared_browser_window import WindowIsolationError
    before = snapshot_page('owned_reuse_preflight', page)
    if (before.get('inspection_complete') is not True or before.get('draft', '').strip()
            or any(before.get(k) for k in ('attachments','uploading','streaming','login','verification','quota'))):
        raise WindowIsolationError('发送前页面证据变化或不完整，保留原页，不导航：' + _blocked_state(before))
    if before.get('errors') and not _archived_reply(before, saved):
        raise WindowIsolationError('发送前页面有未归档错误提示，保留原页，不导航：' + _blocked_state(before))
    clean = (before.get('inspection_complete') is True
             and before.get('url', '').rstrip('/') == 'https://chatgpt.com'
             and before.get('composer_available') is True
             and not before.get('draft', '').strip()
             and not any(before.get(k) for k in ('user_texts','answer_texts','attachments',
                         'streaming','login','verification','quota','errors'))
             )
    page._web_gpt_background = True
    if not clean:page.goto('https://chatgpt.com/', wait_until='domcontentloaded', timeout=60000)
    wait_prompt_box(page, timeout=30000)
    # Composer hydration alone does not prove that settings can be verified.
    trigger = page.get_by_role('button', name=MODEL_TRIGGER)
    trigger.wait_for(state='visible', timeout=30000)
    return {'reused_verified_home':bool(clean)}
