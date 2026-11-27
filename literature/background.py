"""Explicitly started metadata-only worker. One owner, eight process classifiers, one sidecar writer.

Imports/status never start a worker. Original catalog is opened only by core's read API.
No source-record lookup, PDF access, model, browser or other workflow control occurs here.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from core.api import literature_catalog__metadata_rows as metadata_rows
from .classifier import classify, metadata_fingerprint, RULE_VERSION
from .store import Store, fingerprint

PARALLEL = 8
SCAN_SECONDS = 60
BATCH_SIZE = 256
_CHILDREN = {}
_PROCESS_ACTIVE = None
_PROCESS_CONTROL = None


def _process_init(control, counter):
    global _PROCESS_ACTIVE, _PROCESS_CONTROL
    _PROCESS_ACTIVE = counter
    _PROCESS_CONTROL = Path(control)


def _process_predict(doc):
    # Each child checks this task's own pause, and reports actual active classification.
    if read(_PROCESS_CONTROL).get('paused_by_user', False): return None
    with _PROCESS_ACTIVE.get_lock(): _PROCESS_ACTIVE.value += 1
    try: return predict(doc)
    finally:
        with _PROCESS_ACTIVE.get_lock(): _PROCESS_ACTIVE.value -= 1


def paths(config, stage='level1'):
    if stage not in ('level1', 'level2'): raise ValueError('标注范围不合法')
    base = Path(config['catalog_path']).resolve().parent
    return {name: base / ('literature-' + stage + '-' + name + suffix) for name, suffix in (
        ('service', '.json'), ('control', '.json'), ('release', '.json'),
        ('owner', '.lock'), ('start', '.lock'), ('log', '.log'))}


def read(path):
    try:
        value = json.loads(path.read_text())
        if isinstance(value,dict) and Path(path).name in ('literature-level1-control.json','literature-level2-control.json'):
            from core.api import seed_focus__active as focus_active
            if focus_active({'catalog_path':str(Path(path).parent/'catalog.sqlite3')}):
                value={**value,'paused_by_user':True,'paused_by_seed_focus':True,'reason':'仅手选种子模式暂停标签工程'}
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def locked(path, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try: yield
        finally: fcntl.flock(stream, fcntl.LOCK_UN)


def alive(pid):
    if type(pid) is not int or pid <= 0: return False
    try: os.kill(pid, 0); return True
    except PermissionError: return True
    except OSError: return False


def source_fingerprint():
    root = Path(__file__).parent
    return fingerprint({p.name: p.read_bytes().hex() for p in sorted(
        [*root.glob('*.py'), root / 'taxonomy.json'])})


def generation_fingerprint():
    root = Path(__file__).parent
    return fingerprint({name: (root / name).read_bytes().hex()
                        for name in ('classifier.py', 'focus.py', 'taxonomy.json')})


def level1_release(config, *, stage='level1'):
    """Record the exact source accepted after project and global checks, never start it."""
    release = {'source_fingerprint': source_fingerprint(), 'rule_version': RULE_VERSION,
               'validated_at': datetime.now(timezone.utc).isoformat()}
    if stage == 'level2': release['python_executable'] = os.path.abspath(sys.executable)
    atomic(paths(config, stage)['release'], release)
    return release


def level1_status(config, *, stage='level1'):
    """Read files only, including on an unconfigured or missing catalog. No migrations."""
    for nonce, process in list(_CHILDREN.items()):
        if process.poll() is not None: _CHILDREN.pop(nonce, None)
    p = paths(config, stage); state = read(p['service']); control = read(p['control'])
    live = alive(state.get('pid')) and time.time() - state.get('updated', 0) < 30
    paused = control.get('paused_by_user', False)
    return {**state, 'registered': bool(state or control), 'alive': live,
            'paused_by_user': paused, 'parallel': PARALLEL, 'scan_seconds': SCAN_SECONDS,
            'actual_parallel': state.get('actual_parallel', 0) if live else 0,
            'state': 'paused' if paused else state.get('state', 'stopped') if live or state.get('state') == 'awaiting_validation' or (state.get('state') == 'starting' and time.time()-state.get('updated',0)<30) else 'stopped'}


def level1_control(config, paused, *, stage='level1'):
    if type(paused) is not bool: raise ValueError('暂停设置须为布尔值')
    if not paused: return level1_start(config, stage=stage)
    with locked(paths(config, stage)['start']):
        atomic(paths(config, stage)['control'], {'paused_by_user': True, 'updated': time.time()})
    return level1_status(config, stage=stage)


def level1_start(config, *, stage='level1'):
    """Idempotent start of this worker only; retained pause is changed only by this call."""
    p = paths(config, stage)
    with locked(p['start']):
        release = read(p['release'])
        if release.get('source_fingerprint') != source_fingerprint():
            raise ValueError('标签源码尚未完成本版验收，保留现状')
        executable = release.get('python_executable') if stage == 'level2' else sys.executable
        if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
            raise ValueError('二级标签缺少已验收的PDF解析运行环境')
        atomic(p['control'], {'paused_by_user': False, 'updated': time.time()})
        previous = read(p['service'])
        # A live process, even with a stale heartbeat, is never duplicated or killed here.
        if alive(previous.get('pid')): return level1_status(config, stage=stage)
        if previous.get('state') == 'starting' and time.time() - previous.get('updated', 0) < 30:
            return level1_status(config, stage=stage)
        nonce = uuid.uuid4().hex
        atomic(p['service'], {**previous, 'state': 'starting', 'pid': None,
                              'nonce': nonce, 'actual_parallel': 0, 'updated': time.time()})
        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(root / 'infrastructure/bootstrap'), str(root), env.get('PYTHONPATH', '')])
        with p['log'].open('ab') as log:
            module = 'literature.background' if stage == 'level1' else 'literature.background_level2'
            _CHILDREN[nonce] = subprocess.Popen([executable, '-u', '-m', module, '--run',
                              '--catalog', str(Path(config['catalog_path']).resolve()), '--nonce', nonce],
                             cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    return level1_status(config, stage=stage)


def document(row, generation):
    """The complete and immutable scientific input: title and abstract, no keywords."""
    return {'paper_id': row['id'], 'title': row['title'],
            'abstract': row.get('metadata', {}).get('abstract') or '', 'chunks': [],
            'metadata_fingerprint': metadata_fingerprint(row), 'source_fingerprint': None,
            'annotation_scope': 'level1', 'generation_fingerprint': generation,
            'limitations': ['仅依据标题和摘要；自动候选标签，未经科学核验；二级未运行'] +
                ([] if row.get('metadata', {}).get('abstract') else ['missing_abstract'])}


def predict(doc):
    value = classify(doc)
    for key in ('supporting_labels', 'inherited_labels', 'mentions'):
        value[key] = [v for v in value.get(key, []) if v['level'] == 1]
    value.update(level2=[], level2_state='not_requested', annotation_scope='level1',
                 generation_fingerprint=doc['generation_fingerprint'])
    return value


class Worker:
    process_init = staticmethod(_process_init)

    def __init__(self, config, nonce):
        self.config = config; self.p = paths(config); self.nonce = nonce
        self.source = source_fingerprint(); self.generation = generation_fingerprint()
        self.store = Store(Path(config['catalog_path']).parent / 'literature.sqlite3')
        self.stop = False; self.mutex = threading.Lock(); self.active = 0
        self.executor = None; self.counter = None
        self.failures = read(self.p['service']).get('failures', {})
        self.state = {'pid': os.getpid(), 'nonce': nonce, 'parallel': PARALLEL,
                      'rule_version': RULE_VERSION, 'source_fingerprint': self.source,
                      'generation_fingerprint': self.generation, 'scan_seconds': SCAN_SECONDS,
                      'scope': 'level1', 'models_used': False, 'scientific_verified': False}

    def emit(self, **data):
        with self.mutex:
            self.state.update(data)
            atomic(self.p['service'], {**self.state, 'actual_parallel': self.counter.value if self.counter is not None else self.active,
                                      'updated': time.time(), 'failures': self.failures})

    def allowed(self):
        return not self.stop and not read(self.p['control']).get('paused_by_user', False)

    def guarded_predict(self, doc):
        if not self.allowed(): return None
        with self.mutex: self.active += 1
        try:
            return predict(doc)
        finally:
            with self.mutex: self.active -= 1

    def cycle(self):
        rows = metadata_rows(self.config['catalog_path'])
        with self.store.connect() as db:
            heads = {r['paper_id']: dict(r) for r in db.execute('''SELECT h.paper_id,
                r.metadata_fingerprint,r.rule_version,json_extract(r.result,'$.generation_fingerprint') generation,
                json_array_length(json_extract(r.result,'$.level1')) core_count
                FROM level1_heads h JOIN automatic_runs r ON r.id=h.run_id''')}
        current = lambda row: row['id'] in heads and (
            heads[row['id']]['metadata_fingerprint'] == metadata_fingerprint(row)
            and heads[row['id']]['rule_version'] == RULE_VERSION
            and heads[row['id']]['generation'] == self.generation)
        done = [r for r in rows if current(r)]
        pending = [r for r in rows if not current(r)]
        self.emit(total=len(rows), missing_abstract=sum(not r.get('metadata',{}).get('abstract') for r in rows), completed=len(done), matched=sum(heads[r['id']]['core_count'] > 0 for r in done),
                  undetermined=sum(not heads[r['id']]['core_count'] for r in done), queued=len(pending),
                  failed=sum(r['id'] in self.failures for r in pending), last_scan_at=datetime.now(timezone.utc).isoformat())
        ready = [r for r in pending if time.time() >= self.failures.get(r['id'], {}).get('retry_at', 0)][:BATCH_SIZE]
        if not ready: return False
        if not self.allowed(): return False
        self.emit(state='running')
        # A bounded batch keeps pause checks and source identity checks responsive.
        pool = self.executor or ThreadPoolExecutor(max_workers=PARALLEL)
        try:
            futures = {pool.submit(_process_predict if self.executor else self.guarded_predict, document(r, self.generation)): r for r in ready}
            results = []
            for future in as_completed(futures):
                row = futures[future]
                try:
                    result = future.result()
                    if result is not None: results.append((document(row, self.generation), result))
                except Exception as exc:
                    old = self.failures.get(row['id'], {}); attempts = old.get('attempts', 0) + 1
                    self.failures[row['id']] = {'attempts': attempts, 'retry_at': time.time() + min(3600, 60 * 2 ** min(attempts - 1, 6)), 'error': str(exc)[:300]}
                self.emit()
        finally:
            if self.executor is None: pool.shutdown(wait=True, cancel_futures=True)
        # Re-read only metadata through the public read API, never source files or cards.
        latest = {r['id']: r for r in metadata_rows(self.config['catalog_path'])}
        for doc, result in results:
            if not self.allowed(): break
            if source_fingerprint() != self.source: break
            row = latest.get(doc['paper_id'])
            if row is None or metadata_fingerprint(row) != doc['metadata_fingerprint']: continue
            try:
                self.store.save_automatic_run(doc, result, scope='level1')
                self.failures.pop(doc['paper_id'], None)
                self.emit(last_finished_at=datetime.now(timezone.utc).isoformat(), last_paper_id=doc['paper_id'])
            except Exception as exc:
                self.failures[doc['paper_id']] = {'attempts': 1, 'retry_at': time.time() + 60, 'error': str(exc)[:300]}
        return True

    def run(self):
        context = multiprocessing.get_context('spawn')
        self.counter = context.Value('i', 0)
        self.executor = ProcessPoolExecutor(max_workers=PARALLEL, mp_context=context,
            initializer=self.process_init, initargs=(str(self.p['control']), self.counter))
        self.emit(state='running')
        # Separate heartbeat makes long single-document classification visible and truthful.
        heartbeat_stop = threading.Event()
        def heartbeat():
            while not heartbeat_stop.wait(2): self.emit()
        thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
        try:
            while not self.stop:
                if source_fingerprint() != self.source or read(self.p['release']).get('source_fingerprint') != self.source:
                    self.emit(state='awaiting_validation'); break
                if not self.allowed():
                    self.emit(state='paused'); time.sleep(1); continue
                control_revision = read(self.p['control']).get('updated')
                try:
                    more = self.cycle()
                    self.emit(state='running' if more else 'waiting', error='')
                except Exception as exc:
                    self.emit(state='error', error=str(exc)[:500]); more = False
                if not more:
                    for _ in range(SCAN_SECONDS):
                        if (not self.allowed() or source_fingerprint() != self.source
                                or read(self.p['control']).get('updated') != control_revision): break
                        time.sleep(1)
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)
            heartbeat_stop.set(); thread.join(timeout=3)
            self.emit(state='awaiting_validation' if self.state.get('state') == 'awaiting_validation' else 'stopped')


def main(stage='level1', worker_type=Worker):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog'); parser.add_argument('--nonce', default='')
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ('run', 'start', 'pause', 'status'): group.add_argument('--' + flag, action='store_true')
    args = parser.parse_args()
    if args.catalog: config = {'catalog_path': args.catalog}
    else:
        from core.api import catalog__load_config as load_config
        config = load_config()
    if not args.run:
        value = level1_start(config, stage=stage) if args.start else level1_control(config, True, stage=stage) if args.pause else level1_status(config, stage=stage)
        print(json.dumps(value, ensure_ascii=False)); return
    p = paths(config, stage)
    try:
        with locked(p['owner'], blocking=False):
            # A stale launch or changed release must never replace an existing owner.
            if read(p['service']).get('nonce') != args.nonce: return
            if read(p['release']).get('source_fingerprint') != source_fingerprint(): return
            worker = worker_type(config, args.nonce)
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: setattr(worker, 'stop', True))
            worker.run()
    except BlockingIOError:
        return


if __name__ == '__main__': main()
