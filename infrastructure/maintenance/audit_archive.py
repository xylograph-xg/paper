"""Explicit content-addressed archive of selected immutable JSON evidence."""
from core.api import paths__workspace_root as _workspace_root
import argparse
from datetime import datetime, timezone
import hashlib
import json
from core.api import paths__WorkspacePath as Path
import re

ROOT = _workspace_root()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def capture(sources, label, root=ROOT):
    root = Path(root).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', label):
        raise ValueError('归档标签须为字母、数字、下划线或连字符')
    archive = root / 'data/audit_index'
    index = archive / (label + '.json')
    if index.exists():
        raise ValueError('归档标签已经存在；历史索引不可覆盖')
    entries, pending = [], []
    for name in sources:
        source = (root / name).resolve()
        relative = source.relative_to(root)
        if len(relative.parts)<2 or relative.parts[0] != 'data' or relative.parts[1] == 'audit_index':
            raise ValueError('仅显式归档data中的既有证据文件')
        if source.suffix != '.json' or not any(token in source.name for token in ('manifest', 'fingerprint', 'verification', '-stop-')):
            raise ValueError('运行控制/答案不属于归档白名单')
        raw = source.read_bytes()
        json.loads(raw)
        fingerprint = digest(raw)
        target = archive / 'objects' / (fingerprint + '.json')
        if target.exists() and target.read_bytes() != raw:
            raise ValueError('不可变快照损坏；禁止覆盖')
        pending.append((target, raw))
        entries.append({'source': str(relative), 'sha256': fingerprint, 'bytes': len(raw), 'object': str(target.relative_to(archive))})
    for target, raw in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as stream:
                stream.write(raw)
        except FileExistsError:
            if target.read_bytes() != raw:
                raise ValueError('并发归档产生不一致内容')
    archive.mkdir(parents=True, exist_ok=True)
    value = {'schema_version': 1, 'kind':'immutable_evidence_index', 'captured_at': datetime.now(timezone.utc).isoformat(), 'entries': entries,
             'scope': 'immutable evidence only; never restore runtime controls'}
    with index.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return index


def verify(root=ROOT, *, details=False):
    archive = Path(root) / 'data/audit_index'
    total = 0
    skipped=[]
    for index in sorted(archive.glob('*.json')):
        payload=json.loads(index.read_text())
        if not isinstance(payload,dict) or 'entries' not in payload:
            if isinstance(payload,dict) and payload.get('kind')=='immutable_evidence_index':raise ValueError('归档索引缺少entries：'+index.name)
            skipped.append(index.name);continue
        if payload.get('schema_version')!=1 or not isinstance(payload['entries'],list):
            raise ValueError('归档索引结构或版本无效：'+index.name)
        for entry in payload['entries']:
            path = (archive / entry['object']).resolve()
            if not path.is_relative_to(archive.resolve()):
                raise ValueError('证据快照路径越界')
            raw = path.read_bytes()
            if digest(raw) != entry['sha256'] or len(raw) != entry['bytes']:
                raise ValueError('证据指纹不一致：' + entry['source'])
            total += 1
    return {'verified_entries':total,'skipped_non_indexes':skipped} if details else total


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('capture', 'verify'))
    parser.add_argument('--label')
    parser.add_argument('--source', action='append', default=[])
    args = parser.parse_args()
    if args.command == 'capture':
        if not args.label or not args.source:parser.error('capture需要--label和至少一个--source')
        print(capture(args.source, args.label))
    else:print('Verified immutable evidence:', verify())
