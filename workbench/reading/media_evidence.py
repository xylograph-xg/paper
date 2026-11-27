"""Dual evidence for cards: complete PDF references plus versioned source assets."""
import hashlib
import json
import re
from difflib import SequenceMatcher
from core.api import paths__WorkspacePath as Path


def normalize_caption(text):
    text=re.sub(r'^Fig(?:ure)?\.?\s*\d+\s*[|:.]?','',text,flags=re.I)
    text=re.sub(r'\\[A-Za-z]+\*?', ' ',text)
    return re.sub(r'[^a-z0-9]+',' ',text.lower()).strip()


def match_caption(caption,figures):
    query=normalize_caption(caption)
    if len(query)<60:return None
    scores=[]
    for i,f in enumerate(figures):
        if not f.get('in_main_tree'):continue
        candidate=normalize_caption(f.get('caption',''))
        if len(candidate)<60:continue
        size=min(len(query),len(candidate))
        score=SequenceMatcher(None,query,candidate).ratio()
        scores.append((score,i))
    scores.sort(reverse=True)
    if not scores or scores[0][0]<.9 or (len(scores)>1 and scores[0][0]-scores[1][0]<.08):return None
    return scores[0][1]


from read.api import evidence_preparation__complete_column_captions as complete_column_captions


def render_dual(parsed,target,dpi,equation_dpi,base_renderer):
    """Keep PDF composed crops. Unique equation paths prevent same-page collisions."""
    import pymupdf
    # A parser crop can start halfway through a vector figure. Expand to nearby
    # drawing/image bounds above a bottom caption, stopping at preceding prose
    # or another caption. Keep confidence unchanged: geometry is not visual QA.
    with pymupdf.open(parsed.pdf_path) as doc:
        for figure in parsed.figures:
            if len(figure.crop_bbox)!=4 or len(figure.caption_bbox)!=4:
                continue
            original_bbox=list(figure.crop_bbox)
            bounds=pymupdf.Rect(figure.crop_bbox)
            caption=pymupdf.Rect(figure.caption_bbox)
            if figure.crop_page!=figure.caption_page or bounds.y0>=caption.y0:
                continue
            page=doc[figure.crop_page];floor=40.0
            for block in page.get_text('blocks'):
                if block[6]!=0:continue
                rect=pymupdf.Rect(block[:4]);text=block[4].strip()
                overlap=max(0,min(bounds.x1,rect.x1)-max(bounds.x0,rect.x0))
                if rect.y1<bounds.y0 and overlap>=.5*rect.width and (len(text)>160 or re.match(r'^Fig(?:ure)?\.?\s*\d+',text,re.I)):
                    floor=max(floor,rect.y1+3)
            graphics=[p['rect'] for p in page.get_drawings()]
            for item in page.get_images(full=True):
                graphics.extend(page.get_image_rects(item[0]))
            relevant=[rect for rect in graphics if rect.y0>=floor and rect.y1<=caption.y0+2 and rect.height>2 and rect.width>2 and rect.x1>bounds.x0 and rect.x0<bounds.x1]
            upper=[rect.y0 for rect in relevant]
            if upper and min(upper)<bounds.y0-3:
                bounds.y0=max(floor,min(upper)-20)
                figure.crop_note+='；已按邻近图形边界向上扩展，仍需与整页核对'
            if relevant:
                bounds.x0=max(0,min(bounds.x0,min(r.x0 for r in relevant)-12))
                bounds.x1=min(page.rect.width,max(bounds.x1,max(r.x1 for r in relevant)+16))
                # Keep the neighboring prose column out of a single-column
                # figure once its graphics (including colorbar) are complete.
                graphic_right=max(r.x1 for r in relevant)
                for block in page.get_text('blocks'):
                    if block[6]!=0 or len(block[4].strip())<160:continue
                    rect=pymupdf.Rect(block[:4])
                    if rect.x0>graphic_right+2 and rect.x0<bounds.x1 and rect.y0<bounds.y1 and rect.y1>bounds.y0:
                        bounds.x1=min(bounds.x1,rect.x0-3)
            bounds.y1=min(bounds.y1,caption.y0-6)
            if not bounds.is_empty and list(bounds)!=figure.crop_bbox:
                figure.crop_bbox=list(bounds);figure.crop_confidence="medium"
                parsed.warnings.append(f"{figure.label} 裁切几何经过扩展，需与整页核验；原边界与新边界保留于提取记录")
                parsed.extraction_audit.setdefault("crop_changes",[]).append({"figure":figure.label,"original_bbox":original_bbox,"bbox":list(bounds)})
    base_renderer(parsed,target,dpi,equation_dpi)


