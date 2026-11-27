"""Version-bound arXiv source evidence. Never execute submitted TeX or macros."""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import re
import tarfile
import time
from pathlib import PurePosixPath
from core.api import paths__WorkspacePath as Path

MAX_FILES=2000
MAX_EXPANDED=100*1024*1024
MAX_DOWNLOAD=20*1024*1024
VERSION_RE=re.compile(r'arXiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})v\d+)\b',re.I)

def pdf_version(pdf):
    import pymupdf
    with pymupdf.open(pdf) as doc:
        matches=set(VERSION_RE.findall(doc[0].get_text()))
    return next(iter(matches)) if len(matches)==1 else None


def unpack_source(data,destination):
    """Reject traversal, links, devices and oversized archives before any writes."""
    root=Path(destination);files=[]
    try:
        archive=tarfile.open(fileobj=io.BytesIO(data),mode='r:*')
    except tarfile.ReadError:
        raw=gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_EXPANDED+1) if data.startswith(b'\x1f\x8b') else data
        if len(raw)>MAX_EXPANDED or b'\\documentclass' not in raw[:100000]:
            raise ValueError('源码不是可识别的 TeX 或 tar 压缩包')
        files=[('main.tex',raw)]
    else:
        with archive:
            total=0
            names=set()
            for count,m in enumerate(archive):
                if count>=MAX_FILES:raise ValueError('源码文件数超过限制')
                name=PurePosixPath(m.name)
                if str(name) in names:raise ValueError('源码包含重复路径')
                names.add(str(name))
                if name.is_absolute() or '..' in name.parts or '\\' in m.name:
                    raise ValueError('源码包含不安全路径')
                if m.isdir():continue
                if not m.isfile():raise ValueError('源码包含链接或特殊文件')
                total+=m.size
                if total>MAX_EXPANDED:raise ValueError('解压体积超过限制')
                files.append((str(name),archive.extractfile(m).read()))
    root.mkdir(parents=True,exist_ok=True)
    for name,raw in files:
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('路径逃逸')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return [name for name,_ in files]


def uncomment(text):
    return re.sub(r'(?<!\\)%[^\n]*','',text)


def braced(text,start):
    """Return a balanced argument plus end offset; escaped braces are literals."""
    while start<len(text) and text[start].isspace():start+=1
    if start>=len(text) or text[start]!='{':return None,start
    depth=1;i=start+1
    while i<len(text):
        if text[i]=='\\':i+=2;continue
        if text[i]=='{':depth+=1
        if text[i]=='}':depth-=1
        if not depth:return text[start+1:i],i+1
        i+=1
    return None,start


def command_args(text,command):
    result=[]
    for m in re.finditer(r'\\'+re.escape(command)+r'(?![A-Za-z@])\*?',text):
        pos=m.end()
        while pos<len(text) and text[pos].isspace():pos+=1
        if pos<len(text) and text[pos]=='[':
            end=text.find(']',pos+1)
            if end<0:continue
            pos=end+1
        arg,end=braced(text,pos)
        if arg is not None:result.append((arg,m.start(),end))
    return result


def environments(text,names):
    token=re.compile(r'\\(begin|end)\s*\{('+ '|'.join(re.escape(n) for n in names)+r')\}')
    stacks={n:[] for n in names};out=[]
    for m in token.finditer(text):
        action,name=m.groups()
        if action=='begin':stacks[name].append((m.start(),m.end()))
        elif stacks[name]:
            start,body_start=stacks[name].pop();out.append((name,text[body_start:m.start()],start,m.end()))
    return sorted(out,key=lambda x:x[2])


def macro_definitions(text):
    output=[]
    for m in re.finditer(r'\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator)\*?\s*',text):
        pos=m.end();name,end=braced(text,pos)
        if name is None:
            n=re.match(r'\\[A-Za-z@]+',text[pos:])
            if not n:continue
            end=pos+n.end()
        pos=end
        while True:
            while pos<len(text) and text[pos].isspace():pos+=1
            if pos<len(text) and text[pos]=='[':
                close=text.find(']',pos)
                if close<0:break
                pos=close+1
            else:break
        body,end=braced(text,pos)
        if body is not None:output.append(text[m.start():end])
    for m in re.finditer(r'\\(?:gdef|edef|def)\s*\\[A-Za-z@]+[^{}\n]*',text):
        body,end=braced(text,m.end())
        if body is not None:output.append(text[m.start():end])
    return list(dict.fromkeys(output))


