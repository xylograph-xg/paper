"""Version-bound scientific review queue, independent of historical review loops."""
import copy
import fcntl
import hashlib
import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path

from core.api import catalog__Catalog as Catalog, catalog__ROOT as ROOT, catalog__now as now
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest, web_card_inputs__damaged_latex as damaged_latex

VERSION = 'source-review-v1'
GROUPS = ('figures', 'equations', 'tables')
TERMINAL = ('passed', 'corrected', 'correction_queued', 'rework_queued', 'needs_user', 'superseded', 'failed', 'trial_reviewed')


def enabled(config):
    from core.api import control__pause_decision as pause_decision
    from browser.api import shared_browser_window__enabled as shared_enabled
    return (config.get('card_review', {}).get('enabled') is True and
            (shared_enabled(config) or pause_decision(config, 'web_cards').allowed) and
            pause_decision(config, 'card_review').allowed)


def install(catalog):
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS card_review_jobs(
          id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, card_sha256 TEXT NOT NULL,
          source_sha256 TEXT NOT NULL, priority REAL, novelty REAL, title TEXT NOT NULL,
          state TEXT NOT NULL, folder TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
          result TEXT NOT NULL DEFAULT '{}', updated TEXT NOT NULL,
          UNIQUE(paper_id,card_sha256))''')
        for operation in ('INSERT','UPDATE','DELETE'):
            db.execute(f'CREATE TRIGGER IF NOT EXISTS revision_card_review_jobs_{operation.lower()} AFTER {operation} ON card_review_jobs '
                       'BEGIN UPDATE catalog_revision SET value=value+1 WHERE id=1; END')
    from browser.api import shared_workflow_queue__install as arrival_install
    arrival_install(catalog)


def rows(catalog):
    install(catalog)
    with catalog.connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM card_review_jobs '
            'ORDER BY priority IS NULL,priority DESC,novelty IS NULL,novelty DESC,id')]


def update(catalog, rid, state, error='', result=None):
    with catalog.connect() as db:
        db.execute('UPDATE card_review_jobs SET state=?,error=?,result=coalesce(?,result),updated=? WHERE id=?',
            (state, error[:1000], json.dumps(result, ensure_ascii=False) if result is not None else None, now(), rid))


def enqueue(catalog, config, *, maintain_cycles=True, stopping=None):
    """Index only existing main GPT cards; literature scores never become review scores."""
    cancellable = stopping is not None
    stopping = stopping or (lambda: False)
    if stopping() or not enabled(config):return 0
    from reading.api import reading_library__install as reading_install, reading_library__refresh_scores as refresh_scores
    install(catalog);reading_install(catalog);refresh_scores(catalog)
    from .review_channel_recovery import recover
    recover(catalog, config)
    if maintain_cycles:
        from .review_cycle import run_once
        run_once(catalog, config, **({'stopping':stopping} if cancellable else {}))
    if stopping():return 0
    with catalog.connect() as db:
        scores = [dict(r) for r in db.execute('SELECT s.*,p.title FROM paper_card_scores s '
            'JOIN papers p ON p.id=s.paper_id WHERE s.card_sha256!=\'\' '
            'ORDER BY overall_quality IS NULL,overall_quality DESC,direction_novelty DESC,p.created DESC,p.id DESC')]
        existing={(r['paper_id'],r['card_sha256']) for r in db.execute('SELECT paper_id,card_sha256 FROM card_review_jobs')}
    candidates=[]
    for score in scores:
        if stopping():break
        if (score['paper_id'],score['card_sha256']) in existing:continue
        try:
            card = json.loads(Path(score['card_path']).read_text())
            if card.get('meta', {}).get('producer') != 'web_card_service':continue
            if card['meta'].get('provider') != 'chatgpt':continue
            rid = hashlib.sha256((score['paper_id']+score['card_sha256']+VERSION).encode()).hexdigest()[:24]
            folder = catalog.path.parent/'card_reviews'/score['paper_id']/rid
            priority=score['overall_quality']
            candidates.append((rid,score['paper_id'],score['card_sha256'],score['source_hash'],
                               priority,score['direction_novelty'],score['title'],str(folder),now()))
        except (OSError, ValueError, KeyError, TypeError):continue
    if not candidates:return 0
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        inserted=db.executemany('INSERT OR IGNORE INTO card_review_jobs '
                       '(id,paper_id,card_sha256,source_sha256,priority,novelty,title,state,folder,updated) '
                       'VALUES(?,?,?,?,?,?,?,\'queued\',?,?)',candidates)
        added=inserted.rowcount
    return added


def current(catalog, job, config):
    paper = catalog.get(job['paper_id'])
    card_path = Path(paper.get('card_path') or '')
    expected = Path(config['studio_library_root'])/paper['id']/'card.json'
    versioned = (card_path.name == 'card.json' and card_path.parent.parent.name == 'publications'
                 and card_path.parent.parent.parent.resolve() == expected.parent.resolve())
    if (card_path.resolve() != expected.resolve() and not versioned) or digest(card_path) != job['card_sha256']:
        raise ValueError('正式卡片版本变化；不核对或覆盖新版本')
    card = json.loads(card_path.read_text());meta = card.get('meta', {})
    if versioned:
        provenance = json.loads(card_path.with_name('web-provenance.json').read_text())
        receipt = provenance.get('attempt', {})
        with catalog.connect() as db:
            published = db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='web_card_generated' AND json_extract(payload,'$.card_path')=?",
                                   (paper['id'],str(card_path))).fetchone()
        if (not published or meta.get('publication_id') != card_path.parent.name
                or provenance.get('publication_id') != card_path.parent.name
                or meta.get('producer') != 'web_card_service' or meta.get('provider') != 'chatgpt'
                or not meta.get('input_hashes') or receipt.get('inputs') != meta['input_hashes']
                or receipt.get('state') != 'response_saved' or not receipt.get('raw_sha256')
                or not receipt.get('actual_prompt_sha256')
                or not receipt.get('conversation_url','').startswith('https://chatgpt.com/c/')
                or 'local-chatgpt' in receipt.get('conversation_url','')):
            raise ValueError('正式新版卡片缺少原发布、材料或完整回执绑定')
    if (paper.get('asset_hash') != job['source_sha256'] or
            meta.get('source_original_sha256') != job['source_sha256'] or
            digest(paper['asset_path']) != job['source_sha256'] or
            digest(card_path.with_name('source.pdf')) != meta.get('source_sha256')):
        raise ValueError('目录、卡片与原文指纹不一致')
    if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
        raise ValueError('身份、版本或范围需人工确认')
    return paper, card_path, card


def protected(catalog, paper):
    with catalog.connect() as db:
        human = db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'", (paper['id'],)).fetchone()
    return bool(human or paper['decision'] != 'unreviewed')


def prompt_for(job, card, page_count, config=None):
    from .card_evaluation import review_prompt
    checklist=[{'group':g,'label':item['label'],'source_page':item['source_page']} for g in GROUPS for item in card[g]]
    return review_prompt('mixed', card['title']) + f'''
