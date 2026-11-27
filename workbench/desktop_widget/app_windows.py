"""Observe Codex Web GPT task tabs using its local launcher register and events."""
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


LOG_TAIL = 1024 * 1024
FRESH_SECONDS = 60
STAGES = {'browser_page': '打开任务页', 'new_chat_preparation': '准备临时聊天',
          'effort_selection': '设置模型强度', 'prompt_attachment': '准备提示',
          'file_attachment': '上传附件', 'send': '发送中'}
CHECKPOINTS = {'send-accepted': '已发送，等待回答', 'response-visible': '已看到回答',
               'response-stalled-60s': '等待回答（曾连续 60 秒无变化）', 'turn-completed': '收取回答'}
ISSUES = {'tab_renderer_gone': '页面进程已退出', 'tab_navigation_failed': '页面导航失败',
          'turn_authentication_blocked': '等待登录', 'tab_unresponsive': '页面无响应',
          'orphan_turn_expired': '任务心跳超时'}
REMOVED = {'tab_closed', 'tab_closed_externally', 'tab_released', 'retained_tab_expired',
           'failed_tab_expired', 'manual_orphan_turn_reaped'}
PHASE = re.compile(r'browser turn ([\w-]+) stage=(\w+) started$')
CHECK = re.compile(r'browser diagnostic trace=([\w-]+) checkpoint=\d+-([\w-]+) ')
GENERATING = re.compile(r'browser turn ([\w-]+) submission accepted evidence=generation_running$')
BROKER = re.compile(r'broker trace=([\w-]+) (queued|delivered|completed) call=([\w-]+)\b')


def log_tail(path):
    # The launcher rotates to .1. Read at most one MiB, including across rotation.
    parts = []
    remaining = LOG_TAIL
    for source in (path, path.with_suffix('.jsonl.1')):
        try:
            with source.open('rb') as stream:
                end = stream.seek(0, 2)
                start = max(0, end - remaining)
                stream.seek(start)
                data = stream.read(end - start)
        except FileNotFoundError:
            continue
        parts.append(data.partition(b'\n')[2] if start else data)
        remaining -= len(data)
        if not remaining:
            break
    for part in reversed(parts):
        for line in part.splitlines():
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(value, dict):
                yield value


