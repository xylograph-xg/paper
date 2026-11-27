"""Local user-library intake; notes never become source evidence or model input."""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
from html import escape
from core.api import paths__WorkspacePath as Path
from xml.etree import ElementTree


def install(catalog):
    from fetch.api import manual_seed_lineage__install as install_lineage
    install_lineage(catalog)
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS manual_literature_items(
            path TEXT PRIMARY KEY, source_hash TEXT NOT NULL, paper_id TEXT,
            state TEXT NOT NULL, error TEXT NOT NULL, updated REAL NOT NULL, stored_path TEXT)''')
        columns={row['name'] for row in db.execute('PRAGMA table_info(manual_literature_items)')}
        if 'stored_path' not in columns:
            db.execute('ALTER TABLE manual_literature_items ADD COLUMN stored_path TEXT')
        db.execute('''CREATE TABLE IF NOT EXISTS manual_card_priority(
            paper_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, created REAL NOT NULL)''')


_SUPPLEMENT_HEADING = re.compile(r'^(?:supplementary|supporting)\s+(?:information|materials?)\b', re.I)
_ARTICLE_BODY = re.compile(r'\babstract\b|Cite This|摘要', re.I)


def _supplement_cover(text):
    """True only for a supplement cover page, not an article's SI link line.

    Publisher front matter often contains a standalone ``Supporting
    Information`` link (ACS does this on the first page).  A real supplement
    cover has the heading but no abstract or citation immediately after it.
    """
    lines = [line.strip() for line in text.splitlines()[:25] if line.strip()]
    for index, line in enumerate(lines):
        if not _SUPPLEMENT_HEADING.match(line):
            continue
        following = '\n'.join(lines[index + 1:index + 13])
        return not _ARTICLE_BODY.search(following)
    return False


def _first_page_heading(doc):
    """Join the largest-font front-matter lines into the printed article title."""
    lines = []
    for block in doc[0].get_text('dict')['blocks']:
        for line in block.get('lines', []):
            spans = line.get('spans', [])
            if not spans or line['bbox'][1] >= doc[0].rect.height * .6:
                continue
            text = ''.join(s['text'] for s in spans).strip()
            if not text or text[0] in '■●◆▪▫◦':
                continue
            lines.append((max(s['size'] for s in spans), text))
    # Section headings use the largest font on some layouts; the title is
    # always in the front matter before the abstract or first section.
    cutoff = next((index for index, (_, text) in enumerate(lines)
                   if re.match(r'^(?:abstract|摘要|■?\s*(?:introduction|引言))\b', text, re.I)),
                  len(lines))
    front = lines[:cutoff] or lines
    largest = max((size for size, _ in front), default=0)
    return ' '.join(text for size, text in front if size >= largest - .5).strip()


def inspect_file(path):
    """Runs under the configured PDF Python, with no external metadata request."""
    from core.api import catalog__doi as doi
    path = Path(path)
    before = path.stat()
    if before.st_size>100*1024*1024:raise ValueError('输入文件超过100MB')
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(i.file_size for i in entries)>100*1024*1024:
                raise ValueError('DOCX展开额度超限')
            info=archive.getinfo('word/document.xml')
            if info.file_size>8*1024*1024 or info.file_size>max(1,info.compress_size)*200:
                raise ValueError('DOCX正文展开额度超限')
            with archive.open(info) as stream:data=stream.read(8*1024*1024+1)
            if b'\x00' in data:raise ValueError('DOCX XML不接受UTF-16/32或NUL，保留原文件')
            if len(data)>8*1024*1024 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('DOCX正文超限或包含实体声明')
            import io
            depth=nodes=0
            parser=ElementTree.iterparse(io.BytesIO(data),events=('start','end'))
            for event,node in parser:
                if event=='start':
                    depth+=1;nodes+=1
                    if depth>128 or nodes>100000:raise ValueError('DOCX XML结构额度超限')
                else:depth-=1
            root=parser.root
        # Return identifiers only. Personal scientific summaries stay local.
        text = ' '.join(n.text or '' for n in root.iter(
            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        identifiers = sorted({doi(x.rstrip('.,;)')) for x in
            re.findall(r'10\.\d{4,9}/[^\s<>"\[\]]+', text)})
        result = {'kind': 'reading_reference', 'dois': identifiers}
    elif path.suffix.lower() == '.pdf':
        import pymupdf
        from core.api import services__validate_pdf as validate_pdf, services__verify_identity as verify_identity
        from core.api import services__pdf_dois as pdf_dois
        text = validate_pdf(path)
        with pymupdf.open(path) as doc:
            heading = _first_page_heading(doc)
            metadata_title = (doc.metadata.get('title') or '').strip()
            # Publisher PDF metadata is often just a filename stem ("ci6c00425
            # 1..7").  Use the printed heading when the metadata title is not
            # actually present on the first page, so identity is verified
            # against the document instead of rejected.
            title = metadata_title
            if (not title or title.lower() not in text[:4000].lower()) and heading:
                title = heading
            record = {'title': title}
            if _supplement_cover(text):
                raise ValueError('补充材料不能单独作为论文原文，保留待核对')
            identifiers = sorted(pdf_dois(path, text))
            if len(identifiers) == 1:
                record['doi'] = identifiers[0]
            if not record.get('doi'):
                # arXiv preprints have no DOI; the permanent arXiv id is the
                # catalog identity and avoids a permanent "missing DOI" hold.
                arxiv = re.search(r'arXiv[:\s]*(\d{4}\.\d{4,5})(?:v\d+)?', text, re.I)
                if arxiv:
                    record['arxiv_id'] = arxiv.group(1)
            verify_identity(path, record)
            result = {'kind': 'original_pdf', 'record': record, 'pages': len(doc)}
    else:
        raise ValueError('仅支持原文PDF或Word书目/阅读笔记')
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('文件仍在写入，留待下一轮')
    return {**result, 'source_hash': digest}


def _store_item(catalog, path, source_hash, paper_id, state, error, stored_path=None, original_path=None):
    with catalog.connect() as db:
        if original_path is not None and str(original_path) != str(path):
            db.execute('DELETE FROM manual_literature_items WHERE path=?', (str(original_path),))
        db.execute('''INSERT INTO manual_literature_items(path,source_hash,paper_id,state,error,updated,stored_path)
                      VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(path) DO UPDATE SET source_hash=excluded.source_hash,paper_id=excluded.paper_id,
                      state=excluded.state,error=excluded.error,updated=excluded.updated,stored_path=excluded.stored_path''',
                   (str(path), source_hash, paper_id, state, error, time.time(),
                    str(stored_path) if stored_path else None))


def _process_file(catalog, config, path, seed_lane, manual_folder, seed_storage, storage):
    from core.api import catalog__ROOT as ROOT
    pid = None; digest = ''; error = ''; state = ''; stored = None
    try:
        command = [config['web_cards']['pdf_python'], '-m', 'reading.manual_literature', str(path)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError(result.stderr[-1000:])
        info = json.loads(result.stdout); digest = info['source_hash']
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('文件在解析后变化，留待下一轮')
        with catalog.connect() as db:
            if info['kind'] == 'original_pdf':
                matches = list(db.execute('SELECT id FROM papers WHERE asset_hash=?', (digest,)))
            else:
                matches = [row for identifier in info['dois'] for row in db.execute(
                    "SELECT paper_id AS id FROM identifiers WHERE kind='doi' AND value=?", (identifier,))]
        ids = {row['id'] for row in matches}
        if len(ids) > 1:
            raise ValueError('对应多个文献身份，保留待核对')
        if ids:
            pid = next(iter(ids))
        elif info['kind'] == 'original_pdf':
            record = info['record']
            identifier = (('doi', record['doi']) if record.get('doi') else
                          ('arxiv_id', record['arxiv_id']) if record.get('arxiv_id') else None)
            if not identifier:
                raise ValueError('新PDF缺少唯一DOI或arXiv标识，保留待身份核对')
            with catalog.connect() as db:
                existing = db.execute("SELECT paper_id FROM identifiers WHERE kind=? AND value=?",
                                      identifier).fetchone()
            pid = existing['paper_id'] if existing else catalog.upsert(
                record, reason='文献库种子' if seed_lane else '手动DOI原文',
                seed=seed_lane, candidate=not seed_lane)
        else:
            raise ValueError('阅读笔记没有唯一已登记论文；请放入论文原文PDF')
        paper = catalog.get(pid)
        if seed_lane and path.suffix.lower() != '.pdf':
            raise ValueError('文献库只接受原文PDF作为种子')
        alternate = False
        if info['kind'] == 'original_pdf':
            if paper.get('asset_hash') and paper['asset_hash'] != digest:
                # The same DOI is already stored from another copy.  Never
                # overwrite it or the card, but a library seed must still
                # register and leave the intake directory instead of looping.
                if not (seed_lane and paper['acquisition'] == 'available'
                        and paper.get('asset_path') and Path(paper['asset_path']).is_file()):
                    raise ValueError('同一文献原文版本/指纹不同，不覆盖现有原文或卡片')
                alternate = True
            if not paper.get('asset_path'):
                copy_command = [config['web_cards']['pdf_python'], '-m', 'reading.manual_literature',
                                str(path), '--import-config', config['_config_path'], '--paper-id', pid,
                                '--source-hash', digest]
                copied = subprocess.run(copy_command, cwd=ROOT, capture_output=True, text=True, timeout=60)
                if copied.returncode:
                    raise ValueError((copied.stderr.strip().splitlines() or ['原文导入失败'])[-1][:500])
                paper = catalog.get(pid)
        if paper['acquisition'] != 'available' or not paper.get('asset_hash') or not Path(paper.get('asset_path') or '').is_file():
            raise ValueError('论文原文尚未取得，笔记不替代原文')
        with Path(paper['asset_path']).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != paper['asset_hash']:
            raise ValueError('已入库原文指纹变化，阻止制卡')
        protected = any(paper['metadata'].get(k) for k in
                        ('identity_review_required', 'version_review_required', 'out_of_scope'))
        if seed_lane:
            from .completed_literature_archive import move_verified
            def seed_guard():
                current = catalog.get(pid)
                if current.get('asset_hash') != actual or not Path(current.get('asset_path') or '').is_file():
                    raise ValueError('种子原文指纹变化，保留原文件')
            if config['manual_literature'].get('keep_seed_originals') is True:
                seed_guard()
                stored = path
            elif alternate:
                stored = move_verified(path, seed_storage / 'alternates', digest, lambda: None)
            else:
                stored = move_verified(path, seed_storage, digest, seed_guard)
            from fetch.api import manual_seed_lineage__register_root as register_root
            register_root(catalog, paper, paper['asset_path'] if alternate else stored, actual)
            with catalog.connect() as db:
                db.execute('INSERT INTO manual_card_priority VALUES(?,?,?) ON CONFLICT(paper_id) '
                           'DO UPDATE SET source_hash=excluded.source_hash', (pid, actual, time.time()))
            state = 'seed_stored'
            if alternate:
                error = '文献库副本与已入库原文指纹不同；种子使用已入库原文'
        else:
            with catalog.connect() as db:
                db.execute("DELETE FROM manual_seed_roots WHERE paper_id=? AND source_path LIKE ?",
                           (pid, str(manual_folder) + '/%'))
            if not paper.get('seed') and not paper.get('card_path') and paper.get('candidate_order') is None:
                catalog.upsert({'title': paper['title'], 'doi': paper['metadata'].get('doi')},
                               reason='手动DOI原文', candidate=True)
                paper = catalog.get(pid)
            if info['kind'] == 'original_pdf':
                from .completed_literature_archive import move_verified
                def guard():
                    current = catalog.get(pid)
                    if current.get('asset_hash') != digest or not Path(current.get('asset_path') or '').is_file():
                        raise ValueError('手动原文指纹变化，保留原文件')
                stored = move_verified(path, storage, digest, guard)
                state = 'stored'
            else:
                state = 'manual_existing_card' if paper.get('card_path') else 'manual_protected' if protected else 'manual_registered'
    except Exception as exc:
        state = 'seed_needs_inspection' if seed_lane else 'needs_inspection'
        error = str(exc)[-1000:]
    _store_item(catalog, stored or path, digest, pid, state, error,
                stored_path=stored, original_path=path if stored and stored != path else None)
    return {'path': str(stored or path), 'source_path': str(path), 'paper_id': pid,
            'state': state, 'error': error, 'seed': seed_lane}


def _seed_card(db, paper, originals, reviews):
    from .completed_literature_archive import digest

    if paper['decision'] in ('reject', 'ignore') or any(
        paper['metadata'].get(key) for key in ('identity_review_required', 'version_review_required', 'out_of_scope')
    ):
        return None, '文献身份、版本、范围或人工决定待核对', '', ''
    if not paper.get('card_path'):
        return None, '处理中', '', ''
    try:
        raw = Path(paper['card_path']).read_bytes()
        document = json.loads(raw)
        meta = document['meta']
        source = paper['asset_hash']
        if not source or meta.get('source_original_sha256') != source:
            return None, '卡片与当前原文的指纹不一致', '', ''
        for original in originals:
            try:
                if digest(Path(original)) == source:
                    break
            except OSError:
                continue
        else:
            return None, '卡片与当前原文的指纹不一致', '', ''
        sha = hashlib.sha256(raw).hexdigest()
        review = db.execute(
            "SELECT state FROM card_review_jobs WHERE paper_id=? AND source_sha256=? AND card_sha256=?",
            (paper['id'], source, sha),
        ).fetchone() if reviews else None
        state = review['state'] if review else ''
        verified = state == 'passed' and meta.get('scientific_verified') is True
        if verified and meta.get('production_contract_complete') is True:
            return 'complete', '成品卡', sha, ''
        summary = document.get('one_line_summary')
        if (meta.get('producer') == 'web_card_service' and meta.get('structural_complete') is True
                and isinstance(summary, str) and summary.strip() and paper['decision'] == 'unreviewed'
                and not db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",
                                   (paper['id'],)).fetchone()):
            status = '待科学核验及生产验收'
            if verified:
                status = '科学核验已通过，待生产验收'
            elif state == 'submitted':
                status = '核验请求已提交，等待收取完整回答'
            elif state in ('failed', 'needs_user', 'correction_queued', 'rework_queued'):
                status = '核验或修正待处理'
            return 'preview', status, sha, summary
        return None, '已有卡片，当前版本等待完成科学核验与生产验收', '', ''
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, '卡片或原文证据待核对', '', ''


def seed_cards(catalog):
    """Current original-bound cards for registered manual roots."""
    with catalog.connect() as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('manual_seed_roots','card_review_jobs','manual_literature_items')")}
        if 'manual_seed_roots' not in tables:
            return {}
        copies = {}
        if 'manual_literature_items' in tables:
            for row in db.execute(
                "SELECT i.paper_id,i.path FROM manual_literature_items i JOIN manual_seed_roots m USING(paper_id) "
                "JOIN papers p ON p.id=i.paper_id WHERE i.state='seed_stored' AND i.error='' AND i.source_hash=p.asset_hash"
            ):
                copies.setdefault(row['paper_id'], []).append(row['path'])
        cards = {}
        for row in db.execute(
            "SELECT p.id,p.decision,p.metadata,p.asset_hash,p.asset_path,p.card_path,m.source_path "
            "FROM papers p JOIN manual_seed_roots m ON m.paper_id=p.id "
            "WHERE p.card_path IS NOT NULL AND m.input_hash=p.asset_hash"
        ):
            paper = dict(row)
            paper['metadata'] = json.loads(paper['metadata'])
            if paper['metadata'].get('user_seed_disabled') or paper['metadata'].get('is_correction'):
                continue
            originals = dict.fromkeys(path for path in
                [paper['asset_path'], paper['source_path'], *copies.get(paper['id'], [])] if path)
            kind, status, sha, _ = _seed_card(db, paper, originals, 'card_review_jobs' in tables)
            if kind:
                cards[paper['id']] = {'kind': kind, 'status': status, 'sha256': sha}
        return cards


def _write_seed_index(catalog, folder, items):
    complete, previews, pending = [], [], []
    with catalog.connect() as db:
        reviews = db.execute("SELECT 1 FROM sqlite_master WHERE name='card_review_jobs'").fetchone()
        for item in items:
            pdf = Path(item['path'])
            if not item['seed'] or not pdf.is_relative_to(folder) or pdf.suffix.lower() != '.pdf':
                continue
            paper = catalog.get(item['paper_id']) if item['paper_id'] else {}
            title = paper.get('title') or pdf.name
            original = f'<a href="{escape(pdf.as_uri())}">打开原文</a>'
            status = item['error'] or ('处理中' if paper else '等待登记')
            kind = None
            if item['state'] == 'seed_stored' and not item['error'] and paper:
                kind, status, _, summary = _seed_card(db, paper, [pdf], reviews)
            if kind == 'complete':
                link = f'<a href="{escape(Path(paper["card_path"]).as_uri())}">打开成品卡</a>'
                complete.append(f'<li>{escape(title)}　{original}　{link}</li>')
            elif kind == 'preview':
                card = Path(paper['card_path'])
                link = f'<a href="{escape(card.as_uri())}">打开候选卡</a>'
                previews.append(f'<li>{escape(title)}　{original}　{link}<small>{status}</small>'
                                f'<details><summary>展开候选摘要</summary><p>{escape(summary)}</p></details></li>')
            else:
                pending.append(f'<li>{escape(title)}　{original}<small>{escape(status)}</small></li>')
    def section(title, rows):
        return f'<h2>{title} · {len(rows)}</h2><ul>{"".join(rows) or "<li>暂无</li>"}</ul>'
    page = ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>文献库索引</title><style>body{font:16px/1.6 system-ui;margin:3rem auto;padding:0 1rem;'
            'max-width:65rem}li{margin:.6rem 0}small{display:block;color:#555}</style>'
            '<h1>文献库索引</h1><p>成品卡已通过科学核验与生产验收。候选卡供先行阅读，内容可能随核验和修正更新。</p>'
            + section('已有成品卡', complete) + section('可预览候选卡', previews)
            + section('暂无可展示卡片', pending) + '</html>')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(page)
            stream.close()
            os.replace(temporary, folder/'文献库索引.html')
        finally:
            temporary.unlink(missing_ok=True)


def run_once(catalog, config):
    policy = config.get('manual_literature', {})
    if not policy.get('enabled'):
        return {'state': 'disabled'}
    install(catalog)
    manual_folder = Path(policy['directory']).expanduser().resolve()
    seed_folder = Path(policy.get('seed_directory') or Path.home() / 'Desktop/文献库').expanduser().resolve()
    seed_storage = Path(policy.get('seed_storage_directory') or seed_folder.parent / 'library/seeds').expanduser().resolve()
    storage = Path(policy.get('storage_directory') or seed_folder.parent / 'library/manual').expanduser().resolve()
    for folder in (manual_folder, seed_folder, seed_storage, storage):
        folder.mkdir(parents=True, exist_ok=True)
    if manual_folder == seed_folder or seed_folder.is_relative_to(manual_folder) or manual_folder.is_relative_to(seed_folder):
        raise ValueError('文献库种子目录不能与文献暂存目录重合或嵌套')
    for folder,label in ((seed_storage,'种子库'),(storage,'原文存储')):
        if folder in (manual_folder,seed_folder) or folder.is_relative_to(manual_folder) or manual_folder.is_relative_to(folder) or folder.is_relative_to(seed_folder) or seed_folder.is_relative_to(folder):
            raise ValueError(label+'目录不能与暂存/种子入口重合或嵌套')
    root = catalog.path.parent
    from core.api import services__atomic_json as atomic_json
    with (root / 'manual-literature.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'waiting_scan_lock'}
        report = {'state': 'checked', 'updated': time.time(), 'directory': str(manual_folder),
                  'seed_directory': str(seed_folder), 'seed_storage_directory': str(seed_storage),
                  'storage_directory': str(storage), 'items': []}
        present = set()
        for folder, seed_lane in ((seed_folder, True), (manual_folder, False)):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ('.pdf', '.docx'):
                    continue
                present.add(str(path))
                report['items'].append(_process_file(catalog, config, path, seed_lane, manual_folder, seed_storage, storage))
        keep = {'stored','seed_stored'}
        reported = {str(item['path']) for item in report['items']}
        with catalog.connect() as db:
            for row in db.execute("SELECT path,source_hash,paper_id,state,error,stored_path FROM manual_literature_items "
                                  "WHERE state IN ('stored','seed_stored') ORDER BY path"):
                if row['path'] in reported:
                    continue
                report['items'].append({'path':row['path'],'source_path':row['path'],'stored_path':row['stored_path'],
                                        'paper_id':row['paper_id'],'state':row['state'],'error':row['error'],
                                        'seed':row['state']=='seed_stored'})
            for row in db.execute("SELECT path,state FROM manual_literature_items"):
                if row['state'] in keep:
                    continue
                if row['path'] not in present:
                    db.execute("UPDATE manual_literature_items SET state='removed',error='文件已移出手动库',updated=? WHERE path=?",
                               (time.time(), row['path']))
            removed_ids = {row[0] for row in db.execute(
                "SELECT paper_id FROM manual_literature_items WHERE state='removed' AND paper_id IS NOT NULL")}
            old_roots = {row[0] for row in db.execute(
                "SELECT paper_id FROM manual_seed_roots WHERE source_path LIKE ?", (str(manual_folder) + '/%',))}
            for pid in old_roots:
                db.execute("DELETE FROM manual_seed_roots WHERE paper_id=? AND source_path LIKE ?",
                           (pid, str(manual_folder) + '/%'))
            for pid in removed_ids:
                db.execute("DELETE FROM manual_seed_roots WHERE paper_id=? AND (source_path LIKE ? OR source_path LIKE ?)",
                           (pid, str(manual_folder) + '/%', str(seed_folder) + '/%'))
            db.execute("DELETE FROM manual_card_priority WHERE paper_id NOT IN (SELECT paper_id FROM manual_literature_items "
                       "WHERE paper_id IS NOT NULL AND state IN ('seed_stored'))")
            for pid in old_roots | removed_ids:
                if db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=?', (pid,)).fetchone():
                    continue
                row = db.execute('SELECT metadata FROM papers WHERE id=?', (pid,)).fetchone()
                if not row:
                    continue
                data = json.loads(row[0]); data['selected_as_seed'] = False; data.pop('user_seed_disabled', None); data.pop('manual_seed_fast_lane', None)
                db.execute('UPDATE papers SET seed=0,metadata=? WHERE id=?', (json.dumps(data, ensure_ascii=False), pid))
                db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE kind='discover' AND paper_id=? "
                           "AND state='queued' AND json_extract(payload,'$.trigger')='seed_added'", (time.time(), pid))
                db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',
                           (pid, 'human_seed_change', json.dumps({'seed_id': pid, 'seed_action': 'remove',
                                                                  'reason': '文献暂存改为普通候选/种子文件已移出'}), time.time()))
        from cards.api import web_card_queue__select as select
        from fetch.api import manual_seed_lineage__reconcile as reconcile
        report['lineage'] = reconcile(catalog)
        report['selection'] = select(catalog, config)
        report['archive'] = {'state': 'disabled', 'reason': '文献库改为种子入口；原文存储目录为 ' + str(storage)}
        if policy.get('keep_seed_originals') is True:
            _write_seed_index(catalog, seed_folder, [item for item in report['items']
                                                    if item['source_path'] in present])
        atomic_json(root / 'manual-literature-status.json', report)
        return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('file')
    parser.add_argument('--import-config')
    parser.add_argument('--paper-id')
    parser.add_argument('--source-hash')
    args = parser.parse_args()
    info = inspect_file(args.file)
    if args.import_config:
        from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config
        from core.api import services__store_asset as store_asset, services__verify_identity as verify_identity, services__validate_pdf as validate_pdf
        config = load_config(args.import_config)
        catalog = Catalog(config['catalog_path']); paper = catalog.get(args.paper_id)
        if info['source_hash'] != args.source_hash:
            raise ValueError('扫描后文件变化，阻止导入')
        verify_identity(args.file, paper['metadata'])
        version = paper['metadata'].get('arxiv_version_id')
        if version and version.lower() not in validate_pdf(args.file).lower():
            raise ValueError('预印本版本未核对，不自动导入')
        target, digest = store_asset(args.file, config)
        if digest != args.source_hash:raise ValueError('导入复制期间文件变化，阻止绑定')
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE papers SET asset_path=?,asset_hash=?,acquisition='available' "
                "WHERE id=? AND asset_path IS NULL AND card_path IS NULL AND decision='unreviewed'",
                (target,digest,args.paper_id)).rowcount
            if not changed:
                raise ValueError('原文/卡片或人工决定已变化，保留原绑定')
        catalog.event(args.paper_id,'manual_library_import',{'path':str(Path(args.file).resolve()),'sha256':digest})
    print(json.dumps(info, ensure_ascii=False))
