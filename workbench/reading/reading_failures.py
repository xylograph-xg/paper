"""Typed local diagnostics; evidence problems never become scientific approval."""
import re


def failure_class(error):
    text=str(error or '')
    if re.search(r'预算|上下文|长度上限|缺少必需|分隔标题|逐字核对|原文依据|没有返回可解析|索要已提供',text):
        return 'workflow'
    if re.search(r'HTTP (?:429|5\d\d)|timeout|timed out|连接|connection|空内容',text,re.I):return 'transient'
    return 'unknown'


def diagnostics(card):
    figures=card.get('figures',[]);equations=card.get('equations',[])
    stages=card.get('meta',{}).get('generation',{}).get('stages',{})
    errors=[s.get('error') for s in stages.values() if s.get('error')]
    errors += [i.get('error') for i in figures+equations if i.get('error')]
    empty=sum(not e.get('latex') for e in equations)
    visual_incomplete=bool(equations and empty/len(equations)>.25)
    coverage=card.get('meta',{}).get('evidence_coverage',{})
    science=card.get('meta',{}).get('science_checks',{})
    blocked=(bool(science.get('blocking')) or any(failure_class(e)=='workflow' for e in errors) or bool(coverage.get('unresolved') or coverage.get('truncated'))
             or any(i.get('evidence_status')=='needs_review' for i in figures+equations)
             or any(s.get('state')=='missing_source' for s in stages.values()) or visual_incomplete)
    return {'failed_figures':sum(f.get('status')!='ok' for f in figures),'total_figures':len(figures),
            'empty_latex':empty,'total_equations':len(equations),'visual_transcription_incomplete':visual_incomplete,
            'failure_classes':sorted(set(failure_class(e) for e in errors)),
            'science_check_state':science.get('state','not_run'),
            'automatic_retry_blocked':blocked,
            'required_action':'修复输入/流程或核验原文后显式重制；禁止同输入无限重试' if blocked else None,
            'scientific_verified':False}


def retry_guard(card,input_hash,previous=None):
    import hashlib,json
    stages=card.get('meta',{}).get('generation',{}).get('stages',{})
    errors=sorted([str(s.get('error')) for s in stages.values() if s.get('error')]
        +[str(i.get('error')) for i in card.get('figures',[])+card.get('equations',[]) if i.get('error')])
    signature=hashlib.sha256(json.dumps(errors,ensure_ascii=False).encode()).hexdigest() if errors else None
    previous=previous or {}
    repeated=1+previous.get('repetitions',0) if signature and previous.get('input_hash')==input_hash and previous.get('signature')==signature else int(bool(signature))
    classes={failure_class(e) for e in errors}
    blocked=bool(signature and repeated>=2 and classes!={'transient'})
    return {'input_hash':input_hash,'signature':signature,'repetitions':repeated,'automatic_retry_blocked':blocked}