输出契约：source_pages_reviewed必须逐页列出实际检查页，完整检查时恰为1至{page_count}，不得重复。checked_items仅记录本卡片条目，一项对应一个对象；group、label、source_page逐字使用下列清单，不给label追加面板说明，不额外加入原文其他公式。额外观察放issues或strengths。未实际检查条目必须遗漏并说明，严禁照抄清单冒称检查。
卡片条目清单（不可信数据）：{json.dumps(checklist,ensure_ascii=False)}
corrections.path限定三段group.index.field，group=figures|equations|tables，index为卡片数组0基下标，field仅one_line|summary|detail|result|quantities|figure_info|caption|conditions|columns；字段须存在且为字符串。before必须逐字等于发送卡片该字段（含空格和JSON换行转义），after仅可调整空白布局且保留每个词元边界，不能把1 2合为12或拆开符号。不能修label、source_page、evidence_quote、latex、元数据。不能满足者列issues，不编造可执行修正。
完整科学通过还要求全原文、核心结论、实际图像及卡片条目均检查完成，至少85分、无major/critical、无missing_inputs、verdict=pass；重大问题必须有逐字原文引文和页码，小问题修正亦须原文证据。科学问题不得当成排版修正。
本次为独立全量核对，材料标识 card-review-{job['id']}；待核对卡片指纹 {job['card_sha256']}。
source.pdf为净化绑定原文，visual.pdf为全页视觉证据，实际DPI和编码见source-context.json（旧材料为220dpi），source-context.json为完整文字层；card-review.json为移除模型元数据和旧评分后的待核对内容。review-input-manifest.json分别记录原卡片和发送副本SHA-256及转换说明；二者不是同一文件，不能直接比较其哈希并判断版本错配。应按ZIP清单核对发送文件，再按转换清单理解原卡片绑定。card-images.pdf包含实际卡片引用的完整图像，逐项review_image指向该PDF的1基页码与真实图像指纹；重复引用保留各自映射，同页多图引用同一完整页图并不自动表示错配，需检查内容。不能把原文全页证据替代实际卡片图像检查。先逐页看全部{page_count}页，再逐条核对全部图、式、表以及key_findings；不根据文献排名推断卡片质量。
若清单列出supplement.pdf、supplement-visual.pdf和supplement-context.json，它们是已核对归属及版本的独立补充材料。逐页读取并另记录supplement_pages_reviewed（实际检查的1基补充PDF页码数组）；未提供或未读完必须记入missing_inputs，不将主文检查冒称补充材料已核验。
在上述JSON中另加入source_identity_checked（布尔）、key_findings_checked（布尔）、source_pages_reviewed（实际检查的1基PDF页码数组）、checked_items（逐条对象，group=figures|equations|tables、label、source_page，不能遗漏）、corrections（小问题修正建议数组）。
issues和corrections每条用source_document=main|supplement明确引文来自主文或补充材料；页码是对应文档的1基页码，旧省略字段仅表示main。issues每条另含source_page、source_quote（连续原文短引文）、path（卡片字段路径）。任何数值/单位、上下标、共轭、公式关系、图/版本错配、核心结论与证据层级错误标major或critical，不得降为minor；附件缺失不能通过或建议重发。
corrections每条为{{"path":"figures.0.summary","before":"原字符串","after":"建议字符串","source_page":1,"source_quote":"连续原文证据"}}。仅排版、空白等不改变字母/数字/数学符号的小问题可直接修正；科学含义改变列issues，不提供执行命令。图式所在页与引文所在页分开，不把跨页引文当捏造。
全文有冲突、歧义或无法判定时verdict=cannot_evaluate并说明，不静默选一种说法。missing_inputs必须包含未读到的材料。严禁声称检查未实际读取的ZIP内容。
''' + '\n以下是制卡与核验共用的字段/证据合同，必须逐项满足：\n' + (
    json.loads((Path(__file__).resolve().parents[1]/'infrastructure/config/card_review_standard.json').read_text())['contract'])


def source_inputs(catalog,job,path,card):
    """Resolve original frozen inputs without restoring a retired active packet."""
    root=catalog.path.parent/'web_cards'/job['paper_id']
    if (root/'packet.json').is_file():
        packet=json.loads((root/'packet.json').read_text())
        if (packet.get('source_original_sha256')==job['source_sha256'] and
                packet.get('input_hashes',{}).get('source.pdf')==card['meta']['source_sha256']):
            return packet,{name:root/name for name in ('source.pdf','source-context.json')},root
    intent_path=Path(job['folder'])/'repair-intent.json';original=None
    if intent_path.is_file():
        old=json.loads(intent_path.read_text()).get('old_job',{})
        if any(old.get(k)!=job.get(k) for k in ('paper_id','card_sha256','source_sha256')):
            raise ValueError('缺失活动材料且没有原核验归属，不猜测归档')
        from .card_review_repair import collected
        original=collected(catalog,old)
        if original['input_hashes'].get('card-original.json')!=job['card_sha256']:
            raise ValueError('原核验与当前卡片输入指纹不一致')
    source_hash=card['meta']['source_sha256']
    if original and original['input_hashes']['source.pdf']!=source_hash:
        raise ValueError('原核验与正式卡片原文指纹不一致')
    candidates=[]
    for filename in (root/'history').glob('source-review-*/packet.json'):
        reset=filename.with_name('reset-intent.json')
        if not reset.is_file():continue
        bound=json.loads(reset.read_text()).get('job',{})
        packet=json.loads(filename.read_text());hashes=packet.get('input_hashes',{})
        context_hash=hashes.get('source-context.json')
        if (bound.get('paper_id')!=job['paper_id'] or bound.get('source_sha256')!=job['source_sha256'] or
                packet.get('paper_id')!=job['paper_id'] or packet.get('source_original_sha256')!=job['source_sha256'] or
                hashes.get('source.pdf')!=source_hash):continue
        if original:
            if context_hash!=original['input_hashes']['source-context.json'] or packet.get('page_count')!=original['page_count']:continue
        else:
            meta=card['meta'];receipts=[]
            if not all(meta.get(k) for k in ('raw_sha256','actual_prompt_sha256','conversation_url')):continue
            from urllib.parse import urlsplit
            url=urlsplit(meta['conversation_url'])
            if (url.scheme!='https' or url.hostname!='chatgpt.com' or not url.path.startswith('/c/') or
                    len(url.path)<=3 or 'local-chatgpt' in url.path):continue
            for ledger in filename.parent.glob('*/attempt.json'):
                attempt=json.loads(ledger.read_text())
                if (attempt.get('provider')!='chatgpt' or attempt.get('state')!='response_saved' or not attempt.get('finished') or
                        attempt.get('raw_sha256')!=meta['raw_sha256'] or
                        attempt.get('actual_prompt_sha256')!=meta['actual_prompt_sha256'] or
                        attempt.get('conversation_url')!=meta['conversation_url'] or attempt.get('inputs')!=hashes):continue
                if (digest(ledger.with_name('response-raw.txt'))!=meta['raw_sha256'] or
                        digest(ledger.with_name('prompt-actual.txt'))!=meta['actual_prompt_sha256']):
                    raise ValueError('正式发布原回答或提示归档变化')
                receipts.append(attempt)
            if len(receipts)!=1:continue
        if digest(filename.with_name('source-context.json'))!=context_hash:raise ValueError('原文归档文字层变化')
        candidates.append((filename,packet,digest(filename)))
    if not candidates or len({row[2] for row in candidates})!=1:
        if original:
            # The completed old review already froze this source/context pair.
            # This is a new render descriptor, never a reconstructed web packet.
            context=Path(old['folder'])/'source-context.json'
            if digest(context)!=original['input_hashes']['source-context.json']:
                raise ValueError('完整原核验文字层变化')
            descriptor={'source_original_sha256':job['source_sha256'],'page_count':original['page_count'],
                'page_manifest':[],'render_from_verified_source':True,
                'input_hashes':{'source.pdf':source_hash,'source-context.json':digest(context)},
                'source_binding':{'kind':'completed_review_source','review_id':old['id'],
                                  'original_review_packet_sha256':digest(Path(old['folder'])/'packet.json')}}
            return descriptor,{'source.pdf':path.with_name('source.pdf'),'source-context.json':context},path.parent
        raise ValueError('没有唯一指纹绑定的原文归档材料')
    filename,packet,_=sorted(candidates,key=lambda row:str(row[0]))[0]
    if len(packet['page_manifest'])!=packet['page_count']:raise ValueError('原文归档页图清单不完整')
    image_root=path.parent
    for index,item in enumerate(packet['page_manifest']):
        if item['source_page']!=index+1 or digest(image_root/'pages'/f'P{index+1:03d}.png')!=item['sha256']:
            raise ValueError('正式发布页图与原文归档不一致')
    return packet,{'source.pdf':path.with_name('source.pdf'),'source-context.json':filename.with_name('source-context.json')},image_root


def _review_media_folder(media_root,paper_id,job_id,folder):
    """A retry folder cannot overwrite another folder's frozen PDF targets."""
    identity=hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()
    return Path(media_root)/paper_id/job_id/identity


def prepare(catalog, job, config, *, locate_quote_pages=True):
    paper, path, card = current(catalog, job, config)
    folder = Path(job['folder']);folder.mkdir(parents=True, exist_ok=True)
    if (folder/'attempt.json').exists():raise ValueError('已有核对回执；不重新准备或提交')
    if (folder/'packet.json').exists():
        frozen=check_packet(folder)
        if (frozen.get('job_id')!=job['id'] or frozen.get('card_sha256')!=job['card_sha256'] or
            frozen.get('source_original_sha256')!=job['source_sha256']):raise ValueError('冻结核验材料归属变化')
        return True # Reuse validated frozen inputs; do not recompress or rewrite.
    media_root=config.get('card_review',{}).get('media_root')
    if media_root:
        from browser.api import web_media_storage__require_volume as require_volume
        require_volume(media_root,config.get('archive_volume'))
        legacy_media=Path(media_root)/paper['id']/job['id']
        media=_review_media_folder(media_root,paper['id'],job['id'],folder);media.mkdir(parents=True,exist_ok=True)
        for name in ('source.pdf','visual.pdf','card-images.pdf'):
            alias=folder/name;destination=media/name
            if alias.is_symlink():
                if alias.resolve()!=destination.resolve():
                    if alias.resolve()!=(legacy_media/name).resolve() or (folder/'packet.json').exists() or (folder/'attempt.json').exists():
                        raise ValueError('核对媒体链接归属变化')
                    proof=folder/'preparation-media-link-relocation.json'
                    prior=json.loads(proof.read_text()) if proof.exists() else {'links':[]}
                    prior['links'].append({'name':name,'before':str(alias.resolve()),'after':str(destination),'at':time.time()})
                    atomic_json(proof,prior)
                    temporary=alias.with_name(alias.name+'.namespace-'+str(time.time_ns()))
                    temporary.symlink_to(destination);temporary.replace(alias)
            elif alias.exists():raise ValueError('核对媒体已有非登记文件，保留待核对')
            else:alias.symlink_to(destination)
    packet,source_files,source_folder=source_inputs(catalog,job,path,card)
    if packet['source_original_sha256'] != job['source_sha256']:raise ValueError('冻结原文不一致')
    for name in ('source.pdf','source-context.json'):
        if digest(source_files[name]) != packet['input_hashes'][name]:raise ValueError('核对输入变化：'+name)
        shutil.copy2(source_files[name], folder/name)
    if digest(folder/'source.pdf') != card['meta']['source_sha256']:raise ValueError('发送原文与正式绑定原文不一致')
    atomic_json(folder/'card-original.json', card)
    # Personal notes, model metadata and old literature scores never enter the reviewer.
    atomic_json(folder/'card-review.json', {k:v for k,v in card.items() if k not in ('meta','paper_evaluation')})
    request = {'packet':packet,'input_folder':str(source_folder),'output_folder':str(folder),
               'visual_path':str((folder/'visual.pdf').resolve()),
               'card_images_path':str((folder/'card-images.pdf').resolve()),
               'image_roots':[str(path.parent.resolve()),str((source_folder/'pages').resolve())]}
    atomic_json(folder/'visual-request.json', request)
    with (folder/'prepare.log').open('a') as log:
        run = subprocess.run([config['web_cards']['pdf_python'],'-m','review.card_review_queue','--visual',str(folder/'visual-request.json')],
            cwd=ROOT, stdout=log, stderr=log, timeout=600)
    if run.returncode:raise ValueError('核对全页视觉准备失败，见prepare.log')
    texts=json.loads((folder/'source-text-verified.json').read_text())
    candidate,fixes=locate_quotes(card,texts) if locate_quote_pages else (card,[])
    if fixes:
        from correction.api import card_correction_queue__enqueue_quotes as enqueue_quotes
        correction=enqueue_quotes(catalog,job,config,texts=texts,fixes=fixes)
        update(catalog,job['id'],'correction_queued','引文定位建议已进入独立修正队列',
               {'action':'quote_location','count':len(fixes),'correction_id':correction['id']})
        return False
    from .card_review_repair import supplement_packet
    supplements=supplement_packet(catalog,job,config,folder)
    atomic_json(folder/'review-input-manifest.json',{'schema_version':1,'original_card_sha256':job['card_sha256'],
        'review_card_sha256':digest(folder/'card-review.json'),'original_source_sha256':job['source_sha256'],
        'transformations':['remove meta and paper_evaluation','replace local image paths with verified card-images.pdf page mappings',
                           'new review visual evidence uses JPEG quality 85; original image hashes identify source images'],
        'supplement':supplements})
    prompt = prompt_for(job, card, packet['page_count'], config);(folder/'prompt.txt').write_text(prompt)
    with (folder/'prepare.log').open('a') as log:
        run=subprocess.run([config['web_cards']['pdf_python'],'-m','review.card_review_queue','--visual-budget',str(folder/'visual-request.json')],
                           cwd=ROOT,stdout=log,stderr=log,timeout=600)
    if run.returncode:raise ValueError('核验完整材料视觉预算检查失败，见prepare.log')
    visual_policy=json.loads((folder/'review-visual-policy.json').read_text())
    names=('source.pdf','visual.pdf','card-images.pdf','card-image-manifest.json','source-context.json','card-review.json','prompt.txt','card-original.json','review-input-manifest.json',*supplements.get('files',[]))
    hashes = {n:digest(folder/n) for n in names}
    from codex_desktop_chat.api import bundles__prepare_upload_bundle as prepare_upload_bundle
    bundle = prepare_upload_bundle([str(folder/n) for n in ('source.pdf','visual.pdf','card-images.pdf','source-context.json','card-review.json','review-input-manifest.json',*supplements.get('files',[]))])
    if bundle['size']>50*1024*1024:raise ValueError('核验ZIP超过当前远程浏览器50MiB传输上限；禁止上传')
    from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
    (folder/'prompt-actual.txt').write_text(prompt+ZIP_INSTRUCTION)
    atomic_json(folder/'packet.json', {'job_id':job['id'],'card_sha256':job['card_sha256'],
        'source_original_sha256':job['source_sha256'],'page_count':packet['page_count'],'review_images_version':1,
        'review_materials_version':2,'supplement':supplements,
        'source_binding':packet.get('source_binding',{'kind':'original_web_packet'}),
        **visual_policy,
        'input_hashes':hashes,'upload_bundle':bundle,'actual_prompt_sha256':digest(folder/'prompt-actual.txt')})
    current(catalog, job, config)
    return True


def locate_quotes(card, texts):
    """Exact unique source quote location; never move the figure/equation image page."""
    from cards.api import web_card_evidence__canonical as canonical, web_card_evidence__literal_match as literal_match
    from read.api import evidence_quotes__unwrap as unwrap
    result=copy.deepcopy(card);fixes=[]
    for group in GROUPS:
        for index,item in enumerate(result[group]):
            quote=unwrap(item.get('evidence_quote',''))
            if len(canonical(quote).replace(' ',''))<15:continue
            page=item.get('evidence_source_page',item['source_page'])
            if literal_match(quote,texts[page-1],case_sensitive=True):continue
            locations=[i+1 for i,t in enumerate(texts) if literal_match(quote,t,case_sensitive=True)]
            if len(locations)!=1:continue
            item['evidence_source_page']=locations[0];item['evidence_status']='verified'
            item['evidence_verification']={'kind':'literal_quote_separate_page','case_sensitive':True,
                'scientific_entailment_verified':False,'reason':'引文逐字唯一匹配；图式页保持原记录'}
            fixes.append({'group':group,'index':index,'label':item['label'],'figure_page':item['source_page'],
                'quote_page':locations[0],'quote_sha256':hashlib.sha256(quote.encode()).hexdigest()})
    return result,fixes


def replacement(catalog, job, card_hash, state, result=None):
    rid=hashlib.sha256((job['paper_id']+card_hash+VERSION).encode()).hexdigest()[:24]
    with catalog.connect() as db:
        existing=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(rid,)).fetchone()
        if existing and existing['state'] in TERMINAL and existing['state'] != state:
            raise ValueError('新版核验同指纹已有终态记录；保留原回执，不静默重排或重发：'+existing['state'])
        db.execute('INSERT OR IGNORE INTO card_review_jobs '
            '(id,paper_id,card_sha256,source_sha256,priority,novelty,title,state,folder,result,updated) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,job['paper_id'],card_hash,job['source_sha256'],job['priority'],job['novelty'],job['title'],
            state,str(Path(job['folder']).parent/rid),json.dumps(result or {}),now()))


def check_packet(folder):
    folder = Path(folder);packet = json.loads((folder/'packet.json').read_text())
    for name, expected in packet['input_hashes'].items():
        if Path(name).name != name or digest(folder/name) != expected:raise ValueError('核对冻结材料变化')
    bundle = packet['upload_bundle']
    if digest(bundle['zip_path']) != bundle['zip_sha256']:raise ValueError('核对ZIP指纹变化')
    if digest(folder/'prompt-actual.txt') != packet['actual_prompt_sha256']:raise ValueError('核对实际提示变化')
    if packet.get('review_images_version')==1:
        for item in json.loads((folder/'card-image-manifest.json').read_text())['images']:
            if digest(item['path'])!=item['sha256']:raise ValueError('正式卡片图像指纹变化')
    return packet


def parse_review(raw, folder, *, optional_external_supplements=False):
    from .web_feedback import parse_feedback
    from cards.api import web_card_evidence__canonical as canonical, web_card_evidence__literal_match as literal_match
    data, assessment = parse_feedback(raw, 'mixed')
    packet = check_packet(folder);card = json.loads((Path(folder)/'card-original.json').read_text())
    # The card generator only receives the main paper.  A cited external
    # supplement that was never supplied is a coverage limitation, not a
    # missing file in this packet.  When a supplement is actually bound, its
    # pages remain mandatory and are never waived.
    if optional_external_supplements and not packet.get('supplement'):
        import re as _re
        external=[]
        for item in list(data.get('missing_inputs') or []):
            if isinstance(item,str) and _re.search(r'补充|Supplement|Supporting|Supplementary|\bSI\b',item,_re.I):
                external.append(item)
        if external:
            data['missing_inputs']=[x for x in (data.get('missing_inputs') or []) if x not in external]
            data['coverage_limitations']=external
    texts = {row['source_page']:row['text'] for row in json.loads((Path(folder)/'source-context.json').read_text())['source_text']}
    expected = [(g, i['label'], i['source_page']) for g in GROUPS for i in card[g]]
    items=data.get('checked_items',[])
    items_valid=isinstance(items,list) and all(isinstance(i,dict) and i.get('group') in GROUPS and
        isinstance(i.get('label'),str) and type(i.get('source_page')) is int for i in items)
    actual = [(i['group'],i['label'],i['source_page']) for i in items] if items_valid else []
    full = (data.get('source_identity_checked') is True and data.get('key_findings_checked') is True and
            type(data.get('source_pages_reviewed')) is list and
            all(type(p) is int for p in data['source_pages_reviewed']) and
            sorted(data['source_pages_reviewed']) == list(range(1,packet['page_count']+1)) and
            items_valid and sorted(actual) == sorted(expected) and len(actual)==len(expected))
    supplement_pages=packet.get('supplement',{}).get('page_count',0)
    if supplement_pages:
        seen=data.get('supplement_pages_reviewed')
        full=full and isinstance(seen,list) and all(type(p) is int for p in seen) and sorted(seen)==list(range(1,supplement_pages+1))
    supplement_texts={}
    if supplement_pages and (Path(folder)/'supplement-context.json').is_file():
        supplement_texts={r['source_page']:r['text'] for r in json.loads((Path(folder)/'supplement-context.json').read_text())['source_text']}
    def grounded(row):
        page=row.get('source_page');quote=row.get('source_quote')
        return (type(page) is int and isinstance(quote,str) and len(canonical(quote).replace(' ',''))>=15 and
                row.get('source_document','main') in ('main','supplement') and
                literal_match(quote,(supplement_texts if row.get('source_document')=='supplement' else texts).get(page,''),case_sensitive=True))
    major = [i for i in data['issues'] if i['severity'] in ('major','critical')]
    blockers=[f'equations.{i}.latex' for i,e in enumerate(card['equations'])
              if not isinstance(e.get('latex'),str) or damaged_latex(e.get('latex',''))]
    if data['missing_inputs'] or data['verdict']=='cannot_evaluate' or not full:
        action = 'needs_user'
    elif blockers:
        # A model score cannot accept a mathematically damaged persisted field.
        action='rework'
    elif major:
        action = 'rework' if all(grounded(i) for i in major) else 'needs_user'
    elif not isinstance(data.get('corrections',[]),list) or any(not isinstance(i,dict) for i in data.get('corrections',[])):
        action='needs_user'
    elif data.get('corrections'):
        action = 'correct' if assessment['weighted_score']>=85 and all(grounded(i) for i in data['corrections']) else 'needs_user'
        if action == 'correct':
            try:formatting_candidate(card, data['corrections'])
            except (ValueError, KeyError, IndexError, TypeError):
                # Grounded scientific edits cannot be applied as local whitespace.
                # A fresh source-only card must receive its own complete review.
                action = 'rework'
    elif assessment['pass']:
        action = 'pass'
    else:action = 'needs_user'
    reason=('核验材料缺失，须补齐后复核' if data['missing_inputs'] else
            '原文或核心结论、图式检查未覆盖全部材料' if not full else
            '原文存在冲突或歧义，保留原卡片待确认' if data['verdict']=='cannot_evaluate' else
            '重大问题缺少可回查原文证据' if major and action=='needs_user' else
            '修正或评分未满足自动处置条件') if action=='needs_user' else ''
    return data, {**assessment,'model_report_pass':assessment['pass'],'pass':action=='pass','blocking_reason':reason,
                  'missing_inputs':data['missing_inputs'],'coverage_limitations':data.get('coverage_limitations',[]),
                  'scores':data['scores'],'verdict':data['verdict'],
                  'issue_counts':{s:sum(i['severity']==s for i in data['issues']) for s in ('critical','major','minor')},
                  'full_source_checked':full and not data['missing_inputs'],
                  'failure_kind':(None if action=='pass' else 'material' if data['missing_inputs'] else 'incomplete' if not full else
                    'ambiguous' if data['verdict']=='cannot_evaluate' else
                    'scientific' if action in ('rework','correct') or (not major and data['verdict']=='revise') else 'unsubstantiated'),
                  'coverage_complete':full,'action':action,'offline_blockers':blockers}


def formatting_candidate(card, corrections):
    """Only whitespace changes; numbers, signs, LaTeX and claims require rework."""
    result = copy.deepcopy(card)
    for patch in corrections:
        path=patch.get('path','');parts=path.split('.')
        if len(parts)!=3 or parts[0] not in GROUPS or parts[2] not in ('one_line','summary','detail','result','quantities','figure_info','caption','conditions','columns'):
            raise ValueError('修正字段超出排版范围')
        if not parts[1].isdigit():raise ValueError('修正条目无效')
        item=result[parts[0]][int(parts[1])];before=patch.get('before');after=patch.get('after')
        if not isinstance(before,str) or not isinstance(after,str) or item.get(parts[2]) != before:
            raise ValueError('修正原字符串不一致')
        if before.split() != after.split():raise ValueError('修正改变科学文字、数值或符号；退回核对')
        item[parts[2]]=after
    return result


def apply_result(catalog, job, config):
    """Persist the report before any publication; never evaluate an uncertain receipt."""
    folder=Path(job['folder']);attempt=json.loads((folder/'attempt.json').read_text())
    if attempt.get('state')!='response_saved' or digest(folder/'response-raw.txt')!=attempt.get('raw_sha256'):
        raise ValueError('核对回答尚未完整保存或指纹变化')
    packet=check_packet(folder)
    if attempt.get('inputs')!=packet['input_hashes'] or attempt.get('actual_prompt_sha256')!=packet['actual_prompt_sha256']:
        raise ValueError('核对回执与材料不一致')
    if not attempt.get('conversation_url','').startswith('https://chatgpt.com/c/') or 'local-chatgpt' in attempt['conversation_url']:
        raise ValueError('核对回答缺少正式会话URL')
    for path in (catalog.path.parent/'card_reviews').glob('*/*/attempt.json'):
        if path.resolve()==(folder/'attempt.json').resolve():continue
        if json.loads(path.read_text()).get('conversation_url')==attempt['conversation_url']:
            raise ValueError('核对会话URL已属于另一份材料')
    data, result = parse_review((folder/'response-raw.txt').read_text(), folder,
        optional_external_supplements=config.get('review_standard',{}).get('external_supplements_optional') is True)
    # Preserve the model's original assessment; policy disposition is separate.
    atomic_json(folder/'assessment-raw.json',result)
    # No manual needs_user state in the no-user policy.  An ungrounded,
    # incomplete or ambiguous review is automatically sent to the source-rework
    # path; it is never converted into a pass or silently discarded.
    if (config.get('review_standard',{}).get('no_user_state') is True
            and result.get('action') == 'needs_user'):
        result = {**result, 'auto_action': 'rework',
                  'blocking_reason': '自动重做：' + (result.get('blocking_reason') or '证据不足'),
                  'action': 'rework'}
    atomic_json(folder/'feedback.json', data);atomic_json(folder/'assessment.json', result)
    update(catalog,job['id'],'applying',result=result)
    paper,path,card=current(catalog, job, config)
    from cards.api import seed_trials__record_review as record_trial_review
    if record_trial_review(catalog,config,job,result):return
    with (path.parent/'web-publish.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        paper,path,card=current(catalog, job, config)
        if not enabled(config):raise ValueError('核对暂停，不发布或重新排队')
        if protected(catalog,paper):
            state='failed' if config.get('review_standard',{}).get('no_user_state') is True else 'needs_user'
            update(catalog,job['id'],state,'人工保护：仅保存核对建议，不覆盖或重做',result);return
        from correction.api import card_correction_queue__partial_rework_allowed as partial_rework_allowed
        if result['action'] in ('rework','correct') or (config.get('card_correction',{}).get('partial_ambiguous_rework') is True and
                partial_rework_allowed(data,result,folder)):
            from correction.api import card_correction_queue__enqueue_review as enqueue_review
            correction=enqueue_review(catalog,job,config,data,result)
            update(catalog,job['id'],'correction_queued','核验报告已保存，建议进入独立修正队列',
                   {**result,'correction_id':correction['id']})
            return
        if result['action']=='failed':
            update(catalog,job['id'],'failed',result.get('blocking_reason') or '自动终止：证据不足，未通过科学核验',result);return
        if result['action']=='needs_user':
            update(catalog,job['id'],'needs_user',result['blocking_reason'],result);return
        candidate=copy.deepcopy(card)
        from .production_contract import evaluate as evaluate_production
        production = evaluate_production(card, path, job, folder, result)
        # Formatting changes need a fresh scientific review; a report applies only to its exact input hash.
        candidate['meta'].update(scientific_verified=result['action']=='pass',
            scientific_validation_status='reviewed' if result['action']=='pass' else 'unreviewed',
            quality_status='source_review_passed' if result['action']=='pass' else 'needs_review',
            production_contract_complete=production['complete'],
            production_contract_status='verified' if production['complete'] else 'blocked',
            production_contract=production,
            source_review={'job_id':job['id'],'card_sha256':job['card_sha256'],'source_sha256':job['source_sha256'],'report':str(folder/'feedback.json'),
                          'report_sha256':digest(folder/'feedback.json'),'weighted_score':result['weighted_score'],
                          'scores':result['scores'],'issue_counts':result['issue_counts'],
                          'full_source_checked':True,'action':result['action']})
        # Content and all history are preserved before the atomic, version-checked publication.
        backup=path.parent/'history'/('source-review-'+job['id']);backup.mkdir(parents=True,exist_ok=True)
        if not (backup/'card.json').exists():shutil.copy2(path,backup/'card.json')
        if digest(backup/'card.json') != job['card_sha256']:raise ValueError('核对备份指纹不一致')
        atomic_json(folder/'card-candidate.json',candidate)
        if digest(path)!=job['card_sha256']:raise ValueError('发布时卡片变化')
        intent={'job':dict(job),'path':str(path),'before':job['card_sha256'],
                'after':digest(folder/'card-candidate.json'),'result':result,'state':'pending'}
        atomic_json(folder/'publication-intent.json',intent)
        finish_publication(catalog,intent,folder,config)


def finish_publication(catalog,intent,folder,config):
    """Replay a frozen metadata publication; conflicting versions are never overwritten."""
    folder=Path(folder);path=Path(intent['path']);job=intent['job'];result=intent['result']
    acceptance_only=intent.get('kind')=='production_acceptance'
    evidence=Path(intent.get('evidence_folder',folder))
    if evidence.resolve()!=folder.resolve():
        if (intent.get('kind')!='production_acceptance' or evidence.resolve()!=Path(job['folder']).resolve()
                or not folder.resolve().is_relative_to((catalog.path.parent/'production-acceptance').resolve())
                or intent.get('scientific_before')!=job['card_sha256']):
            raise ValueError('独立生产验收路径或原科学版本变化')
    candidate=folder/'card-candidate.json'
    if digest(candidate)!=intent['after']:raise ValueError('发布候选指纹变化')
    actual=digest(path)
    if not enabled(config):raise ValueError('核验暂停；不恢复发布')
    from core.api import seed_focus__allowed as seed_allowed
    if not seed_allowed(config,job['paper_id']):raise ValueError('仅手选种子模式：暂停普通文献生产发布')
    paper,verified_path,_=current(catalog,{**job,'card_sha256':actual},config)
    if verified_path.resolve()!=path.resolve() or protected(catalog,paper):raise ValueError('发布恢复路径或人工保护变化')
    check_packet(evidence)
    candidate_card=json.loads(candidate.read_text())
    if digest(evidence/'feedback.json')!=candidate_card['meta']['source_review']['report_sha256']:raise ValueError('发布报告变化')
    production=candidate_card['meta'].get('production_contract')
    if production is not None:
        from .production_contract import evaluate as evaluate_production, same_scientific_pass
        backup=path.parent/'history'/('source-review-'+job['id'])/'card.json'
        original=json.loads(backup.read_text())
        _, assessment=parse_review((evidence/'response-raw.txt').read_text(),evidence,
            optional_external_supplements=config.get('review_standard',{}).get('external_supplements_optional') is True)
        if not (same_scientific_pass(result,assessment) if acceptance_only else assessment==result):
            raise ValueError('生产验收原科学报告变化')
        checked=evaluate_production(original,backup,job,evidence,result,published_path=path)
        if (checked!=production or candidate_card['meta'].get('production_contract_complete') is not checked['complete']
                or {k:v for k,v in original.items() if k!='meta'}!={k:v for k,v in candidate_card.items() if k!='meta'}):
            raise ValueError('生产合同或科学内容变化，保留原发布意图')
    elif candidate_card['meta'].get('production_contract_complete') is True:
        raise ValueError('生产合同缺少独立验收证据')
    with catalog.connect() as publication_db:
        publication_db.execute('BEGIN IMMEDIATE')
        if acceptance_only:
            original_review=publication_db.execute("SELECT result FROM card_review_jobs WHERE id=? AND paper_id=? "
                "AND source_sha256=? AND card_sha256=? AND state='passed'",
                (job['id'],job['paper_id'],job['source_sha256'],job['card_sha256'])).fetchone()
            if not original_review or json.loads(original_review['result'])!=result:
                raise ValueError('独立生产验收原科学通过记录变化')
        fresh=publication_db.execute('SELECT asset_hash,card_path,decision,metadata FROM papers WHERE id=?',(job['paper_id'],)).fetchone()
        human=publication_db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(job['paper_id'],)).fetchone()
        if (not fresh or fresh['asset_hash']!=job['source_sha256'] or not fresh['card_path']
                or Path(fresh['card_path']).resolve()!=path.resolve()
                or fresh['decision']!='unreviewed' or human
                or any(json.loads(fresh['metadata']).get(k) for k in ('identity_review_required','version_review_required','out_of_scope'))
                or not enabled(config) or not seed_allowed(config,job['paper_id'])):
            raise ValueError('发布前原文、正式指针、暂停或人工保护变化')
        actual=digest(path)
        if actual==intent['before']:atomic_json(path,candidate_card)
        elif actual!=intent['after']:raise ValueError('发布恢复遇到其他版本；保留待核对')
    replacement(catalog,job,intent['after'],'passed',{**result,'publication_alias':True})
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state=db.execute('SELECT state FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
        if state is None:raise ValueError('发布原任务不存在')
        if state['state']!='passed':
            db.execute("UPDATE card_review_jobs SET state='passed',result=?,updated=? WHERE id=?",
                       (json.dumps(result),now(),job['id']))
        before=intent.get('scientific_before',intent['before'])
        recorded=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='card_source_review' AND json_extract(payload,'$.before')=? AND json_extract(payload,'$.after')=?",
                            (job['paper_id'],before,intent['after'])).fetchone()
        if not recorded:
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'card_source_review',?,?)",
                       (job['paper_id'],json.dumps({'state':'passed','report':str(evidence/'feedback.json'),
                        'before':before,'after':intent['after']}),now()))
    atomic_json(folder/'publication-intent.json',{**intent,'state':'completed'})


def queue_rework(catalog, job, config, paper, path, result):
    """An explicit, bounded reset after a complete grounded major review."""
    from cards.api import web_card_retry__known_unsent as known_unsent, web_card_retry__finished_response as finished_response
    from cards.api import web_card_queue__install as queue_install
    queue_install(catalog)
    root=catalog.path.parent/'web_cards'/paper['id']
    packet=json.loads((root/'packet.json').read_text())
    for name,h in packet['input_hashes'].items():
        if name=='visual.pdf' and not (root/name).exists():continue # Compacted input is rebuilt from the original source below.
        if digest(root/name)!=h:raise ValueError('制卡原冻结输入变化，不重置')
    records=[]
    for attempt_path in root.glob('*/attempt.json'):
        a=json.loads(attempt_path.read_text())
        if not known_unsent(a):finished_response(attempt_path,a,packet)
        records.append(attempt_path)
    if not records:raise ValueError('没有完整原制卡账本，不重置')
    with catalog.connect() as db:
        old=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(paper['id'],)).fetchone()
        count=db.execute("SELECT count(*) FROM events WHERE paper_id=? AND kind='card_review_rework'",(paper['id'],)).fetchone()[0]
    if old is None or old['state']!='completed':raise ValueError('原制卡仍活动或异常；不重置')
    from .review_cycle import policy
    if not policy(config).get('enabled') and count>=min(2,int(config.get('card_review',{}).get('max_reworks',2))):
        update(catalog,job['id'],'needs_user','科学重做上限已到，保留原卡片和反馈',result);return
    backup=path.parent/'history'/('review-rework-'+job['id']);backup.mkdir(parents=True,exist_ok=True)
    if not (backup/'card.json').exists():shutil.copy2(path,backup/'card.json')
    if digest(backup/'card.json')!=job['card_sha256']:raise ValueError('重做备份不一致')
    if not (backup/'source.pdf').exists():shutil.copy2(path.with_name('source.pdf'),backup/'source.pdf')
    history=root/'history'/('source-review-'+job['id']);history.mkdir(parents=True,exist_ok=True)
    # Freeze intent; a crash at any subsequent stage cannot silently requeue an uncertain attempt.
    atomic_json(history/'reset-intent.json',{'job':dict(old),'review_id':job['id'],'card_sha256':job['card_sha256']})
    for name in ('packet.json','prompt.txt','source-context.json'):
        if not (history/name).exists():shutil.copy2(root/name,history/name)
        if digest(history/name)!=digest(root/name):raise ValueError('原冻结材料归档冲突')
    for a in records:
        destination=history/a.parent.name
        if destination.exists():
            for item in a.parent.rglob('*'):
                target=destination/item.relative_to(a.parent)
                if item.is_dir():target.mkdir(parents=True,exist_ok=True)
                elif item.is_file():
                    if target.exists() and digest(target)!=digest(item):raise ValueError('历史回执冲突')
                    if not target.exists():
                        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
        else:shutil.copytree(a.parent,destination)
        for item in a.parent.rglob('*'):
            if item.is_file() and digest(destination/item.relative_to(a.parent))!=digest(item):raise ValueError('原回执归档失败')
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(paper['id'],)).fetchone()
        if dict(fresh)!=dict(old) or digest(path)!=job['card_sha256'] or protected(catalog,paper):raise ValueError('重置期间状态变化')
        selection=json.loads(old['selection'])
        selection['rework']={'kind':'source_review','review_id':job['id'],'old_card_path':str(path),
            'old_sha256':job['card_sha256'],'backup':str(backup),'human_protected':False,
            'review_report':str(Path(job['folder'])/'feedback.json'),'review_report_sha256':digest(Path(job['folder'])/'feedback.json')}
        if result.get('correction_id'):
            selection['rework'].update(correction_id=result['correction_id'],correction_fifo_at=result['correction_fifo_at'])
        # MaterialProducer recreates a source-only packet; no report/old card enters regeneration.
        # Old answers remain in history; next generation receives only original source inputs.
        db.execute("UPDATE web_card_jobs SET state='review_reset_pending',selection=?,retry_at=?,error=?,updated=? WHERE paper_id=?",
            (json.dumps(selection,ensure_ascii=False),time.time()+300,'独立原文核对发现重大问题，保留旧卡片退回重做',now(),paper['id']))
        db.execute('DELETE FROM web_page_queue WHERE paper_id=?',(paper['id'],)) if db.execute("SELECT 1 FROM sqlite_master WHERE name='web_page_queue'").fetchone() else None
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'card_review_rework',?,?)",
            (paper['id'],json.dumps({'review_id':job['id'],'backup':str(backup),'number':count+1}),now()))
        db.execute("UPDATE card_review_jobs SET state='rework_queued',result=?,updated=? WHERE id=?",(json.dumps(result),now(),job['id']))
    finish_rework_reset(catalog,paper['id'],root,history)


def finish_rework_reset(catalog,pid,root,history):
    """Only a committed reset may remove archived working receipts."""
    root=Path(root);history=Path(history)
    for saved in history.glob('*/attempt.json'):
        active=root/saved.parent.name
        if active.exists():
            for item in active.rglob('*'):
                if item.is_file():
                    archived=saved.parent/item.relative_to(active)
                    if not archived.is_file() or digest(item)!=digest(archived):raise ValueError('重置归档内容变化')
            shutil.rmtree(active)
    packet=root/'packet.json'
    if packet.exists():
        if digest(packet)!=digest(history/'packet.json'):raise ValueError('重置冻结输入变化')
        packet.unlink()
    retry=root/'retry.json'
    if retry.exists():retry.replace(history/'retry.json')
    with catalog.connect() as db:
        db.execute("UPDATE web_card_jobs SET state='queued',updated=? WHERE paper_id=? AND state='review_reset_pending'",(now(),pid))


class ReviewProducer:
    """Parallel local preparation/report validation; browser calls stay in the owner loop."""
    def __init__(self, config):
        self.config=config;self.catalog=Catalog(config['catalog_path']);install(self.catalog)
        if enabled(config):
            with self.catalog.connect() as db:
                pending=[dict(r) for r in db.execute("SELECT * FROM card_review_jobs WHERE state IN ('applying','needs_user')")]
                resets=[dict(r) for r in db.execute("SELECT * FROM web_card_jobs WHERE state='review_reset_pending'")] if db.execute("SELECT 1 FROM sqlite_master WHERE name='web_card_jobs'").fetchone() else []
            for job in pending:
                intent=Path(job['folder'])/'publication-intent.json'
                if intent.exists():
                    try:
                        saved=json.loads(intent.read_text())
                        if saved.get('state')=='completed':continue
                        with (Path(saved['path']).parent/'web-publish.lock').open('a') as lock:
                            fcntl.flock(lock,fcntl.LOCK_EX)
                            finish_publication(self.catalog,saved,intent.parent,config)
                    except Exception as exc:update(self.catalog,job['id'],'needs_user',str(exc))
            for reset in resets:
                try:
                    rid=json.loads(reset['selection'])['rework']['review_id']
                    with self.catalog.connect() as db:original=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(rid,)).fetchone()
                    if original is None:raise ValueError('原重做核验任务缺失')
                    paper,_,_=current(self.catalog,dict(original),config)
                    if protected(self.catalog,paper):raise ValueError('人工保护；不恢复重做清理')
                    root=self.catalog.path.parent/'web_cards'/reset['paper_id']
                    finish_rework_reset(self.catalog,reset['paper_id'],root,root/'history'/('source-review-'+rid))
                except Exception as exc:
                    atomic_json(self.catalog.path.parent/'review-reset-recovery-status.json',
                                {'paper_id':reset['paper_id'],'checked_at':time.time(),'error':str(exc)[:700]})
        self.stop_event=threading.Event();self.thread=threading.Thread(target=self.run,name='card-review-producer',daemon=True)
        self.executor=ThreadPoolExecutor(max_workers=20,thread_name_prefix='card-source-review');self.futures={}
        with self.catalog.connect() as db:
            db.execute("UPDATE card_review_jobs SET state='queued' WHERE state='preparing'")
            db.execute("UPDATE card_review_jobs SET state='needs_user',error='核对提交中断；只收取原会话' WHERE state='submitting'")
            db.execute("UPDATE card_review_jobs SET state='needs_user',error='核对发布中断；保留报告与候选核对' WHERE state='applying'")
    def start(self):self.thread.start()
    def stop(self):self.stop_event.set();self.thread.join();self.executor.shutdown(wait=True)
    def work(self,job):
        try:
            if job['state']=='response_saved':apply_result(self.catalog,job,self.config)
            elif prepare(self.catalog,job,self.config):update(self.catalog,job['id'],'ready')
        except Exception as exc:update(self.catalog,job['id'],'needs_user',str(exc))
    def run(self):
        last_scan=None;scan_future=None;scan_state={}
        def discover():
            try:enqueue(self.catalog,self.config,stopping=self.stop_event.is_set)
            except Exception as exc:
                atomic_json(self.catalog.path.parent/'card-review-discovery-error.json',
                    {'updated':now(),'error':str(exc)[:600]})
            finally:scan_state['finished_at']=time.monotonic()
        while not self.stop_event.is_set():
            try:
                self.futures={k:f for k,f in self.futures.items() if not f.done()}
                if not enabled(self.config):self.stop_event.wait(1);continue
                if scan_future is not None and scan_future.done():
                    last_scan=scan_state['finished_at'];scan_future=None
                # Discovery also revisits historical receipts. Leave the ready
                # and saved-response queues on their separate one-second poll.
                if scan_future is None and (last_scan is None or time.monotonic()-last_scan>=15*60):
                    scan_future=self.executor.submit(discover)
                limit=self.config.get('card_review',{}).get('parallel_jobs',4)
                while len(self.futures)<min(8,limit) and not self.stop_event.is_set():
                    with self.catalog.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        from core.api import seed_focus__active as focus_active
                        seed_scope=" AND paper_id IN (SELECT paper_id FROM manual_seed_roots)" if focus_active(self.config) else ''
                        ahead=db.execute("SELECT count(*) FROM card_review_jobs WHERE state IN ('ready','submitting','submitted')"+seed_scope).fetchone()[0]
                        from browser.api import shared_page_backlog__preparation_head_ids as preparation_head_ids
                        assigned_heads=preparation_head_ids(db,self.catalog,self.config,'review')
                        states="('queued','response_saved')" if ahead<limit or assigned_heads else "('response_saved')"
                        r=db.execute("SELECT j.*,a.queued_at,a.sequence FROM card_review_jobs j LEFT JOIN shared_workflow_arrivals a ON a.lane='review' AND a.job_id=j.id WHERE state IN "+states+seed_scope.replace("paper_id", "j.paper_id",1)+" ORDER BY state='response_saved' DESC,a.queued_at,a.sequence,j.id LIMIT 1").fetchone()
                        if not r:break
                        from core.api import workflow_priority__sort as sort_articles
                        if r is not None and r['state']!='response_saved':
                            candidates=[dict(x) for x in db.execute("SELECT j.*,a.queued_at,a.sequence FROM card_review_jobs j LEFT JOIN shared_workflow_arrivals a ON a.lane='review' AND a.job_id=j.id WHERE state IN "+states+seed_scope.replace("paper_id", "j.paper_id",1)+" ORDER BY a.queued_at,a.sequence,j.id")]
                            if ahead>=limit:
                                candidates=[x for x in candidates if x['id'] in assigned_heads]
                            candidates=sort_articles(db,candidates,self.config)
                            prioritized=[x for x in candidates if x.get('seed_fast_lane') or x['id'] in assigned_heads] or candidates
                            if not prioritized:break
                            r=prioritized[0]
                        job=dict(r);db.execute('UPDATE card_review_jobs SET state=?,updated=? WHERE id=?',('applying' if job['state']=='response_saved' else 'preparing',now(),job['id']))
                    self.futures[job['id']]=self.executor.submit(self.work,job)
            except Exception as exc:
                atomic_json(self.catalog.path.parent/'card-review-error.json',{'updated':now(),'error':str(exc)[:600]})
            self.stop_event.wait(1)


def status(config):
    from core.api import concurrency_control__settings as settings
    parallel=settings(config)['review']
    catalog_path=Path(config['catalog_path'])
    import sqlite3
    counts={};jobs=[];last_finished=None
    if catalog_path.is_file():
        with sqlite3.connect(catalog_path.as_uri()+'?mode=ro',uri=True,timeout=1) as db:
            db.row_factory=sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='card_review_jobs'").fetchone():
                counts=dict(db.execute("SELECT state,count(*) FROM card_review_jobs WHERE json_extract(result,'$.publication_alias') IS NOT 1 GROUP BY state").fetchall())
                jobs=[public_result(dict(r)) for r in db.execute("SELECT id,paper_id,card_sha256,source_sha256,title,state,priority,error,result,updated FROM card_review_jobs WHERE json_extract(result,'$.publication_alias') IS NOT 1 ORDER BY priority IS NULL,priority DESC,novelty DESC,id LIMIT 100")]
                from core.api import workflow_priority__sort as sort_articles, workflow_priority__enabled as score_order
                if score_order(config) or config.get('card_correction',{}).get('priority_passed_first'):
                    jobs=[public_result(r) for r in sort_articles(db,[dict(r) for r in db.execute("SELECT id,paper_id,card_sha256,source_sha256,title,state,priority,novelty,error,result,updated FROM card_review_jobs WHERE json_extract(result,'$.publication_alias') IS NOT 1")],config)[:100]]
                finished=db.execute("SELECT updated FROM card_review_jobs WHERE json_extract(result,'$.publication_alias') IS NOT 1 AND state IN ('passed','corrected','correction_queued','rework_queued','needs_user','failed') ORDER BY updated DESC,id DESC LIMIT 1").fetchone()
                last_finished=finished['updated'] if finished else None
    from core.api import workflow_recovery__decorate as decorate
    return decorate(config,'review',{'enabled':enabled(config),'parallel_jobs':parallel,'counts':counts,'jobs':jobs,
            'last_finished_at':last_finished})


def for_card(config, paper_id, card_hash):
    import sqlite3
    path=Path(config['catalog_path'])
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='card_review_jobs'").fetchone():return None
        row=db.execute('SELECT state,error,priority,result,updated FROM card_review_jobs WHERE paper_id=? AND card_sha256=?',
            (paper_id,card_hash)).fetchone()
        return public_result(dict(row)) if row else None


def public_result(row):
    result=json.loads(row.pop('result'));score=result.get('weighted_score')
    quality=row.get('article_quality',row.get('priority'))
    row['priority']=quality if type(quality) in (int,float) and 0<=quality<=100 else None
    row.update(review_score=score if type(score) in (int,float) and 0<=score<=100 else None,
        review_scores=result.get('scores',{}),review_issues=result.get('issue_counts',{}),
        full_source_checked=result.get('full_source_checked'),review_action=result.get('action'),
        review_reason=result.get('blocking_reason',''),review_missing_inputs=result.get('missing_inputs',[]),
        material_recheck_pending=result.get('material_recheck_pending',False))
    return row


def visual(request_path):
    import pymupdf
    request=json.loads(Path(request_path).read_text());packet=request['packet'];root=Path(request['input_folder']);out=Path(request['output_folder'])
    pdf=pymupdf.open()
    with pymupdf.open(out/'source.pdf') as source:
        if len(source)!=packet['page_count']:raise ValueError('核对原文页数变化')
        texts=[p.get_text() for p in source]
        provided=json.loads((out/'source-context.json').read_text())['source_text']
        if [{'source_page':i+1,'text':t} for i,t in enumerate(texts)]!=provided:raise ValueError('发送文字层与原文实际提取不一致')
        atomic_json(out/'source-text-verified.json',texts)
        for index,item in enumerate(packet['page_manifest']):
            image=root/'pages'/f'P{index+1:03d}.png'
            if item['source_page']!=index+1 or digest(image)!=item['sha256']:raise ValueError('核对冻结页图变化')
            rect=source[index].rect;page=pdf.new_page(width=rect.width,height=rect.height+24)
            page.insert_text((8,16),f'P{index+1:03d} | Source PDF page {index+1}',fontsize=10)
            if packet.get('visual_encoding')=='jpeg':
                page.insert_image(pymupdf.Rect(0,24,rect.width,rect.height+24),
                    stream=pymupdf.Pixmap(str(image)).tobytes('jpeg',jpg_quality=packet['visual_jpeg_quality']))
            else:page.insert_image(pymupdf.Rect(0,24,rect.width,rect.height+24),filename=str(image))
    if packet.get('render_from_verified_source') is True:
        pdf.close()
        render_review_visual(out/'source.pdf',request.get('visual_path',str(out/'visual.pdf')),220)
    else:
        pdf.save(request.get('visual_path',str(out/'visual.pdf')),garbage=4,deflate=True);pdf.close()
    card=json.loads((out/'card-review.json').read_text());images=[];by_path={};evidence=pymupdf.open()
    for group in GROUPS:
        for item in card[group]:
            raw=Path(item.get('image_path') or '')
            candidates=[raw] if raw.is_absolute() else [Path(r)/raw for r in request['image_roots']]
            image=next((p.resolve() for p in candidates if p.is_file() and
                        any(p.resolve().is_relative_to(Path(r).resolve()) for r in request['image_roots'])),None)
            if image is None:raise ValueError('实际卡片图像缺失或归属不明确：'+item['label'])
            key=str(image);sha=digest(image)
            if key not in by_path:
                pix=pymupdf.Pixmap(image);scale=min(1,1000/pix.width,1400/pix.height)
                page=evidence.new_page(width=max(240,pix.width*scale),height=pix.height*scale+24)
                page.insert_text((8,16),f'Actual card image {len(images)+1} | {sha[:16]}',fontsize=10)
                # Preserve transparency rather than silently flattening it.
                encoding='png' if pix.alpha else 'jpeg'
                stream=pix.tobytes(encoding) if pix.alpha else pix.tobytes('jpeg',jpg_quality=85)
                page.insert_image(pymupdf.Rect(0,24,pix.width*scale,pix.height*scale+24),stream=stream)
                images.append({'path':key,'sha256':sha,'page':len(images)+1,
                               'visual_encoding':encoding,'visual_jpeg_quality':None if pix.alpha else 85,
                               'embedded_sha256':hashlib.sha256(stream).hexdigest()});by_path[key]=images[-1]
            item['image_path']='card-images.pdf#page='+str(by_path[key]['page'])
            item['review_image']={'file':'card-images.pdf','page':by_path[key]['page'],'sha256':sha}
    if not images:
        page=evidence.new_page();page.insert_text((8,16),'No figure, equation or table image in this card.')
    evidence.save(request.get('card_images_path',str(out/'card-images.pdf')),garbage=4,deflate=True);evidence.close()
    atomic_json(out/'card-image-manifest.json',{'images':images})
    atomic_json(out/'card-review.json',card)


def render_review_visual(source_path,output_path,dpi,*,supplement=False):
    """Render a new review's bound PDF without modifying frozen source PNGs."""
    import pymupdf
    from cards.api import web_card_inputs__VISUAL_JPEG_QUALITY as VISUAL_JPEG_QUALITY
    manifest=[]
    with pymupdf.open(source_path) as source,pymupdf.open() as output:
        if not len(source) or source.is_encrypted:raise ValueError('核验视觉原文不可读取')
        for index,page in enumerate(source):
            stream=page.get_pixmap(dpi=dpi,alpha=False).tobytes('jpeg',jpg_quality=VISUAL_JPEG_QUALITY)
            target=output.new_page(width=page.rect.width,height=page.rect.height+24)
            label=f'Supplement PDF page {index+1}' if supplement else f'P{index+1:03d} | Source PDF page {index+1}'
            target.insert_text((8,16),label,fontsize=10)
            target.insert_image(pymupdf.Rect(0,24,page.rect.width,page.rect.height+24),stream=stream)
            manifest.append({'source_page':index+1,'image':Path(output_path).name+'#page='+str(index+1),
                             'sha256':hashlib.sha256(stream).hexdigest()})
        output.save(output_path,garbage=4,deflate=True)
    return manifest


def fit_review_visual_budget(request_path):
    from cards.api import web_card_inputs__MATERIAL_BUDGET_BYTES as MATERIAL_BUDGET_BYTES, web_card_inputs__VISUAL_DPI_STEPS as VISUAL_DPI_STEPS, web_card_inputs__VISUAL_JPEG_QUALITY as VISUAL_JPEG_QUALITY, web_card_inputs__VISUAL_POLICY_VERSION as VISUAL_POLICY_VERSION, web_card_inputs__visual_budget as visual_budget
    request=json.loads(Path(request_path).read_text());folder=Path(request['output_folder'])
    if (folder/'packet.json').exists() or (folder/'attempt.json').exists():raise ValueError('冻结或在途核验材料不可调整')
    if digest(folder/'source.pdf')!=request['packet']['input_hashes']['source.pdf']:raise ValueError('核验原文指纹变化')
    names=['source.pdf','visual.pdf','card-images.pdf','source-context.json','card-review.json','review-input-manifest.json']
    supplement=(folder/'supplement.pdf').exists()
    if supplement:names+=['supplement.pdf','supplement-visual.pdf','supplement-context.json']
    context=json.loads((folder/'source-context.json').read_text())
    context['original_page_manifest']=context.get('page_manifest',[])
    for dpi in VISUAL_DPI_STEPS:
        context['page_manifest']=render_review_visual(folder/'source.pdf',(folder/'visual.pdf').resolve(),dpi)
        policy={'visual_dpi':dpi,'visual_policy_version':VISUAL_POLICY_VERSION,
                'visual_encoding':'jpeg','visual_jpeg_quality':VISUAL_JPEG_QUALITY,'material_budget_bytes':MATERIAL_BUDGET_BYTES}
        context.update(policy);atomic_json(folder/'source-context.json',context)
        if supplement:
            render_review_visual(folder/'supplement.pdf',folder/'supplement-visual.pdf',dpi,supplement=True)
            supplemental=json.loads((folder/'supplement-context.json').read_text())
            supplemental.update(policy);atomic_json(folder/'supplement-context.json',supplemental)
        sizes={name:(folder/name).stat().st_size for name in names};size=sum(sizes.values())
        budget=visual_budget(size,dpi)
        if budget['accepted']:
            if digest(folder/'source.pdf')!=request['packet']['input_hashes']['source.pdf']:raise ValueError('核验预算检查期间原文变化')
            atomic_json(folder/'review-visual-policy.json',{**policy,**{k:v for k,v in budget.items() if k!='accepted'},'material_bytes':size,'file_bytes':sizes});return
    failure={**policy,'material_bytes':size,'file_bytes':sizes,
             'error':'核验完整材料超过60MB预算；保留全部页，不上传','automatic_resubmit':False}
    atomic_json(folder/'material-preparation-failure.json',failure)
    raise ValueError(failure['error'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--visual');group.add_argument('--visual-budget');args=p.parse_args()
    if args.visual:visual(args.visual)
    else:fit_review_visual_budget(args.visual_budget)
