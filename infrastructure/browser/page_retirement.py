"""Close only finished owned slots when a user lowers desired concurrency."""
import hashlib,time
from core.api import paths__WorkspacePath as Path
from core.api import control__read_record as read_record
from core.api import services__atomic_json as atomic_json

def may_retire(state,ledger_state,url,users,answers,draft='',streaming=False,live_hash='',saved_hash=''):
    if state=='ready_blank':
        return ledger_state in (None,'not_sent','deferred') and url.rstrip('/')=='https://chatgpt.com' and users==0 and answers==0 and not draft.strip() and not streaming
    return state=='ready' and ledger_state=='response_saved' and users==1 and answers>0 and not draft.strip() and not streaming and bool(saved_hash) and saved_hash==live_hash

def retire_excess(root,pages,entries,latest,target):
    from web_gpt.core import ANSWER,STOP_BUTTON,_message_text,wait_prompt_box,_box_text
    from web_gpt.submission import submission_lock
    from .web_card_pool import USER
    closed=[];excess=max(0,sum(t in entries for t in pages)-target)
    if not excess or not any(entries.get(t,{}).get("state") in ("ready","ready_blank") for t in pages):return closed
    with submission_lock(timeout=5):
        for tid,page in list(pages.items()):
            if len(closed)>=excess:break
            entry=entries.get(tid,{})
            if entry.get('state') not in ('ready','ready_blank'):continue
            a=latest.get(tid,{})
            ledger_path=Path(a['_ledger_path']) if a.get('_ledger_path') else None
            if ledger_path:
                a=read_record(ledger_path)
                if a.get('target_id')!=tid:continue
            try:
                users=page.locator(USER).count();answers=page.locator(ANSWER);stops=page.locator(STOP_BUTTON)
                streaming=any(stops.nth(i).is_visible() for i in range(stops.count()))
                draft=_box_text(wait_prompt_box(page,timeout=3000))
                live_hash=hashlib.sha256(_message_text(answers.last).encode()).hexdigest() if answers.count() else ''
                saved_hash=a.get('raw_sha256','')
                if entry.get('state')=='ready':
                    if not ledger_path or page.url!=a.get('conversation_url') or sum(p.url==page.url for p in pages.values())!=1:continue
                    raw=ledger_path.parent/'response-raw.txt'
                    if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest()!=saved_hash:continue
                if not may_retire(entry.get('state'),a.get('state'),page.url,users,answers.count(),draft,streaming,live_hash,saved_hash):continue
                page.close();pages.pop(tid);entry.update(state='retired',retired_at=time.time(),retired_reason='user_concurrency_reduction')
                if ledger_path:
                    a['tab_cleanup']='closed_concurrency_reduction';atomic_json(ledger_path,a)
                closed.append(tid)
            except Exception:continue # Preserve any uncertain, changed or generating page.
    return closed
