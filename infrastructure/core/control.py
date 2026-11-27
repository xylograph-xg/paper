"""Shared, fail-closed decisions over existing scoped control files.

Keep user intent, provider observations and browser leases in separate files.
Only this module interprets their precedence; it never starts a service.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from .paths import WorkspacePath as Path
import time


class InvalidControl(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    scope: str
    state: str
    reason: str
    source: str = ''
    expires_at: str | None = None
    requires_user_action: bool = False

    @property
    def allowed(self):
        return self.state == 'ready'

    def as_dict(self):
        return {**asdict(self), 'allowed': self.allowed}


def read_record(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise InvalidControl(f'{path.name}: {exc}') from exc
    if not isinstance(value, dict):
        raise InvalidControl(f'{path.name}: 控制记录必须为对象')
    return value


def evaluate(scope, *, paused=False, enabled=True, verification=False,
             unavailable='', blocked_until=0, source='', at=None):
    """Pause > disabled > manual verification > readiness > cooldown > ready."""
    if any(type(v) is not bool for v in (paused, enabled, verification)):
        return Decision(scope, 'invalid', '控制开关必须为布尔值', source, requires_user_action=True)
    if paused:
        return Decision(scope, 'paused', '用户已暂停', source)
    if not enabled:
        return Decision(scope, 'disabled', '功能或通道未启用', source)
    if verification:
        return Decision(scope, 'needs_user', '请在原页面完成访问验证；确认后才恢复', source, requires_user_action=True)
    if unavailable:
        return Decision(scope, 'unavailable', unavailable, source, requires_user_action=True)
    if isinstance(blocked_until, bool) or not isinstance(blocked_until, (int, float)) or not math.isfinite(blocked_until) or blocked_until < 0:
        return Decision(scope, 'invalid', '通道恢复时间无效', source, requires_user_action=True)
    if blocked_until > (time.time() if at is None else at):
        try:expires = datetime.fromtimestamp(blocked_until, timezone.utc).isoformat()
        except (ValueError,OverflowError,OSError):
            return Decision(scope, 'invalid', '通道恢复时间超出有效范围', source, requires_user_action=True)
        return Decision(scope, 'cooldown', '等待通道恢复探测', source,
                        expires)
    return Decision(scope, 'ready', '允许执行', source)


def pause_decision(config, scope, *, enabled=True):
    names = {'fetch': 'fetch-control.json', 'local_model': 'local-model-control.json',
             'web_cards': 'web-card-control.json', 'card_review': 'card-review-control.json',
             'card_correction': 'card-correction-control.json',
             'tab_watch': 'web-tab-watch-control.json'}
    path = Path(config['catalog_path']).parent / names[scope]
    try:
        control = read_record(path)
        decision = evaluate(scope, paused=control.get('paused_by_user', False), enabled=enabled, source=str(path))
        if decision.state == 'paused' and control.get('reason'):
            return Decision(scope, 'paused', str(control['reason']), str(path))
        from .seed_focus import active
        if decision.allowed and scope=='fetch' and active(config):
            return Decision(scope,'paused','仅手选种子模式暂停文献发现与拉取',str(path.parent/'seed-focus-control.json'))
        return decision
    except InvalidControl as exc:
        return Decision(scope, 'invalid', str(exc), str(path), requires_user_action=True)


def provider_decisions(folder, *, state=None, policy=None, at=None):
    folder = Path(folder)
    policy = policy or {}
    try:
        selection = read_record(folder / 'web-provider-selection.json')
        manual = read_record(folder / 'web-channel-control.json')
        blocks = read_record(folder / 'web-provider-control.json') if state is None else state
        selected = selection.get('provider', policy.get('provider'))
        allowed = selection.get('allowed_providers')
        if allowed is None:
            allowed = policy.get('allowed_providers')
            if allowed is None:allowed = [selected] if selected else ['chatgpt', 'qwen']
        if not isinstance(allowed, list) or any(p not in ('chatgpt', 'qwen', 'deepseek') for p in allowed):
            raise InvalidControl('网页通道授权列表无效')
        ceiling = policy.get('allowed_providers')
        if ceiling is not None:
            if not isinstance(ceiling,list) or any(p not in ('chatgpt','qwen','deepseek') for p in ceiling):
                raise InvalidControl('静态通道范围无效')
            allowed = [p for p in allowed if p in ceiling]
        result = {}
        for provider in ('chatgpt', 'qwen', 'deepseek'):
            if provider not in allowed:
                result[provider] = evaluate('provider:' + provider, enabled=False, source=str(folder / 'web-provider-selection.json'))
                continue
            channel = manual.get(provider, {})
            block = blocks.get(provider, {})
            if not isinstance(channel, dict) or not isinstance(block, dict):
                raise InvalidControl('网页通道状态必须为对象')
            unavailable = ''
            if selection.get('state') == 'login_required' and selected == provider:
                unavailable = '请先在专用浏览器登录当前通道'
            elif provider == 'deepseek' and selection.get('state') != 'ready':
                unavailable = 'DeepSeek通道尚未验收就绪'
            elif provider == 'qwen' and selection.get('reuse_qwen_window', policy.get('reuse_single_window', False)):
                window = read_record(folder / 'qwen-window.json')
                if window.get('state') != 'ready':
                    unavailable = window.get('error') or '固定Qwen窗口尚未核对就绪；不新建页面'
            result[provider] = evaluate('provider:' + provider, enabled=provider in allowed,
                paused=selection.get(provider + '_paused_by_user', False),
                verification=channel.get('manual_verification_required', False), unavailable=unavailable,
                blocked_until=block.get('blocked_until', 0), source=str(folder / 'web-channel-control.json'), at=at)
        return result
    except (InvalidControl, TypeError, AttributeError) as exc:
        return {p: Decision('provider:' + p, 'invalid', str(exc), str(folder), requires_user_action=True)
                for p in ('chatgpt', 'qwen', 'deepseek')}


def submission_decision(attempts):
    """A receipt, saved result or unknown attempt can never authorize a new send."""
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get('state') not in ('not_sent', 'deferred'):
            return Decision('submission', 'needs_inspection', '已有提交或不确定记录；只核对原会话，不重新发送',
                            requires_user_action=True)
    return Decision('submission', 'ready', '没有可能已发送的历史请求')


WEB_JOB_STATES = frozenset(('queued', 'preparing', 'submitting', 'submitted', 'collecting',
                            'completed', 'protected', 'failed', 'needs_inspection'))


def transition_decision(before, after):
    if before not in WEB_JOB_STATES or after not in WEB_JOB_STATES:
        return Decision('web_job', 'invalid', '未知任务状态')
    if before in ('completed', 'protected') and after != before:
        return Decision('web_job', 'invalid', '正式结果/人工保护不能由普通状态更新重新打开')
    if before in ('submitted', 'collecting', 'needs_inspection') and after in ('queued', 'preparing', 'submitting'):
        return Decision('web_job', 'needs_inspection', '可能已发送的任务不能重新进入发送队列', requires_user_action=True)
    return Decision('web_job', 'ready', '允许状态转换')


def explicit_reset(record):
    """An old boolean or an estimated timestamp is not website evidence."""
    evidence = record.get('reset_evidence') or {}
    try:
        return (record.get('explicit_reset') is True and record.get('reset_source') == 'live_browser_notice'
                and evidence.get('source') == 'live_browser_notice' and bool(evidence.get('notice'))
                and datetime.fromisoformat(evidence['not_before_utc']).timestamp() == record.get('blocked_until'))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def mutate_record(path, changes, *, replace=False, event='control_changed', validate=None):
    """Serialize control writers and preserve an append-only local change history."""
    from .services import atomic_json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / 'control-write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = read_record(path)
        after = dict(changes) if replace else {**before, **changes}
        # Cross-field decisions use the current record under the same lock as
        # publication. A rejected edit leaves both the record and history intact.
        if validate is not None:
            validate(after)
        if after == before:
            return after
        atomic_json(path, after)
        record = {'schema_version': 1, 'at': datetime.now(timezone.utc).isoformat(),
                  'event': event, 'source': path.name, 'before': before, 'after': after}
        with (path.parent / 'control-events.jsonl').open('a') as log:
            log.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
            log.flush()
            os.fsync(log.fileno())
        return after