def index_source(root):
    root=Path(root).resolve();texts={}
    for path in sorted(root.rglob('*.tex')):
        if path.stat().st_size>2*1024*1024:continue
        texts[path.relative_to(root).as_posix()]=uncomment(path.read_text(errors='replace'))
    figures=[];equations=[];warnings=[]
    # Build inclusion order without expanding arbitrary user-defined commands.
    mains=[name for name,t in texts.items() if '\\documentclass' in t and '\\begin{document}' in t]
    ordered=[];seen=set()
    def visit(name):
        if name in seen or name not in texts:return
        seen.add(name);ordered.append(name)
        for command in ['input','include']:
            for arg,_,_ in command_args(texts[name],command):
                base=Path(name).parent/arg
                for candidate in [base.as_posix(),base.with_suffix('.tex').as_posix()]:
                    if candidate in texts:visit(candidate);break
                else:warnings.append(f'{name}: 未解析的 {command} {arg}')
    for name in mains:visit(name)
    reachable=set(ordered)
    for name in texts:visit(name)
    for name in ordered:
        t=texts[name];base=root/Path(name).parent
        dirs=[base,root]
        for paths,_,_ in command_args(t,'graphicspath'):
            for d in re.findall(r'\{([^{}]+)\}',paths):dirs.extend([base/d,root/d])
        for env,body,start,end in environments(t,['figure','figure*']):
            assets=[]
            for arg,_,_ in command_args(body,'includegraphics'):
                found=None
                if not re.search(r'[\\#]',arg):
                    for folder in dirs:
                        for ext in ['', '.pdf','.png','.jpg','.jpeg','.eps','.ps']:
                            path=(folder/(arg+ext)).resolve()
                            if path.is_relative_to(root.resolve()) and path.is_file():found=path;break
                        if found:break
                assets.append({'argument':arg,'path':found.relative_to(root).as_posix() if found else None,'status':'available' if found else 'unresolved'})
            figures.append({'file':name,'line':t[:start].count('\n')+1,'environment':env,'caption':'\n'.join(a for a,_,_ in command_args(body,'caption')),'labels':[a for a,_,_ in command_args(body,'label')],'graphics':assets,'in_main_tree':name in reachable,'source_tex':t[start:end]})
        names=['equation','equation*','align','align*','gather','gather*','multline','multline*','displaymath','eqnarray','eqnarray*']
        items=environments(t,names)
        items += [('displaymath',m.group(1),m.start(),m.end()) for m in re.finditer(r'\\\[([\s\S]*?)\\\]',t)]
        for env,body,start,end in sorted(items,key=lambda x:x[2]):
            equations.append({'file':name,'line':t[:start].count('\n')+1,'environment':env,'latex':body.strip(),'labels':[a for a,_,_ in command_args(body,'label')],'in_main_tree':name in reachable,'validation':'source_exact_not_independently_rendered'})
    return {'tex_files':list(texts),'main_files':mains,'figures':figures,'equations':equations,'macros':list(dict.fromkeys(m for t in [*texts.values(),*(p.read_text(errors='replace') for p in root.rglob('*') if p.is_file() and p.suffix in {'.sty','.cls'} and p.stat().st_size<2*1024*1024)] for m in macro_definitions(t))),'warnings':warnings,'limitations':['静态解析不执行 TeX；宏生成的图、公式、条件分支可能未完整展开。','源码与截图只按可靠证据匹配，不用出现顺序猜编号。']}


def prepare_source(target,download_fn=None):
    """Fetch only the exact version printed in the active PDF; cached failures back off."""
    target=Path(target);version=pdf_version(target/'source.pdf');status_file=target/'source-status.json'
    if not version:return {'state':'no_verified_arxiv_version','reason':'PDF 未发现唯一的带版本 arXiv 标记；不与其他版本源码混用。'}
    try:old=json.loads(status_file.read_text()) if status_file.exists() else {}
    except (ValueError,OSError):old={}
    root=target/'arxiv_source'/version.replace('/','_')
    from .reading_contract import file_digest
    implementation=file_digest(Path(__file__))
    if old.get('version')==version:
        if old.get('state')=='needs_rebuild':return old
        if old.get('state')=='available':
            try:
                index=json.loads((root/'index.json').read_text())
                if not isinstance(index,dict) or file_digest(root/'source.archive')!=old['archive_sha256']:
                    raise ValueError('源码缓存归档指纹变化')
                manifest=old['file_sha256']
                actual={p.relative_to(root/'files').as_posix():file_digest(p) for p in (root/'files').rglob('*') if p.is_file() and not p.is_symlink()}
                if actual!=manifest or file_digest(root/'index.json')!=old['index_sha256']:
                    raise ValueError('源码缓存文件树/索引变化')
                return old
            except (OSError,ValueError,KeyError,TypeError) as exc:
                from core.api import services__atomic_json as atomic_json
                old.update(state='needs_rebuild',reason=str(exc),checked_at=time.time())
                atomic_json(status_file,old)
                return old # Preserve damaged evidence; rebuilding is explicit.
        if old.get('implementation_sha256')==implementation and old.get('retry_after',0)>time.time() and old.get('url')=='https://arxiv.org/src/'+version:return old
    status={'implementation_sha256':implementation,'version':version,'url':'https://arxiv.org/src/'+version,'state':'pending','checked_at':time.time()}
    try:
        if download_fn is None:
            from core.api import services__download as download_fn
        root.mkdir(parents=True,exist_ok=True)
        temp=root/'download.part'
        download_fn(status['url'],temp,max_bytes=MAX_DOWNLOAD)
        data=temp.read_bytes();files=unpack_source(data,root/'files')
        archive=root/'source.archive';temp.replace(archive)
        index=index_source(root/'files')
        from read.api import atomic_io__atomic_json as atomic_json
        atomic_json(root/'index.json',index)
        status.update(index_sha256=file_digest(root/'index.json'),file_sha256={p.relative_to(root/'files').as_posix():file_digest(p) for p in (root/'files').rglob('*') if p.is_file()},state='available',archive=str(archive.relative_to(target)),archive_sha256=hashlib.sha256(data).hexdigest(),index_path=str((root/'index.json').relative_to(target)),source_root=str((root/'files').relative_to(target)),files=len(files))
    except Exception as exc:
        status.update(state='unavailable',reason=str(exc),error_type=type(exc).__name__,retry_after=time.time()+24*3600)
        if 'temp' in locals():temp.unlink(missing_ok=True)
    from core.api import services__atomic_json as atomic_json
    atomic_json(status_file,status);return status
