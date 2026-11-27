"""Deduplicate completed web inputs; preserve exact uploaded artifacts and receipts."""
import fcntl
import json
import os
import subprocess
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog, catalog__now as now
from core.api import services__atomic_json as atomic_json
from reading.api import reading_contract__file_digest as file_digest


def compact_completed(config, dry_run=False):
    root = Path(config['catalog_path']).parent
    library = Path(config['studio_library_root'])
    report = {'updated': now(), 'dry_run': dry_run, 'files': [], 'empty_logs_removed': 0, 'bytes_reclaimed': 0, 'errors': []}
    catalog = Catalog(config['catalog_path'])
    with (root/'web-artifact-retention.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return report
        with catalog.connect() as db:
            jobs = list(db.execute("SELECT paper_id FROM web_card_jobs WHERE state='completed'"))
            seeds={r[0] for r in db.execute('SELECT paper_id FROM manual_seed_roots')} if db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_roots'").fetchone() else set()
        for row in jobs:
            pid = row[0]
            if pid in seeds:
                trace=root/'seed-tracking'/pid/'trace.json'
                if not trace.exists() or json.loads(trace.read_text()).get('complete') is not True:continue
            folder, target = root/'web_cards'/pid, library/pid
            try:
                # All checks precede mutations; canonical publication and raw reply must match.
                proof = json.loads((target/'web-provenance.json').read_text())
                packet = json.loads((folder/'packet.json').read_text())
                attempt = proof['attempt']
                if Path(proof['packet']).resolve() != (folder/'packet.json').resolve():
                    continue
                if attempt.get('state') != 'response_saved' or file_digest(target/'card.json') != proof['card_sha256']:
                    continue
                raw = folder/attempt['provider']/'response-raw.txt'
                if file_digest(raw) != attempt['raw_sha256']:
                    continue
                context = json.loads((folder/'source-context.json').read_text())
                pairs = [(folder/'source.pdf', target/'source.pdf', packet['input_hashes']['source.pdf'])]
                pairs += [(folder/'pages'/Path(p['image']).name,
                           target/'pages'/Path(p['image']).name, p['sha256']) for p in context['page_manifest']]
                if any(file_digest(a) != h or file_digest(b) != h for a,b,h in pairs):
                    continue
                visual = folder/'visual.pdf'
                if visual.exists() and file_digest(visual) != packet['input_hashes']['visual.pdf']:
                    continue
                media_root = config.get('web_cards', {}).get('media_root')
                actions = []
                for a,b,h in pairs:
                    if a.resolve() == b.resolve():continue
                    action = {'path': str(a), 'canonical': str(b), 'sha256': h,
                              'bytes': a.stat().st_size, 'action': 'replace_with_symlink'}
                    if a.is_symlink():
                        if not media_root or not a.resolve().is_relative_to(Path(media_root).resolve()):continue
                        action['media_delete'] = str(a.resolve())
                    actions.append(action)
                # Re-rendered PDF bytes need not match the actual uploaded PDF hash.
                # Keep that artifact; deduplicate only byte-identical source/pages.
                if not actions:
                    continue
                if not dry_run:
                    # Persistent intent survives interruption; original input hash records stay untouched.
                    prior = []
                    if (folder/'retention.json').exists():
                        prior = json.loads((folder/'retention.json').read_text()).get('actions', [])
                    merged = {a['path']: a for a in prior + actions}
                    atomic_json(folder/'retention.json', {'updated': now(), 'policy': 'completed-evidence-preserved-v2',
                                'card_sha256': proof['card_sha256'], 'actions': list(merged.values()),
                                'visual_policy': 'preserve exact uploaded PDF; do not replace historical hashes with rebuilt bytes'})
                    for action in actions:
                        path = Path(action['path'])
                        if action['action'] == 'replace_with_symlink':
                            temporary = path.with_name(path.name+'.retention-link')
                            temporary.unlink(missing_ok=True)
                            temporary.symlink_to(os.path.relpath(Path(action['canonical']).resolve(), path.parent.resolve()))
                            os.replace(temporary, path)
                        else:
                            path.unlink()
                        if action.get('media_delete'):
                            Path(action['media_delete']).unlink(missing_ok=True)
                report['files'].extend(actions)
                report['bytes_reclaimed'] += sum(a['bytes'] for a in actions)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                report['errors'].append({'paper_id': pid, 'error': str(exc)})
        # Empty old per-invocation logs contain no diagnostics. Never unlink open/service logs.
        try:
            opened = subprocess.run(['/usr/sbin/lsof', '-n', '-P', '-Fn'], capture_output=True, text=True, timeout=20)
            if opened.returncode not in (0,1):
                raise OSError('cannot establish open-file inventory')
            open_paths = {str(Path(line[1:]).resolve()) for line in opened.stdout.splitlines() if line.startswith('n/')}
            for path in (root/'logs').glob('*.log'):
                if not path.name.startswith(('discover-', 'acquire-', 'fetchpdf-', 'model-job-')):
                    continue
                stat = path.stat()
                if stat.st_size or stat.st_mtime > time.time()-3600 or str(path.resolve()) in open_paths:
                    continue
                if not dry_run:
                    path.unlink()
                report['empty_logs_removed'] += 1
        except (OSError, subprocess.TimeoutExpired) as exc:
            report['errors'].append({'logs': str(exc)})
        if not dry_run:
            atomic_json(root/'web-artifact-retention.json', report)
    return report


if __name__ == '__main__':
    import argparse
    from core.api import catalog__load_config as load_config
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = compact_completed(load_config(args.config), args.dry_run)
    print(json.dumps({k: len(v) if k == 'files' else v for k,v in result.items()}, ensure_ascii=False, indent=2))
