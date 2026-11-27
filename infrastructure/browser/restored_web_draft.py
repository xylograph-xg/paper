"""Clear only an exact archived, explicitly unsent pipeline draft on a new slot."""
import hashlib
import json
import re
import time
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json


def evidence(root,draft):
    match=re.search(r'材料标识 web-card-([0-9a-f-]{36})-',draft)
    if not match:
        review=re.search(r'材料标识 card-review-([0-9a-f]{24})',draft)
        if not review:return None
        dense=lambda text:re.sub(r'\s+','',text)
        for folder in (Path(root)/'card_reviews').glob('*/'+review[1]):
            prompt=folder/'prompt-actual.txt'
            if not prompt.is_file():continue
            raw=prompt.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            if dense(raw.decode())!=dense(draft):continue
            for attempt in folder.rglob('attempt.json'):
                saved=json.loads(attempt.read_text())
                if (saved.get('review_id')==review[1] and saved.get('state')=='not_sent'
                    and saved.get('send_click_started') is False and saved.get('actual_prompt_sha256')==sha):
                    return {'attempt_path':str(attempt.resolve()),'prompt_path':str(prompt.resolve()),'prompt_sha256':sha}
        return None
    folder=Path(root)/'web_cards'/match[1]
    dense=lambda text:re.sub(r'\s+','',text)
    for prompt in folder.rglob('prompt-actual.txt'):
        attempt=prompt.parent/'attempt.json'
        if not attempt.is_file():continue
        raw=prompt.read_bytes();saved=json.loads(attempt.read_text())
        raw_path=prompt.parent/'response-raw.txt'
        completed=(saved.get('state')=='response_saved' and raw_path.is_file() and raw_path.stat().st_size>0
            and saved.get('raw_sha256')==hashlib.sha256(raw_path.read_bytes()).hexdigest()
            and str(saved.get('conversation_url','')).startswith('https://chatgpt.com/c/'))
        unsent=saved.get('state')=='not_sent' and saved.get('send_click_started') is False
        if ((unsent or completed)
            and saved.get('actual_prompt_sha256')==hashlib.sha256(raw).hexdigest()
            and dense(raw.decode())==dense(draft)):
            return {'attempt_path':str(attempt.resolve()),'prompt_path':str(prompt.resolve()),
                    'prompt_sha256':hashlib.sha256(raw).hexdigest()}
    return None


def verified_blank(entry):
    stamp=entry.get('blank_history_verified_at')
    hashes=entry.get('blank_history_ledger_hashes')
    if type(stamp) not in (int,float) or not 0 <= time.time()-stamp <= 60 or not isinstance(hashes,dict) or not hashes:
        return False
    try:
        return all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha for path,sha in hashes.items())
    except OSError:
        return False


def clear(root,page,entry,box,draft,users,answers,streaming):
    # Preserve the exact live composer before any eligibility/identity check.
    # A diagnostic snapshot grants no permission to clear or navigate.
    sha=hashlib.sha256(draft.encode()).hexdigest()
    diagnostic=Path(root)/'blocked-web-drafts'/sha
    diagnostic.mkdir(parents=True,exist_ok=True)
    if not (diagnostic/'draft.txt').exists():(diagnostic/'draft.txt').write_text(draft)
    atomic_json(diagnostic/'observation.json',{'sha256':sha,'url':page.url,
        'entry':dict(entry),'users':users,'answers':answers,'streaming':streaming,'checked_at':time.time()})
    if (entry.get('state')!='ready_blank' or (entry.get('never_submitted') is not True and entry.get('origin')!='verified_unsent_retry' and not verified_blank(entry))
        or not entry.get('startup_request_id') or users or answers or streaming
        or page.url.rstrip('/')!='https://chatgpt.com'):return False
    proof=evidence(root,draft)
    if not proof:return False
    # Attachments must be absent; their ownership cannot be inferred from text.
    if page.locator('[data-testid="attachment-preview"], [data-testid*="file-thumbnail"], [data-testid*="file-upload"]').count():return False
    archive=Path(root)/'restored-draft-cleanups'/entry['startup_request_id']/str(time.time_ns())
    archive.mkdir(parents=True);(archive/'draft.txt').write_text(draft)
    atomic_json(archive/'evidence.json',{**proof,'url':page.url,'startup_request_id':entry['startup_request_id'],'state':'clear_intent','created':time.time()})
    from .web_editor_input import replace
    replace(box,'')
    from web_gpt.core import _box_text
    if _box_text(box).strip():
        atomic_json(archive/'evidence.json',{**proof,'state':'clear_not_applied','editor':box.evaluate("el=>({keys:Object.keys(el),parentKeys:el.parentElement&&Object.keys(el.parentElement),tag:el.tagName,editable:el.contentEditable,view:!!el.pmViewDesc,viewType:el.pmViewDesc&&Object.keys(el.pmViewDesc),modelText:el.pmViewDesc&&el.pmViewDesc.view&&el.pmViewDesc.view.state.doc.textContent.length,textLength:(el.textContent||'').length})")})
        return False
    atomic_json(archive/'evidence.json',{**proof,'state':'cleared','checked':time.time()})
    entry['restored_unsent_draft_cleared']=str(archive)
    return True
