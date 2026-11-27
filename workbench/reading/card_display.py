"""Source-PDF display crops only; never mutate scientific cards or frozen inputs."""
import argparse
import fcntl
import json
import re
import sys
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json
from .reading_contract import file_digest

VERSION='pdf-display-v2'


def number(item,kind):
    value=item.get('number') if kind=='figures' else None
    if type(value) is int and value>0:return value
    if isinstance(value,str) and value.isdecimal():return int(value)
    text=str(item.get('label','')).strip()
    pattern=r'(?:Fig(?:ure)?\.?|图)\s*\(?([0-9]+)\)?' if kind=='figures' else r'(?:Eq(?:uation)?\.?|公式|式)?\s*\(?([0-9]+)\)?'
    match=re.fullmatch(pattern,text,re.I)
    return int(match[1]) if match else None


def unique_region(item,kind,parsed):
    page=item.get('source_page');n=number(item,kind)
    if type(page) is not int or n is None:return None
    if kind=='figures':
        found=[f for f in parsed.figures if f.number==n and f.crop_page+1==page
               and f.caption_page==f.crop_page and f.crop_confidence in ('high','medium')
               and f.caption_confidence=='high' and f.graphics_found and not f.sublabel]
        if len(found)!=1:return None
        f=found[0]
        return page-1,f.crop_bbox
    found=[e for e in parsed.equations if e.page+1==page and e.confidence=='high'
           and (e.number==n or n in e.group_numbers)]
    if len(found)!=1:return None
    return page-1,found[0].group_bbox or found[0].bbox


def build(folder):
    import pymupdf
    from read.api import parser__parse_pdf as parse_pdf
    from .media_evidence import render_dual
    folder=Path(folder);out=folder/'display';out.mkdir(exist_ok=True)
    with (out/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        source=folder/'source.pdf';card_path=folder/'card.json'
        hashes={'card_sha256':file_digest(card_path),'source_sha256':file_digest(source),'version':VERSION}
        index=out/'index.json'
        if index.exists():
            prior=json.loads(index.read_text())
            if all(prior.get(k)==v for k,v in hashes.items()) and all((folder/x['asset']).is_file() for x in prior.get('items',{}).values()):return prior
        card=json.loads(card_path.read_text())
        parsed=parse_pdf(source,{'max_figures':sys.maxsize,'max_equation_groups':sys.maxsize,'max_context_chars':1000})
        render_dual(parsed,folder,300,300,lambda *_:None)
        result={**hashes,'dpi':300,'items':{},'visual_validation':'automatic_region_needs_visual_check'}
        with pymupdf.open(source) as doc:
            for kind in ('figures','equations'):
                for i,item in enumerate(card.get(kind,[])):
                    region=unique_region(item,kind,parsed)
                    if region is None:continue
                    page,bbox=region;rect=pymupdf.Rect(bbox)
                    rect=(rect+(-6,-6,6,6)) & doc[page].rect
                    if rect.is_empty or rect.width*rect.height*(300/72)**2>20000000:continue
                    name=f'{kind}-{i}.png';path=out/name;temporary=out/(name+'.tmp.png')
                    pix=doc[page].get_pixmap(matrix=pymupdf.Matrix(300/72,300/72),clip=rect,alpha=False)
                    pix.save(temporary);temporary.replace(path)
                    result['items'][f'{kind}:{i}']={'asset':'display/'+name,'label':item.get('label'),
                        'source_page':page+1,'bbox':list(rect),'width':pix.width,'height':pix.height}
        if file_digest(card_path)!=hashes['card_sha256'] or file_digest(source)!=hashes['source_sha256']:
            raise ValueError('生成展示图时原文或卡片发生变化，保留原展示')
        atomic_json(index,result)
        # Derived display files only, never page evidence or historical cards.
        wanted={Path(x['asset']).name for x in result['items'].values()}
        for path in out.glob('*.png'):
            if path.name not in wanted:path.unlink()
        return result


def maintain(config):
    import subprocess
    from core.api import catalog__Catalog as Catalog, catalog__ROOT as ROOT
    from browser.api import web_media_storage__require_config_storage as require_config_storage
    require_config_storage(config)
    catalog=Catalog(config['catalog_path'])
    with catalog.connect() as db:rows=list(db.execute('SELECT card_path FROM papers WHERE card_path IS NOT NULL'))
    results=[]
    for row in rows:
        folder=Path(row[0]).parent
        if not (folder/'source.pdf').exists():continue
        # Only whole-page web outputs need this display adaptation.
        card=json.loads((folder/'card.json').read_text())
        if not any('/pages/P' in str(x.get('image_path','')) for k in ('figures','equations','tables') for x in card.get(k,[])):continue
        index=folder/'display/index.json'
        if index.exists():
            prior=json.loads(index.read_text())
            if prior.get('version')==VERSION and prior.get('card_sha256')==file_digest(folder/'card.json') and prior.get('source_sha256')==file_digest(folder/'source.pdf'):continue
        try:
            p=subprocess.run([config['web_cards']['pdf_python'],'-m','reading.card_display',str(folder)],cwd=ROOT,capture_output=True,text=True,timeout=90)
            error=p.stderr[-300:] if p.returncode else ''
            results.append({'folder':str(folder),'ok':p.returncode==0,'result':p.stdout.strip()[-200:],'error':error})
        except subprocess.TimeoutExpired:
            error='本地展示解析超时；保留整页放大，不重复同输入'
            results.append({'folder':str(folder),'ok':False,'error':error})
        if error:
            index.parent.mkdir(exist_ok=True)
            atomic_json(index,{'version':VERSION,'card_sha256':file_digest(folder/'card.json'),'source_sha256':file_digest(folder/'source.pdf'),'items':{},'dpi':300,'state':'failed','error':error})
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',nargs='?');parser.add_argument('--maintain',action='store_true');args=parser.parse_args()
    if args.maintain:
        from core.api import catalog__load_config as load_config
        print(json.dumps(maintain(load_config()),ensure_ascii=False))
    else:
        r=build(args.folder);print(json.dumps({'crops':len(r['items']),'dpi':r['dpi']},ensure_ascii=False))
