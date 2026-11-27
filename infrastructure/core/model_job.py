"""A cancellable inference process; closing its lease kills bridge descendants."""
import json
import os
from .paths import WorkspacePath as Path
import signal
import subprocess
import sys
import tempfile

from .catalog import Catalog, ROOT
from .model_schedule import ModelWindowClosed, require_allowed, status


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def run(catalog, config, job, should_stop=lambda: False, heartbeat=lambda: None):
    require_allowed(config)
    from .catalog import validate_local_model
    validate_local_model(config)
    folder = catalog.path.parent / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    read_fd, write_fd = os.pipe()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='model-job-', dir=catalog.path.parent) as tmp:
            request = Path(tmp) / 'request.json'
            result = Path(tmp) / 'result.json'
            request.write_text(json.dumps({'config': config, 'job': job, 'result': str(result)}))
            request.chmod(0o600)
            with (folder / ('model-job-' + job['id'] + '.log')).open('a') as log:
                process = subprocess.Popen([sys.executable, '-m', 'core.model_job', str(request), str(read_fd)],
                                           cwd=ROOT, stdout=log, stderr=log, start_new_session=True,
                                           pass_fds=(read_fd,))
                os.close(read_fd); read_fd = None
                while process.poll() is None:
                    heartbeat()
                    if should_stop() or not status(config)['allowed']:
                        raise ModelWindowClosed('本地模型已暂停，任务保留待允许时段恢复')
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode == 75:
                    raise ModelWindowClosed('本地模型时段已关闭')
                if process.returncode:
                    log_path=folder / ('model-job-' + job['id'] + '.log')
                    with log_path.open('rb') as failure_log:
                        failure_log.seek(max(0,log_path.stat().st_size-1600))
                        details=failure_log.read().decode('utf-8',errors='replace')
                    raise RuntimeError('本地模型任务失败：'+details+'\n日志：'+str(log_path))
                return json.loads(result.read_text())['state']
    finally:
        os.close(write_fd)
        if read_fd is not None:
            os.close(read_fd)
        if process is not None:
            terminate(process)


def bootstrap(config):
    """Start the dedicated Ollama only when an allowed job needs it."""
    if not config.get('model', {}).get('autostart', False):
        return
    import fcntl
    from urllib.request import urlopen
    with (Path(config['catalog_path']).parent / 'ollama-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require_allowed(config)
        try:
            with urlopen(config['model']['base_url'].rstrip('/') + '/api/version', timeout=2):
                return
        except OSError:
            pass
        # This launcher is tied to read's dedicated service; other endpoints are caller-managed.
        if config['model']['base_url'].rstrip('/') != 'http://127.0.0.1:11435':
            raise RuntimeError('非默认 Ollama 地址须手动启动服务')
        env = {**os.environ, 'READ_OLLAMA_PYTHON': sys.executable,
               'OLLAMA_NUM_PARALLEL': str(config['model'].get('parallel_reading_jobs', 2))}
        subprocess.run(['bash', '-c', 'source "$1"; start_read_ollama', 'paper-model',
                        str(ROOT / 'read/scripts/ollama_env.sh')], env=env, check=True, timeout=45)


def main():
    from .runtime import watch_supervisor
    from . import services
    watch_supervisor(int(sys.argv[2]))
    data = json.loads(Path(sys.argv[1]).read_text())
    config, job = data['config'], data['job']
    # Each new local task uses the current saved model configuration. Active
    # tasks keep their frozen config; fetch and lane owners need no restart.
    from .catalog import load_config
    latest=load_config(config.get("_config_path"))
    if latest['catalog_path']==config['catalog_path']:
        config['model']=dict(latest['model'])
    require_allowed(config)
    from .catalog import validate_local_model
    validate_local_model(config)
    bootstrap(config)
    require_allowed(config)
    catalog = Catalog(config['catalog_path'])
    if job['kind'] == 'screen':
        services.screen(catalog, config, job['paper_id'])
        state = 'done'
    elif job['kind'] == 'deep_read':
        state = services.deep_read(catalog, config, job['paper_id'],force=job.get('payload',{}).get('force',False),resume=job.get('payload',{}).get('resume',False) or job.get('attempts',0)>1) or 'done'
    else:
        raise ValueError('不是本地模型任务')
    services.atomic_json(Path(data['result']), {'state': state})


if __name__ == '__main__':
    try:
        main()
    except ModelWindowClosed:
        sys.exit(75)
