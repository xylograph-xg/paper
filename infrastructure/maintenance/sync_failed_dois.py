# -*- coding: utf-8 -*-
"""Read-only Catalog snapshot -> managed, journal-grouped desktop DOI lists."""
from core.api import paths__workspace_root as _workspace_root
import argparse
import collections
import fcntl
import hashlib
import html
import json
import math
import os
from core.api import paths__WorkspacePath as Path
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import time

ROOT = _workspace_root()


def tick(config, now=None):
    """Called by the existing local watcher; durable 2h cadence across restarts."""
    now = time.time() if now is None else now
    folder = Path(config['catalog_path']).parent
    status_path = folder / 'failed-doi-sync-status.json'
    output = Path.home() / 'Desktop/拉取失败'
    # A separate lock prevents overlapping local/manual timer calls.
    with (folder / 'failed-doi-timer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'already_running'}
        try:
            state = json.loads(status_path.read_text()) if status_path.exists() else {}
            last = state.get('last_success', 0)
            if not last and (output / '更新状态.json').exists():
                last = datetime.fromisoformat(json.loads((output / '更新状态.json').read_text())['updated_shanghai']).timestamp()
            due = max(last + 7200, state.get('retry_at', 0))
            if now < due:
                report = {**state, 'state': 'waiting', 'last_success': last, 'next_run': due,
                          'checked_at': now, 'owner_pid': os.getpid(), 'scheduler': 'local.paper.web-tab-watch', 'interval_seconds': 7200}
            else:
                result = sync(Path(config['catalog_path']), output)
                report = {'state': 'synced', 'last_success': now, 'next_run': now + 7200,
                          'checked_at': now, 'owner_pid': os.getpid(), 'scheduler': 'local.paper.web-tab-watch',
                          'interval_seconds': 7200, 'result': result}
        except Exception as exc:
            report = {'state': 'error', 'error': str(exc), 'checked_at': now, 'retry_at': now + 300,
                      'last_success': locals().get('last', 0), 'owner_pid': os.getpid(),
                      'scheduler': 'local.paper.web-tab-watch', 'interval_seconds': 7200}
        atomic(status_path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return report


def atomic(path, content):
    tmp = path.with_name('.' + path.name + '.tmp')
    tmp.write_text(content, encoding='utf-8')
    os.replace(tmp, path)


def normalize_doi(value):
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*', '', str(value or '').strip(), flags=re.I).lower()
    return value if re.fullmatch(r'10\.\d{4,9}/\S+', value) else None


def publication_key(record):
    """Newest first; preserve date precision and place unknown dates last."""
    value = str(record.get('publication_date') or '').strip()
    match = re.fullmatch(r'(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?', value)
    if match:
        year, month, day = (int(v or 0) for v in match.groups())
        try:
            datetime(year, month or 1, day or 1)
            return (-year, -month, -day, record['doi'])
        except ValueError:
            pass
    year = str(record.get('year') or '').strip()
    return (-int(year), 0, 0, record['doi']) if re.fullmatch(r'\d{4}', year) and int(year) > 0 else (0, 0, 0, record['doi'])


def collect(db):
    groups = collections.defaultdict(set)
    details = []
    skipped = collections.Counter()
    identifiers = dict(db.execute("SELECT paper_id,value FROM identifiers WHERE kind='doi' ORDER BY value DESC"))
    failures = {r[0] for r in db.execute("SELECT paper_id FROM jobs WHERE kind IN ('acquire','acquire_fallback') AND state IN ('failed','needs_manual')")}
    for row in db.execute('SELECT id,title,metadata,acquisition,asset_path,asset_hash,decision FROM papers ORDER BY created,id'):
        pid, title, raw, state, asset, digest, decision = row
        meta = json.loads(raw)
        # Available is established by the existing verified importer/acquisition flow.
        if state == 'available' and asset and digest and Path(asset).is_file() and Path(asset).stat().st_size:
            continue
        if state not in ('needs_manual_download', 'needs_access_check') and pid not in failures:
            continue
        if decision in ('reject', 'ignore') or any(meta.get(k) for k in ('out_of_scope', 'is_correction', 'identity_review_required', 'version_review_required')):
            skipped['protected_or_out_of_scope'] += 1
            continue
        doi = normalize_doi(identifiers.get(pid) or meta.get('doi'))
        if not doi:
            skipped['missing_valid_doi'] += 1
            continue
        journal = ' '.join(html.unescape(str(meta.get('venue') or meta.get('journal') or '期刊待核对')).split()) or '期刊待核对'
        groups[journal].add(doi)
        details.append({'doi': doi, 'journal': journal, 'title': title, 'paper_id': pid, 'acquisition': state,
                        'publication_date': meta.get('publication_date'), 'year': meta.get('year')})
    details.sort(key=lambda record: (record['journal'], publication_key(record)))
    return groups, details, dict(skipped)


def normalize_journal(name):
    """Case/entity/space-insensitive journal key for the editable level table."""
    return re.sub(r'\s+', ' ', html.unescape(str(name or ''))).strip().casefold()


def load_levels(path):
    data = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}
    levels = {normalize_journal(k): int(v) for k, v in (data.get('levels') or {}).items()}
    aliases = {normalize_journal(k): normalize_journal(v) for k, v in (data.get('aliases') or {}).items()}
    return {'levels': levels, 'aliases': aliases, 'default': int(data.get('default', 1)),
            'max_level': max(1, int(data.get('max_level', 5))),
            'level_weight': min(1.0, max(0.0, float(data.get('level_weight', 0.75)))),
            'source': str(path)}


def journal_level(journal, levels):
    key = normalize_journal(journal)
    key = levels['aliases'].get(key, key)
    return levels['levels'].get(key, levels['default'])


def rank_journals(groups, levels):
    """Rank journals by level (default 75%) and failed-DOI count (default 25%)."""
    max_count = max((len(dois) for dois in groups.values()), default=1)
    rows = []
    for journal, dois in groups.items():
        count = len(dois)
        level = journal_level(journal, levels)
        level_score = level / levels['max_level']
        count_score = math.log1p(count) / math.log1p(max_count) if max_count > 1 else 1.0
        score = levels['level_weight'] * level_score + (1 - levels['level_weight']) * count_score
        rows.append({'journal': journal, 'level': level, 'count': count,
                     'level_score': round(level_score, 4), 'count_score': round(count_score, 4),
                     'score': round(score, 4)})
    rows.sort(key=lambda row: (-row['score'], -row['count'], normalize_journal(row['journal'])))
    for index, row in enumerate(rows, 1):
        row['rank'] = index
    return rows


def write_ranking(output, ranked, levels):
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    payload = {'updated_shanghai': stamp, 'formula': 'level_weight * (level/max_level) + (1-level_weight) * log1p(count)/log1p(max_count)',
               'level_weight': levels['level_weight'], 'max_level': levels['max_level'],
               'level_source': levels['source'], 'journals': ranked}
    atomic(output / '期刊排序.json', json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 拉取失败期刊排序', '',
             f"综合分 = {levels['level_weight']:.0%} × 期刊水平 + {(1-levels['level_weight']):.0%} × 失败数量（log 归一化）。",
             '期刊水平来自可编辑的 `infrastructure/config/journal-levels.json`，1–5 为领域相对分层，不是 JCR/中科院分区官方数据。', '',
             '| 排名 | 期刊 | 水平(1-5) | 失败 DOI 数 | 综合分 |', '| ---: | --- | ---: | ---: | ---: |']
    for row in ranked:
        journal = str(row['journal']).replace('|', '\\|')
        lines.append(f"| {row['rank']} | {journal} | {row['level']} | {row['count']} | {row['score']:.4f} |")
    atomic(output / '期刊排序.md', '\n'.join(lines) + '\n')
    return payload


def sync(catalog, output, levels_path=None):
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest_path = output / '.清单索引.json'
        previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'files': {}, 'dois': []}
        with sqlite3.connect(catalog.resolve().as_uri() + '?mode=ro', uri=True, timeout=30) as db:
            db.execute('BEGIN')
            groups, details, skipped = collect(db)
        files = {}
        publication_order = {}
        for record in details:
            key = (record['journal'], record['doi'])
            publication_order[key] = min(publication_order.get(key, publication_key(record)), publication_key(record))
        levels = load_levels(levels_path or ROOT / 'config/journal-levels.json')
        ranked = rank_journals(groups, levels)
        write_ranking(output, ranked, levels)
        master = ['# 综合排序：期刊水平 75% + 失败数量 25%',
                  '# 每行一个 DOI；期刊内按发表时间新到旧',
                  '# rank | journal | level(1-5) | failures | score']
        for row in ranked:
            master.append(f"# {row['rank']} | {row['journal']} | {row['level']} | {row['count']} | {row['score']:.4f}")
            master.extend(sorted(groups[row['journal']], key=lambda doi: publication_order[(row['journal'], doi)]))
        atomic(output / '全部失败DOI_按期刊排序.txt', '\n'.join(master) + '\n')
        backup = output / '.修改前备份'

        def preserve(path, expected):
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                backup.mkdir(exist_ok=True)
                stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
                (backup / (stamp + '-' + path.name)).write_bytes(path.read_bytes())

        for journal, dois in sorted(groups.items()):
            safe = re.sub(r'[\x00-\x1f/\\:*?"<>|]', '_', journal).strip(' .')[:90] or '期刊待核对'
            name = safe + '--' + hashlib.sha256(journal.encode()).hexdigest()[:8] + '.txt'
            content = '\n'.join(sorted(dois, key=lambda doi: publication_order[(journal, doi)])) + '\n'
            path = output / name
            if not path.exists() or path.read_text() != content:
                preserve(path, previous['files'].get(name, {}).get('sha256'))
                atomic(path, content)
            files[name] = {'journal': journal, 'count': len(dois), 'sha256': hashlib.sha256(content.encode()).hexdigest()}
        for name, info in previous['files'].items():
            if Path(name).name != name or not name.endswith('.txt'):
                raise ValueError('索引文件名不安全')
            if name not in files:
                path = output / name
                preserve(path, info.get('sha256'))
                path.unlink(missing_ok=True)
        current = sorted({d['doi'] for d in details})
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
        summary = {'updated_shanghai': stamp, 'catalog': str(catalog.resolve()), 'journals': len(files),
                   'doi_count': len(current), 'added': len(set(current) - set(previous['dois'])),
                   'removed': len(set(previous['dois']) - set(current)), 'skipped': skipped,
                   'sort_order': 'journal_level_75_count_25',
                   'ranked_journals': len(ranked), 'level_source': levels['source']}
        atomic(output / '文献明细.json', json.dumps(details, ensure_ascii=False, indent=2) + '\n')
        atomic(output / '更新状态.json', json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        atomic(manifest_path, json.dumps({'files': files, 'dois': current}, ensure_ascii=False, indent=2) + '\n')
        atomic(output / '使用说明.md', '# 拉取失败 DOI 清单\n\n## 综合排序\n\n`全部失败DOI_按期刊排序.txt` 按“期刊水平 75% + 失败数量 25%”综合分排列；`期刊排序.md`/`期刊排序.json` 给出排名、水平、数量与分数。期刊水平见可编辑的 `infrastructure/config/journal-levels.json`，不是 JCR/中科院分区官方数据；默认 1–5 为领域相对分层。\n\n每个期刊一个 txt 文件，每行一个 DOI，可直接复制。内部按文献发表时间从新到旧排序；日期缺失时用发表年份，时间均缺失放最后，同时间按 DOI 稳定排序。期刊名来自原数据库元数据，不猜测或合并不同名称；缺失期刊归入“期刊待核对”。\n\n由本地现有 local.paper.web-tab-watch 后台程序每 2 小时扫描主 Catalog 中新增失败和已获取原文，增删对应 DOI，不依赖 Codex 聊天或自动化。电脑休眠或关机期间无法执行，后台恢复后补做到期同步。不将尚未尝试的文献当成失败。身份/版本待核对、范围外、勘误及人工排除记录不进入普通手动下载清单。\n\n手动下载的 PDF 请放到桌面“文献暂存”，由现有导入流程核对身份并登记。只有 Catalog 登记 available 且具有原文路径、哈希及非空文件时才视为已获取；仅下载到其他位置或手动删除某行不会使项目知道已完成。\n\n清单由脚本维护，手动更改会在下次刷新时同步回数据库状态，改动前副本保存在隐藏的 .修改前备份 文件夹。其他用户文件不会被清理。\n\n立即刷新：\n\n```sh\npython3 /Users/xiaoyanhao/project/paper/infrastructure/maintenance/sync_failed_dois.py\n```\n\n文献明细.json 提供标题与状态；更新状态.json 记录上海时间、数量、增删及跳过原因。两小时任务扫描现有发现/拉取链路新进入数据库的记录，不解除任何暂停、不独立外发或重新启动拉取。\n')
        with (output / '.更新历史.jsonl').open('a') as log:
            log.write(json.dumps(summary, ensure_ascii=False) + '\n')
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'data/catalog.sqlite3')
    parser.add_argument('--output', type=Path, default=Path.home() / 'Desktop/拉取失败')
    parser.add_argument('--levels', type=Path, default=ROOT / 'config/journal-levels.json')
    args = parser.parse_args()
    print(json.dumps(sync(args.catalog, args.output, args.levels), ensure_ascii=False))
