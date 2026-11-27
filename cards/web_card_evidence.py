"""Offline, case-sensitive quote checks; never infer scientific entailment."""
import hashlib
import json
from core.api import paths__WorkspacePath as Path
import subprocess
import sys
from core.api import catalog__ROOT as ROOT
from read.api import evidence_literal__canonical as canonical, evidence_literal__literal_match as literal_match
from read.api import evidence_quotes__unwrap as unwrap


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def verify(card,folder,packet,config,*,require_complete_inputs=True):
    """Annotate evidence only; a quote match does not validate a conclusion."""
    folder=Path(folder)
    required=('source.pdf','visual.pdf','source-context.json','prompt.txt')
    missing_inputs=[]
    for name in required:
        expected=packet.get('input_hashes',{}).get(name)
        if name=='visual.pdf' and not (folder/name).is_file() and not require_complete_inputs:
            missing_inputs.append(name);continue
        if not expected or digest(folder/name)!=expected:
            raise ValueError('证据核验前冻结输入指纹变化：'+name)
    context=json.loads((folder/'source-context.json').read_text())
    provided={}
    for item in context['source_text']:
        page=item['source_page']
        if type(page) is not int or page in provided or not isinstance(item['text'],str):
            raise ValueError('冻结文字层页码/内容无效')
        provided[page]=item['text']
    if set(provided)!=set(range(1,packet['page_count']+1)):
        raise ValueError('冻结文字层缺页')
    for index,item in enumerate(packet['page_manifest'],1):
        image=folder/'pages'/f'P{index:03d}.png'
        if item['source_page']!=index or Path(item['image']).resolve()!=image.resolve() or digest(image)!=item['sha256']:
            raise ValueError('冻结视觉证据指纹或页码变化')
    if len(packet['page_manifest'])!=packet['page_count']:raise ValueError('冻结视觉证据缺页')
    error='';actual={}
    try:
        result=subprocess.run([config.get('web_cards',{}).get('pdf_python',sys.executable),
            '-m','cards.web_card_evidence','--extract',str(folder/'source.pdf')],
            cwd=ROOT,capture_output=True,text=True,timeout=60)
        if result.returncode:raise RuntimeError(result.stderr[-500:] or '原文文字提取失败')
        values=json.loads(result.stdout)
        if not isinstance(values,list) or len(values)!=packet['page_count'] or any(not isinstance(v,str) for v in values):
            raise ValueError('原文文字层页数无效')
        actual=dict(enumerate(values,1))
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:error=str(exc)[:500]
    if digest(folder/'source.pdf')!=packet['input_hashes']['source.pdf']:
        raise ValueError('证据提取期间原文变化')
    checks=[]
    for group in ('figures','equations','tables'):
        for item in card[group]:
            page=item['source_page'];quote=unwrap(item['evidence_quote'])
            reason='';matched=False
            if error:reason='原文文字核验不可用：'+error
            elif not actual.get(page,'').strip():reason='原页没有可提取文字；需要视觉核对'
            elif len(canonical(quote).replace(' ',''))<15:reason='引文过短，不能可靠定位'
            else:
                matched=literal_match(quote,actual[page],case_sensitive=True) and literal_match(quote,provided[page],case_sensitive=True)
                if not matched:reason='引文未在声明页原文和实际发送文字层中逐字匹配'
            status='verified' if matched else 'needs_review'
            item['evidence_status']=status
            item['evidence_verification']={'kind':'literal_quote_same_page','case_sensitive':True,
                'scientific_entailment_verified':False,'reason':reason}
            checks.append({'group':group,'label':item['label'],'source_page':page,'state':status,'reason':reason})
    verified=sum(c['state']=='verified' for c in checks)
    complete=bool(checks) and verified==len(checks) and not error
    return {'schema_version':1,'kind':'literal_quote_same_page','case_sensitive':True,
        'state':'verified' if complete else 'unavailable' if error else 'needs_review' if checks else 'no_items',
        'evidence_verified':complete,'scientific_verified':False,'production_contract_complete':False,
        'source_sha256':packet['input_hashes']['source.pdf'],'input_hashes':packet['input_hashes'],
        'input_artifacts_complete':not missing_inputs,'missing_inputs':missing_inputs,
        'verified_count':verified,'needs_review_count':len(checks)-verified,'checks':checks,'error':error}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--extract',required=True);args=parser.parse_args()
    import pymupdf
    with pymupdf.open(args.extract) as document:
        if document.needs_pass or not len(document):raise ValueError('原文加密或为空')
        print(json.dumps([page.get_text() for page in document],ensure_ascii=False))