def observed_tabs(events, launched, now):
    tabs, by_trace = {}, {}
    for record in events:
        try:
            stamp = datetime.fromisoformat(record['at'].replace('Z', '+00:00')).timestamp()
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
        if not launched <= stamp <= now:
            continue
        event = str(record.get('event', '')).removeprefix('browser.')
        info = record.get('detail')
        if not isinstance(info, dict):
            continue
        tab_id, trace = info.get('tabId'), info.get('traceId')
        if event in ('tab_created', 'tab_reused') and isinstance(tab_id, str) and isinstance(trace, str):
            # At capacity a new tab can silently evict a terminal page. Keep only
            # terminal identities confirmed after the most recent such allocation.
            if event == 'tab_created' and info.get('tabCount') == 5:
                for key in [key for key, tab in tabs.items() if tab['terminal']]:
                    del tabs[key]
            tabs[tab_id] = dict(id=tab_id, trace=trace, at=stamp, phase='准备任务页',
                                issue='', terminal=False, approval=False, calls={}, phase_at=stamp)
            by_trace[trace] = tab_id
            continue
        phase = None
        broker = None
        if event == 'runtime.daemon_stdout':
            line = info.get('line')
            if not isinstance(line, str):
                continue
            match = PHASE.search(line)
            checkpoint = CHECK.search(line)
            broker = BROKER.search(line)
            if match:
                trace, stage = match.groups()
                phase = STAGES.get(stage)
            elif checkpoint:
                trace, name = checkpoint.groups()
                phase = CHECKPOINTS.get(name)
            elif broker:
                trace = broker[1]
            else:
                generating = GENERATING.search(line)
                if generating:
                    trace, phase = generating[1], '已观测到生成'
            if not (phase or broker):
                continue
        if not isinstance(trace, str):
            continue
        tab = tabs.get(tab_id or by_trace.get(trace))
        if not tab or tab['trace'] != trace:
            continue
        if event in REMOVED:
            del tabs[tab['id']]
            continue
        if event in ('tab_completed', 'tab_retained', 'failed_tab_preserved', 'turn_ended'):
            status = info.get('status')
            failed = event == 'failed_tab_preserved' or status == 'failed'
            tab.update(terminal=True, issue='', phase='任务失败' if failed else
                       '任务已中止' if status == 'aborted' else '任务已完成')
            tab['calls'].clear()
        elif tab['terminal']:
            continue
        elif event in ISSUES:
            tab['issue'] = ISSUES[event]
        elif event == 'tab_responsive' and tab['issue'] == ISSUES['tab_unresponsive']:
            tab['issue'] = ''
        elif event == 'tool_approval' and type(info.get('pending')) is bool:
            tab['approval'] = info['pending']
        elif broker:
            if broker[2] == 'completed':
                tab['calls'].pop(broker[3], None)
            else:
                tab['calls'][broker[3]] = broker[2]
            tab['phase'] = '等待回答'
        elif phase:
            tab['phase'], tab['phase_at'] = phase, stamp
        elif event != 'turn_heartbeat':
            continue
        tab['at'] = stamp

    result = []
    for tab in sorted(tabs.values(), key=lambda t: t['id']):
        state = tab['phase']
        if state == '已观测到生成' and now - tab['phase_at'] > 20:
            state = '已发送，等待回答'
        if tab['calls']:
            state = '执行工具' if 'delivered' in tab['calls'].values() else '等待执行工具'
        if tab['approval'] and not tab['terminal']:
            state = '等待工具批准'
        state = tab['issue'] or state
        if now - tab['at'] > FRESH_SECONDS and not tab['terminal']:
            state = '待观测'
        result.append(dict(id=tab['id'], state=state, terminal=tab['terminal'],
                           checked=datetime.fromtimestamp(tab['at'], ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')))
    return result


def app_windows():
    home = Path.home()
    register = home / '.codex-chatgpt-web/runtime/launcher-browser.json'
    logs = home / 'Library/Application Support/Codex Web GPT/logs/launcher.jsonl'
    try:
        descriptor = json.loads(register.read_bytes())
        if descriptor.get('kind') != 'codex-web-gpt-launcher' or type(descriptor.get('pid')) is not int:
            return {}
        targets = descriptor['surfaceTargets']
        if not isinstance(targets, dict) or descriptor['surfaceId'] not in targets:
            return {}
        count = len(targets) - 1
        if not 0 <= count <= 5:
            return {}
        # Use the launcher process lifetime to exclude a previous login/session.
        proc = subprocess.run(['/bin/ps', '-p', str(descriptor['pid']), '-o', 'lstart=,comm='],
                              capture_output=True, text=True, timeout=1, env={'LC_ALL': 'C', 'TZ': 'UTC'})
        started, marker, _ = proc.stdout.strip().partition(' /')
        if not marker or '/Codex Web GPT.app/Contents/MacOS/' not in proc.stdout:
            return {}
        launched = datetime.strptime(started.strip(), '%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc).timestamp()
        tabs = observed_tabs(log_tail(logs), launched, time.time())
        # Registration may change during sampling, e.g. as one turn replaces another.
        after = json.loads(register.read_bytes())
        if after.get('pid') != descriptor['pid'] or after.get('surfaceTargets') != targets:
            return {}
        if len(tabs) > count:
            tabs = [tab for tab in tabs if not tab['terminal']]
        if len(tabs) > count:
            tabs = []
        return dict(tabs=tabs, registered=count)
    except (AttributeError, KeyError, OSError, TypeError, ValueError, subprocess.TimeoutExpired):
        return {}
