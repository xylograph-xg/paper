"""Close only saved, completed review tabs whose live answer still matches."""
import os
import sys
from core.api import paths__WorkspacePath as Path

from .card_evaluation import ROOT,digest
from .web_feedback import save_json


def close_page(page, saved, answer_selector, stop_selector, message_text):
    stop=page.locator(stop_selector)
    if any(stop.nth(i).is_visible() for i in range(stop.count())):
        return 'generating'
    answers=page.locator(answer_selector)
    if not answers.count() or message_text(answers.last).strip()!=saved.strip():
        return 'answer_changed'
    page.close()
    return 'closed'


def close_saved_review(folder):
    import json
    folder=Path(folder).resolve()
    if (ROOT/'data/shared-gpt-window.json').exists():
        return 'preserved_shared_window_owner'
    if not folder.is_relative_to((ROOT/'data/quality_reviews').resolve()):
        raise ValueError('Review folder outside quality_reviews')
    attempt_path=folder/'web-attempt.json'
    attempt=json.loads(attempt_path.read_text())
    if attempt.get('state')!='feedback_received':return 'not_received'
    if attempt.get('tab_cleanup')=='closed':return 'closed'
    try:
        raw=folder/'feedback-raw.txt';feedback=folder/'feedback.json'
        if not attempt.get('raw_sha256') or not attempt.get('feedback_sha256'):
            return 'legacy_without_fingerprints'
        if digest(raw)!=attempt.get('raw_sha256') or digest(feedback)!=attempt.get('feedback_sha256'):
            return 'saved_evidence_changed'
        if attempt.get('format_followup') and (not attempt.get('format_raw_sha256') or digest(folder/'feedback-format-retry-raw.txt')!=attempt['format_raw_sha256']):return 'saved_evidence_changed'
        url=attempt.get('conversation_url','')
        if not url.startswith('https://chatgpt.com/c/'):return 'no_conversation_url'
        sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[2] / 'chatgpt_playwright')))
        from web_gpt.core import ANSWER,STOP_BUTTON,_message_text
        from web_gpt.submission import submission_lock
        from playwright.sync_api import sync_playwright
        saved_path=folder/('feedback-format-retry-raw.txt' if attempt.get('format_followup') else 'feedback-raw.txt')
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'))
            try:
                with submission_lock():
                    pages=[page for c in browser.contexts for page in c.pages if page.url==url]
                    result=('not_open' if not pages else 'ambiguous' if len(pages)!=1 else
                            close_page(pages[0],saved_path.read_text(),ANSWER,STOP_BUTTON,_message_text))
            finally:browser.close()
        attempt['tab_cleanup']=result
    except Exception as exc:
        attempt['tab_cleanup_error']=f'{type(exc).__name__}: {exc}'
        result='cleanup_failed'
    save_json(attempt_path,attempt)
    return result


if __name__=='__main__':
    for attempt in sorted((ROOT/'data/quality_reviews').glob('**/web-attempt.json')):
        result=close_saved_review(attempt.parent)
        if result not in ('not_received','not_open'):print(attempt.parent.name,result,flush=True)
