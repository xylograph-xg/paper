"""Call the existing read processor in a clean interpreter; never send web messages."""
from __future__ import annotations
from core.api import paths__workspace_root as _workspace_root
import json
import hashlib
import re
import sys
from collections import Counter
from core.api import paths__WorkspacePath as Path

ROOT=_workspace_root()
from read.api import analyzer, parser, exporter
from reading.api import source_media__prepare_source as prepare_source
from reading.api import media_evidence__complete_column_captions as complete_column_captions, media_evidence__media_manifest as media_manifest, media_evidence__render_dual as render_dual, media_evidence__vision_transcriber as vision_transcriber
from reading.api import evidence_repair__repair_sections as repair_sections, evidence_repair__recover_split_figures as recover_split_figures, evidence_repair__recover_numbered_equations as recover_numbered_equations, evidence_repair__include_adjacent_definitions as include_adjacent_definitions, evidence_repair__recover_caption_text as recover_caption_text, evidence_repair__equation_gaps as equation_gaps
from reading.api import prompt_overlays__render_review_prompt as render_review_prompt
from reading.api import quantity_supplement__supplement_quantities as supplement_quantities
from reading.api import reading_contract__READING_CONTRACT_VERSION as READING_CONTRACT_VERSION, reading_contract__file_digest as file_digest
from read.api import generation_state__generation_complete as generation_complete


from read.api import evidence_preparation__filter_equation_candidates as filter_equation_candidates


