"""Daily inference windows, explicit all-day operation, and expiring overrides."""
from datetime import datetime, timedelta, time
import json
from .paths import WorkspacePath as Path
from zoneinfo import ZoneInfo

MODEL_KINDS = ('screen', 'deep_read')


class ModelWindowClosed(RuntimeError):
    pass


def schedule_path(config):
    return Path(config['catalog_path']).parent / 'model-schedule.json'


def pause_path(config):
    return Path(config['catalog_path']).parent / 'local-model-control.json'


def set_user_pause(config, paused, reason=''):
    """Persist a human pause separately from daily windows and overrides."""
    if type(paused) is not bool:raise ValueError('paused 必须为布尔值')
    from .control import mutate_record
    mutate_record(pause_path(config), {'paused_by_user':paused, 'reason':reason,
                'updated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()},event='user_pause' if paused else 'user_resume')
    return status(config)


def minute(value, end=False):
    if value in ('24:00', '00:00') and end:
        return 1440
    try:
        hour, minutes = map(int, value.split(':'))
        if len(value) != 5 or not 0 <= hour < 24 or not 0 <= minutes < 60:
            raise ValueError()
        return hour * 60 + minutes
    except (ValueError, AttributeError, TypeError):
        raise ValueError('时间须为 HH:MM，结束时间可用 24:00') from None


def validate(settings):
    start, end = minute(settings['start']), minute(settings['end'], end=True)
    if not (600 <= start < end <= 1440 or (start == 0 and end == 1440)):
        raise ValueError('每日时段须位于 10:00–24:00；全天候请设置 00:00–24:00，其他夜间时段使用临时放行')
    ZoneInfo(settings['timezone'])
    until = settings.get('override_until')
    if until and datetime.fromisoformat(until).tzinfo is None:
        raise ValueError('临时放行到期时间必须带时区')
    return start, end


def status(config, at=None):
    settings = {'timezone': 'Asia/Shanghai', 'start': '10:00', 'end': '24:00',
                'override_until': None, **config.get('local_model_schedule', {})}
    try:
        path = schedule_path(config)
        if path.exists():
            saved = json.loads(path.read_text())
            settings.update({key: saved[key] for key in ('timezone', 'start', 'end', 'override_until')})
        from .control import pause_decision,read_record
        if pause_path(config).exists() and type(read_record(pause_path(config)).get('paused_by_user')) is not bool:
            raise ValueError('用户暂停设置缺少有效 paused_by_user')
        pause=pause_decision(config,'local_model')
        if not pause.allowed:
            return {**settings,'allowed':False,'mode':'paused' if pause.state=='paused' else 'invalid','next_allowed_at':None,'reason':pause.reason}
        if config.get('local_models_enabled',True) is False:
            return {**settings,'allowed':False,'mode':'disabled','next_allowed_at':None,
                    'reason':'本地模型功能已停用；须明确恢复功能与用户暂停后才能执行'}
        start, end = validate(settings)
        zone = ZoneInfo(settings['timezone'])
        current = at.astimezone(zone) if at is not None else datetime.now(zone)
        if at is not None and at.tzinfo is None:
            raise ValueError('核查时间必须带时区')
        until = datetime.fromisoformat(settings['override_until']) if settings.get('override_until') else None
        manual = bool(until and current < until)
        current_minute = current.hour * 60 + current.minute
        allowed = manual or start <= current_minute < end
        resume = None
        if not allowed:
            day = current.date() + (timedelta(days=1) if current_minute >= end else timedelta())
            resume = datetime.combine(day, time(start // 60, start % 60), zone).isoformat()
        all_day = start == 0 and end == 1440
        return {**settings, 'allowed': allowed, 'mode': 'all_day' if all_day else 'manual' if manual else 'scheduled',
                'next_allowed_at': resume, 'checked_at': current.isoformat(),
                'reason': '全天候允许运行' if all_day else '临时放行中' if manual else '允许运行' if allowed else '本地模型等待允许时段'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**settings, 'allowed': False, 'mode': 'invalid', 'next_allowed_at': None,
                'reason': '模型时段设置无效：' + str(exc)}


def require_allowed(config):
    value = status(config)
    if not value['allowed']:
        raise ModelWindowClosed(value['reason'])


def configure(config, *, start=None, end=None, allow_minutes=None, reset=False, at=None):
    from .services import atomic_json
    from .catalog import Catalog
    existing = status(config)
    settings = {'timezone': config.get('local_model_schedule', {}).get('timezone', 'Asia/Shanghai'),
                'start': '10:00', 'end': '24:00', 'override_until': None}
    if not reset:
        if existing['mode'] == 'invalid':
            raise ValueError('当前设置无效，请先恢复默认时段')
        settings.update({key: existing[key] for key in settings})
        if start is not None or end is not None:
            if start is None or end is None:
                raise ValueError('请同时设置开始与结束时间')
            settings.update(start=start, end='24:00' if end == '00:00' else end, override_until=None)
        if allow_minutes is not None:
            if type(allow_minutes) is not int or not 1 <= allow_minutes <= 1440:
                raise ValueError('临时放行须为 1–1440 分钟')
            current = at or datetime.now(ZoneInfo(settings['timezone']))
            if current.tzinfo is None:
                raise ValueError('放行时间必须带时区')
            settings['override_until'] = (current + timedelta(minutes=allow_minutes)).isoformat()
    validate(settings)
    atomic_json(schedule_path(config), settings)
    Catalog(config['catalog_path']).event(None, 'model_schedule_changed', settings)
    return status(config, at)
