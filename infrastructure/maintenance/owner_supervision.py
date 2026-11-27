"""Original LaunchAgent supervision; never owns CDP, queues or pause controls."""
import fcntl
import hashlib
import json
import os
import plistlib
import re
import signal
import subprocess
import tempfile
import time
from core.api import paths__WorkspacePath as Path, catalog__ROOT as ROOT
from core.api import services__atomic_json as atomic_json, runtime__alive as alive

LABEL = 'local.paper.web-cards'


def _code():
    from cards.api import web_card_service__code_version as version
    return version()['module_sha256']


def _release_evidence():
    """External kernel, ZIP adapter and SDK actually running for this source."""
    from cards.api import web_card_service__code_version as version
    return version().get('external_dependencies') or {}


def _external_ready(evidence):
    return (isinstance(evidence, dict) and evidence.get('status') == 'ok'
            and not evidence.get('errors') and bool(evidence.get('files'))
            and bool(evidence.get('import_root')) and bool(evidence.get('sdk_version')))


def _owner(config):
    from cards.api import web_card_service__status as status
    return status(config)


def _permitted(config):
    from cards.api import web_card_service__owner_enabled as enabled
    return enabled(config)


def _managed(config):
    path = Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
    spec = plistlib.loads(path.read_bytes())
    expected = [str(Path(config['web_cards']['python'])),'-u','-m','cards.web_card_service','run',
                '--config',str(Path(config['_config_path']).resolve())]
    if (spec.get('Label') != LABEL or not spec.get('WorkingDirectory')
            or Path(spec['WorkingDirectory']).resolve() != ROOT.resolve()
            or spec.get('ProgramArguments') != expected):
        raise ValueError('原LaunchAgent入口或配置不匹配，不监督其他服务')
    result = subprocess.run(['launchctl','print',f'gui/{os.getuid()}/{LABEL}'],capture_output=True,text=True,timeout=3)
    if result.returncode:raise ValueError('原LaunchAgent未注册，不创建或恢复其他入口')
    match = re.search(r'\bpid = (\d+)', result.stdout)
    return {'pid':int(match[1]) if match else None,'plist_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'submit_lock':spec.get('EnvironmentVariables',{}).get('WEB_GPT_SUBMIT_LOCK')}


def _submission_idle(lock_path=None):
    path = Path(lock_path or os.environ.get('WEB_GPT_SUBMIT_LOCK',str(Path(tempfile.gettempdir())/f'web-gpt-submit-{os.getuid()}.lock')))
    if not path.exists():return True
    with path.open('r') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        fcntl.flock(stream,fcntl.LOCK_UN)
    return True


def publish_validated(config, hashes, verification):
    """Record the exact source and external kernel tested by the maintainer;
    does not restart anything."""
    evidence = _release_evidence()
    if (hashes != _code() or not hashes or not _external_ready(evidence) or
            verification.get('external_dependencies') != evidence or
            any(verification.get(k) is not True for k in ('tests_passed','interfaces_passed','links_passed'))
            or type(verification.get('test_count')) is not int or verification['test_count'] <= 0):
        raise ValueError('源码、外部内核变化或验收不完整，不发布自动交接许可')
    record = {'schema_version':2,'module_sha256':hashes,
              'external_dependencies':evidence,'verification':verification,'validated_at':time.time()}
    atomic_json(Path(config['catalog_path']).parent/'validated-owner-release.json',record)
    return record


def _kickstart():
    subprocess.run(['launchctl','kickstart',f'gui/{os.getuid()}/{LABEL}'],check=True,capture_output=True,timeout=5)


def tick(config, *, at=None):
    """One bounded check on the existing HTTP-only watcher; no new daemon."""
    from core.api import catalog__load_config as load_config
    if config.get('_config_path'):config = load_config(config['_config_path'])
    policy = config.get('automatic_issue_handling',{}).get('owner_supervision',{})
    root = Path(config['catalog_path']).parent
    if config.get('automatic_issue_handling',{}).get('enabled') is not True or policy.get('enabled') is not True:
        return {'state':'disabled'}
    at = time.time() if at is None else at
    path = root/'owner-supervision.json'
    with (root/'owner-supervision.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'another_check_running'}
        report = json.loads(path.read_text()) if path.exists() else {}
        def finish(state, **values):
            if state != 'preserved_error':report.pop('error',None)
            report.update(state=state,checked_at=at,**values)
            atomic_json(path,report)
            return report
        if not _permitted(config):return finish('respect_pause')
        try:
            managed = _managed(config)
            current = _code()
            evidence = _release_evidence()
            release_path = root/'validated-owner-release.json'
            release = json.loads(release_path.read_text()) if release_path.exists() else {}
            checks = release.get('verification',{})
            approved = (type(release.get('schema_version')) is int and release['schema_version'] == 2
                        and release.get('module_sha256') == current
                        and release.get('external_dependencies') == evidence
                        and _external_ready(evidence)
                        and type(checks.get('test_count')) is int and checks['test_count'] > 0
                        and all(checks.get(k) is True for k in ('tests_passed','interfaces_passed','links_passed')))
            owner = _owner(config)
            pending = report.get('handoff')
            if pending:
                if managed['pid'] and managed['pid'] != pending['pid']:
                    if (owner.get('alive') and owner.get('pid') == managed['pid']
                            and owner.get('code_version',{}).get('module_sha256') == current):
                        report.pop('handoff',None)
                        return finish('new_owner_confirmed',new_owner_pid=owner['pid'])
                    return finish('waiting_new_owner_identity')
                if alive(pending['pid']):return finish('waiting_old_owner_exit')
                if managed['pid']:return finish('waiting_launchagent_exit')
                if not approved:return finish('waiting_validated_release')
                # No -k, no bootout/bootstrap; only the same registered idle job.
                if pending.get('restart_requested_at'):
                    return finish('waiting_original_entry_receipt')
                pending['restart_requested_at'] = at
                finish('original_entry_restart_intent')
                _kickstart()
                return finish('original_entry_restarted')
            if not owner.get('alive') or managed['pid'] != owner.get('pid'):
                return finish('owner_not_confirmed')
            if not approved:return finish('waiting_validated_release')
            if not owner.get('token'):return finish('owner_token_missing')
            identity = hashlib.sha256((str(owner['pid'])+owner['token']).encode()).hexdigest()
            observation_path = root/'web-page-observer.json'
            observation = json.loads(observation_path.read_text()) if observation_path.exists() else {}
            stale_seconds = max(300,policy.get('stale_seconds',300))
            stale = (at-owner.get('updated',at) >= stale_seconds and
                     (observation.get('owner_pid') != owner['pid'] or at-observation.get('updated',at) >= stale_seconds))
            previous = report.get('stale_check',{})
            if stale:
                same = previous.get('identity') == identity
                rounds = previous.get('rounds',0) if same else 0
                last = previous.get('at',0) if same else 0
                if not rounds or at-last >= 60:
                    rounds += 1;report['stale_check']={'identity':identity,'rounds':rounds,'at':at}
                stale = rounds >= 2
            else:report.pop('stale_check',None)
            loaded = owner.get('code_version',{}).get('module_sha256')
            changed = isinstance(loaded,dict) and bool(loaded) and loaded != current
            if not stale and not changed:return finish('healthy' if 'stale_check' not in report else 'confirming_stale_owner')
            if changed and not stale and not _submission_idle(managed.get('submit_lock')):
                validated_at = release.get('validated_at')
                # A graceful SIGTERM only sets the original owner's stop flag:
                # its existing drain guards finish original operations before
                # exit. Continuous legitimate submissions must not prevent a
                # validated update forever; never force-kill or start a peer.
                if (type(validated_at) not in (int,float) or not 0 < validated_at <= at
                        or at-validated_at < 300):
                    return finish('waiting_submission_boundary')
            recent = [value for value in report.get('requests',[]) if at-value < 3600]
            if len(recent) >= 2 or recent and at-recent[-1] < 300:return finish('cooldown')
            # Recheck live identity and pause immediately before the targeted signal.
            fresh = _owner(config);fresh_managed = _managed(config)
            if (not _permitted(config) or not fresh.get('alive') or fresh.get('pid') != owner['pid']
                    or fresh.get('token') != owner['token'] or fresh_managed != managed):
                return finish('identity_or_pause_changed')
            handoff = {'pid':owner['pid'],'token_sha256':hashlib.sha256(owner['token'].encode()).hexdigest(),
                       'identity':identity,'reason':'stale_owner' if stale else 'validated_source_update',
                       'requested':at,'plist_sha256':managed['plist_sha256']}
            # Intent survives a watcher interruption; a signal failure does not start a peer.
            report.update(handoff=handoff,requests=recent+[at])
            finish('graceful_handoff_requested')
            os.kill(owner['pid'],signal.SIGTERM)
            return report
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
            return finish('preserved_error',error=str(exc)[:600])