def reviewed_source_matches(card,source):
    audit=card.meta.get('quality_review',{})
    return bool(audit.get('source_sha256')) and audit['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()


def producer_fingerprint():
    from .reading_contract import producer_fingerprint as fingerprint
    return fingerprint()

def reading_input_hash(source_hash,config):
    payload={'source_sha256':source_hash,'config':{k:v for k,v in config.items() if k!='schedule_config'},
             'contract':READING_CONTRACT_VERSION,'producer_fingerprint':producer_fingerprint()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def attach_media(card,target,status):
    try:
        card.meta['media_evidence']=media_manifest(target,card,status)
        card.warnings.extend(card.meta['media_evidence'].get('warnings',[]))
    except Exception as exc:
        # Optional source assets must not throw away completed reading/model work.
        note=f'双份图式证据未完整生成：{exc}；原 PDF 和已生成卡片保留。'
        card.warnings.append(note)
        card.meta['media_evidence']={'schema_version':1,'source':status,'warnings':[note]}
        (target/'media-evidence.json').write_text(json.dumps(card.meta['media_evidence'],ensure_ascii=False,indent=2))


def reading_config(model,domain_prompt=None,schedule_config=None,model_digest=None):
    config=analyzer.load_config()
    config.update(ollama_base_url=model['base_url'],ollama_model=model['name'])
    if 'think' in model:
        if type(model['think']) is not bool:
            raise ValueError('模型 think 配置必须是布尔值')
        config['ollama_think']=model['think']
    config['schedule_config']=schedule_config or {'catalog_path':str(ROOT/'data/catalog.sqlite3')}
    config['domain_prompt']=domain_prompt
    config['ollama_options']['num_ctx']=model['num_ctx']
    # Detect broadly before filtering; a plot label must not use up the real
    # equation processing budget. The original raw text is retained in parsed.json.
    config['max_equation_groups']=200
    config['max_figures']=200
    from core.api import model_identity__resolve_identity as resolve_identity
    config['model_digest']=model_digest or resolve_identity(model)
    return config


def process(request):
    target=Path(request['out_dir'])
    source=target/'source.pdf'
    old=analyzer.PaperCard.from_dict(json.loads((target/'card.json').read_text())) if (target/'card.json').exists() else None
    # A reviewed card is an independent version; a background retry must not
    # replace it with machine text or overwrite its audit warnings.
    from review.api import review_protection__protection as protection
    review=protection(target)
    if old and not request.get('force') and (old.meta.get('quality_review') or review):
        matches=reviewed_source_matches(old,source)
        if review:matches=not review['source_changed']
        return {'card_path':str(target/'card.json'),'state':'needs_review' if not matches or not generation_complete(old.to_dict()) or (review and review.get('pass') is not True) else 'done','cached':True,'warnings':old.warnings,'source_changed':not matches}
    source_hash=file_digest(source)
    from .science_verifier import runtime_identity,VERSIONS
    if runtime_identity()!=VERSIONS:
        raise RuntimeError('离线科学核验依赖缺失或版本不一致，请先按 requirements-science.txt 安装；本次不调用模型。')
    config=reading_config(request['model'],request.get('domain_prompt'),request.get('schedule_config'))
    from core.api import model_identity__resolve_identity as resolve_identity
    input_hash=reading_input_hash(source_hash,config)
    from .reading_contract import verified_completion
    if old and not request.get('force') and old.meta.get('reading_input_hash')==input_hash and verified_completion(target):
        return {'card_path':str(target/'card.json'),'state':'done','cached':True,'warnings':old.warnings}
    if old and not request.get('force') and old.meta.get('reading_input_hash')==input_hash and old.meta.get('generation_diagnostics',{}).get('automatic_retry_blocked'):
        return {'card_path':str(target/'card.json'),'state':'needs_review','cached':True,'warnings':old.warnings,'automatic_retry_blocked':True}
    previous_guard=old.meta.get('retry_guard',{}) if old else {}
    parsed=parser.parse_pdf(source,config)
    parser.prepare_evidence(parsed,config)
    from read.api import generation_state__expected_coverage as expected_coverage
    expected=expected_coverage(parsed)
    source_status=prepare_source(target)
    # Preserve evidence before slow model calls, even when generation fails.
    from read.api import atomic_io__atomic_json as atomic_json
    atomic_json(target/'parsed.json',parsed.to_dict())
    if request.get('force') or (old and old.meta.get('reading_input_hash')!=input_hash):
        old=None
    checkpoint_path=target/'generation-checkpoint.json'
    if request.get('resume') and checkpoint_path.exists():
        try:
            saved=json.loads(checkpoint_path.read_text())
            if saved.get('source_sha256')==source_hash and saved.get('input_hash')==input_hash:
                old=analyzer.PaperCard.from_dict(saved['card'])
                print('从同源同版本阶段检查点恢复，复用已完成步骤…',file=sys.stderr,flush=True)
        except (OSError,ValueError,KeyError,TypeError):pass
    def checkpoint(card):
        from core.api import services__atomic_json as atomic_json
        from datetime import datetime,timezone
        atomic_json(checkpoint_path,{'source_sha256':source_hash,'input_hash':input_hash,
                    'updated_at':datetime.now(timezone.utc).isoformat(),'card':card.to_dict()},durable=True)
    if old:
        valid_equations={eq.group_label or eq.label for eq in parsed.equations if eq.members}
        old.equations=[eq for eq in old.equations if (getattr(eq,'group_label',None) or eq.label) in valid_equations]
        failed=[f.number for f in old.figures if f.status!='ok' or f.error or f.classification_status not in ('ok','not_applicable')]
    renderer=analyzer.render_figures;prompter=analyzer._render_prompt
    client=analyzer.OllamaClient(config)
    transcriber=vision_transcriber(client)
    import copy
    prompt_scopes=copy.deepcopy(old.meta.get('prompt_input_scope',{})) if old else {}
    from read.api import context_budget__input_limit as input_limit
    def render_prompt(name,values,prompt_dir=analyzer.PROMPT_DIR):
        images=[]
        if name in ('figure','equation'):
            items=parsed.figures if name=='figure' else parsed.equations
            original=next((x for x in items if (x.label if name=='figure' else x.group_label or x.label)==values.get('label')),None)
            if original and original.image_path:images=[original.image_path]
        limit=input_limit(config['ollama_options'],getattr(client,'system',''),images)
        return render_review_prompt(name,values,prompt_dir,prompter,parsed,input_budget=limit,scopes=prompt_scopes)
    card=analyzer.analyze_paper(parsed,config,out_dir=target,client=client,
        progress=lambda msg:print(msg,file=sys.stderr,flush=True),
        base_card=old,only_figures=failed if old else None,checkpoint=checkpoint,
        renderer=lambda paper,out,dpi,eq_dpi:render_dual(paper,out,dpi,eq_dpi,renderer),
        transcriber=transcriber,prompt_renderer=render_prompt)
    print('核验缺失物理量与辅助补充…',file=sys.stderr,flush=True)
    supplement_quantities(card,parsed,client,analyzer._equation_evidence,progress=lambda msg:print(msg,file=sys.stderr,flush=True))
    positions=[]
    for kind,items,originals in [('figure',card.figures,parsed.figures),('equation',card.equations,parsed.equations)]:
        for index,item in enumerate(items):
            original=next((x for x in originals if (x.label if kind=='figure' else x.group_label or x.label)==item.label),None)
            page=item.crop_page if kind=='figure' else item.page
            box=(original.crop_bbox if kind=='figure' else original.group_bbox or original.bbox) if original else None
            positions.append({'kind':kind,'index':index,'page':page,'bbox':list(box) if box else []})
    # Merge canonical figure/equation streams within each page. Pure y sorting
    # interleaves columns and reverses printed equation and figure sequences.
    ordered=[]
    for page in sorted({r['page'] for r in positions}):
        streams={kind:sorted([r for r in positions if r['page']==page and r['kind']==kind],key=lambda r:r['index'])
                 for kind in ('figure','equation')}
        width=parsed.page_sizes[page-1][0] if 1<=page<=len(parsed.page_sizes) else 600
        def geometry(row):
            box=row['bbox']
            return (int(box[0]>=width*.48),box[1]) if box else (2,10**6)
        while any(streams.values()):
            kind=min((k for k in streams if streams[k]),key=lambda k:geometry(streams[k][0]))
            ordered.append(streams[kind].pop(0))
    positions=ordered
    card.meta['reading_order']=positions
    card.meta['reading_contract_version']=READING_CONTRACT_VERSION
    card.meta['reading_source_sha256']=source_hash
    card.meta['reading_input_hash']=input_hash
    card.meta['model_digest']=config['model_digest']
    card.meta['prompt_input_scope']=prompt_scopes
    expected['truncated']=expected['truncated'] or any(r.get('truncated_fields') for r in card.meta.get('input_budget_scope',[])) or any(r.get('truncated') for rows in prompt_scopes.values() for r in rows)
    card.meta['evidence_coverage']=expected
    card.meta['producer_fingerprint']=producer_fingerprint()
    print('关联图式来源证据…',file=sys.stderr,flush=True)
    attach_media(card,target,source_status)
    if any(eq.latex for eq in card.equations):
        card.warnings.append('公式 LaTeX 为视觉转写，语法检查不保证符号正确；展示以 PDF 公式截图为准。')
    for fig in card.figures:
        if fig.crop_confidence!='high':
            card.warnings.append(f'{fig.label} 截图边界未经可靠确认，请对照原文 p.{fig.crop_page} 检查面板完整性。')
    for item in [*card.figures,*card.equations]:
        body=' '.join(str(getattr(item,k,'')) for k in ['summary','detail','result','one_line'])
        if re.search(r'(请(?:上传|提供).{0,30}(?:论文|附件|图片|原文)|等待.{0,15}(?:上传|材料|附件))',body):
            item.status='failed'
            item.error='模型索要已提供的证据，解释不能作为成功结果。'
            card.warnings.append(f'{item.label} 证据使用失败；保留截图等待重试。')
    if any('未识别' in s or '无法总结' in s for s in [card.intro_summary,card.conclusion_summary]):
        card.warnings.append('前言或讨论提取不完整，当前卡片不能视为完整精读。')
    card.warnings=list(dict.fromkeys(card.warnings))
    if resolve_identity(request['model'])!=config['model_digest'] or reading_input_hash(source_hash,config)!=input_hash:
        from core.api import services__atomic_json as atomic_json
        atomic_json(target/'card-uncommitted.json',card.to_dict())
        raise RuntimeError('生成期间模型权重或流程输入指纹发生变化，暂存结果但禁止发布完成标记')
    print('保存卡片并核验完成合同…',file=sys.stderr,flush=True)
    marker=target/'quality-ready.json'
    from .science_verifier import bounded_audit
    card.meta['science_checks']=bounded_audit(card.to_dict(),parsed.to_dict())
    if card.meta['science_checks'].get('blocking'):
        card.warnings.append('离线科学一致性核验发现待核验项或核验不可用；详见 meta.science_checks，禁止自动标为完成。')
    from datetime import datetime,timezone
    from .reading_failures import diagnostics,retry_guard
    card.meta['retry_guard']=retry_guard(card.to_dict(),input_hash,previous_guard)
    card.meta['generation_diagnostics']=diagnostics(card.to_dict())
    if card.meta['retry_guard']['automatic_retry_blocked']:
        card.meta['generation_diagnostics']['automatic_retry_blocked']=True
        card.warnings.append('同输入连续相同故障达到熔断阈值，停止自动重试，等待流程修复或人工核验。')
    # Diagnostics are part of the exact published snapshot.
    exporter.export_card(card,target)
    checkpoint(card)
    failed=not generation_complete(card.to_dict())
    if failed:marker.unlink(missing_ok=True)
    else:
        completion={'completed_at':datetime.now(timezone.utc).isoformat(),
                    'reading_contract_version':READING_CONTRACT_VERSION,'generation_complete':True,
                    'producer_fingerprint':producer_fingerprint(),'reading_input_hash':input_hash,'model_digest':config['model_digest'],
                    'card_sha256':file_digest(target/'card.json'),'source_sha256':source_hash}
        completion['evidence_sha256']={str(Path(item.image_path).resolve().relative_to(target.resolve())):file_digest(item.image_path) for item in [*card.figures,*card.equations]}
        from core.api import services__atomic_json as atomic_json
        atomic_json(marker,completion)
    no_evidence=not card.figures and not card.equations
    return {'card_path':str(target/'card.json'),'state':'needs_review' if no_evidence else (('needs_review' if card.meta['generation_diagnostics']['automatic_retry_blocked'] else 'partial') if failed else 'done'),'warnings':card.warnings}


if __name__=='__main__':
    from core.api import process_runner__watch_parent as watch_parent
    watch_parent()
    try:
        request=json.load(sys.stdin)
        from core.api import model_schedule__require_allowed as require_allowed
        from core.api import catalog__load_config as load_config
        require_allowed(request.get('schedule_config') or load_config())
        print(json.dumps(process(request),ensure_ascii=False))
    except Exception as exc:
        import traceback
        print(traceback.format_exc()[-4000:],file=sys.stderr);sys.exit(1)