def media_manifest(target,card,source_status):
    import pymupdf
    target=Path(target)
    manifest={'schema_version':1,'pdf_sha256':__import__('reading.api',fromlist=['reading_contract']).reading_contract.file_digest(target/"source.pdf"),'source':source_status,'figures':[],'equations':[],'source_figures':[],'source_equations':[],'warnings':[]}
    if source_status.get('state')=='unavailable':manifest['warnings'].append('版本源码未取得，使用PDF证据；'+source_status.get('reason','未知故障'))
    index={}
    if source_status.get('state')=='available':
        index=json.loads((target/source_status['index_path']).read_text())
        manifest['macros']=index['macros'];manifest['warnings']+=index.get('warnings',[])+index.get('limitations',[])
        for i,f in enumerate(index['figures']):
            copy={**f,'id':f'source-figure-{i+1}','originals':[]}
            for graphic in f['graphics']:
                if graphic.get('path'):
                    rel=str(Path(source_status['source_root'])/graphic['path']);p=target/rel
                    item={'path':rel,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'format':p.suffix.lower(),'argument':graphic['argument']}
                    if p.suffix.lower() in {'.png','.jpg'}:item['preview_path']=rel
                    elif p.suffix.lower()=='.jpeg':
                        from PIL import Image
                        preview=target/f'Media_original_{i+1:03d}_{len(copy["originals"])+1}'/'preview.png';preview.parent.mkdir(parents=True,exist_ok=True)
                        try:
                            with Image.open(p) as image:image.save(preview)
                            item['preview_path']=str(preview.relative_to(target))
                        except Exception as exc:item['preview_note']=str(exc)
                    elif p.suffix.lower()=='.pdf':
                        try:
                            with pymupdf.open(p) as original:
                                if len(original):
                                    preview=target/f'Media_original_{i+1:03d}_{len(copy["originals"])+1}'/'preview.png';preview.parent.mkdir(parents=True,exist_ok=True)
                                    original[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(preview);item['preview_path']=str(preview.relative_to(target));item['preview_note']='源码原图 PDF 首页预览；完整原文件另存。'
                        except Exception as exc:item['preview_note']=str(exc)
                    copy['originals'].append(item)
            manifest['source_figures'].append(copy)
        manifest['source_equations']=index['equations']
    pages=set()
    with pymupdf.open(target/'source.pdf') as doc:
        def reference(page):
            if not 1<=page<=len(doc):return None
            path=target/f'Media_page_{page}'/'page.png'
            if page not in pages:
                path.parent.mkdir(parents=True,exist_ok=True);doc[page-1].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(path);pages.add(page)
            return str(path.relative_to(target))
        for f in card.figures:
            i=match_caption(f.caption,index.get('figures',[]))
            manifest['figures'].append({'label':f.label,'number':f.number,'pdf_crop_path':str(Path(f.image_path).relative_to(target)) if f.image_path else None,'pdf_page':f.crop_page,'pdf_page_path':reference(f.crop_page),'crop_confidence':f.crop_confidence,'source_figure_id':f'source-figure-{i+1}' if i is not None else None,'source_match':'caption_unique_high_similarity' if i is not None else 'not_verified'})
        for i,e in enumerate(card.equations):
            manifest['equations'].append({'label':e.label,'pdf_crop_path':str(Path(e.image_path).relative_to(target)) if e.image_path else None,'pdf_page':e.page,'pdf_page_path':reference(e.page),'latex':e.latex,'latex_status':e.latex_status,'semantic_verified':False})
    from read.api import atomic_io__atomic_json as atomic_json
    path=target/'media-evidence.json';atomic_json(path,manifest);return manifest


def validate_latex(text):
    """Syntax checks are never a correctness certificate."""
    if not text or len(text)>20000:return False,'空结果或长度异常'
    if re.search(r'[\x00-\x08\x0b-\x1f]',text.replace('\r\n','\n')):return False,'包含控制字符，可能为JSON转义损坏'
    if re.search(r'\\(?:input|include|write|openout|read|catcode|csname|href|url|includegraphics|def|newcommand)\b',text):return False,'包含非公式或执行命令'
    stack=[]
    for m in re.finditer(r'\\[{}]|[{}]',text):
        ch=m.group()
        if ch=='{':stack.append(ch)
        elif ch=='}':
            if not stack:return False,'花括号不平衡'
            stack.pop()
    if stack:return False,'花括号不平衡'
    env=[]
    for m in re.finditer(r'\\(begin|end)\{([^}]+)\}',text):
        action,name=m.groups()
        if action=='begin':env.append(name)
        elif not env or env.pop()!=name:return False,'公式环境不平衡'
    if env:return False,'公式环境不平衡'
    return True,'通过基本语法检查；上下标、矩阵、分段和符号仍需对照截图核验'


def parse_latex_response(output):
    output=output.strip()
    sentinel=re.fullmatch(r'<<<LATEX>>>\s*(.*?)\s*<<<END>>>',output,re.S)
    if sentinel:
        latex=sentinel.group(1).strip()
    else:
        # Strict compatibility only: never repair arbitrary malformed JSON escapes.
        output=re.sub(r'^```(?:json)?\s*|\s*```$','',output)
        data=json.loads(output)
        latex=data.get('latex','') if isinstance(data,dict) else ''
    if not isinstance(latex,str):raise ValueError('视觉转写返回格式错误')
    valid,note=validate_latex(latex)
    if not valid:raise ValueError('视觉转写未通过检查：'+note)
    return latex,note


def vision_transcriber(client):
    def transcribe(path):
        transcribe.last_raw_response=''
        if not path or not Path(path).is_file():return '','没有公式截图'
        try:
            output=client.chat('仅转写图片中的数学公式为 LaTeX。保留上下标、矩阵、分段、多行与编号；不要解释，不要猜模糊字符，不要输出宏定义或 Markdown。如果看不清或不是公式，中间留空。第一行写 <<<LATEX>>>，最后一行写 <<<END>>>，中间只放 LaTeX 本身。',images=[path],retries=1)
            transcribe.last_raw_response=output
            latex,note=parse_latex_response(output)
            return latex,'现有本地模型视觉转写，未人工核验；'+note
        except Exception as exc:return '',f'视觉转写未完成（截图保留）：{exc}'
    transcribe.last_raw_response=''
    return transcribe
