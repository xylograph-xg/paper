import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_widget.app_windows import log_tail, observed_tabs


def event(name, stamp, tab=None, trace=None, **detail):
    if tab:
        detail['tabId'] = tab
    if trace:
        detail['traceId'] = trace
    return dict(event=name, at=f'1970-01-01T00:00:{stamp:02d}Z', detail=detail)


def runtime(stamp, line):
    return event('runtime.daemon_stdout', stamp, line=line)


class AppWindows(unittest.TestCase):
    def test_interleaved_stages_reuse_and_expired_evidence(self):
        events = [event('browser.tab_created', 1, 'a', 'first'),
                  event('browser.tab_created', 2, 'b', 'other'),
                  runtime(3, 'browser turn first stage=file_attachment started'),
                  runtime(3, 'broker trace=other queued call=call_b tool=view_image'),
                  runtime(4, 'broker trace=other delivered call=call_b path=waiter'),
                  event('browser.turn_heartbeat', 5, trace='first')]
        sample = lambda now: {t['id']: t['state'] for t in observed_tabs(events, 0, now)}
        self.assertEqual(sample(6), {'a': '上传附件', 'b': '执行工具'})
        self.assertEqual(sample(65), {'a': '上传附件', 'b': '待观测'})
        events.extend([event('browser.tab_reused', 8, 'a', 'next'),
                       event('browser.tab_released', 9, 'a', 'first'),
                       runtime(10, 'broker trace=other completed call=call_b pending=0'),
                       event('browser.turn_authentication_blocked', 11, 'a', 'next')])
        self.assertEqual(sample(12), {'a': '等待登录', 'b': '等待回答'})
        self.assertEqual(observed_tabs(events, 12, 13), [])

    def test_sustained_heartbeat_does_not_refresh_generation_or_authorization_evidence(self):
        events = [event('browser.tab_created', 1, 'a', 'one'),
                  runtime(2, 'browser turn one submission accepted evidence=generation_running'),
                  event('browser.turn_heartbeat', 30, trace='one')]
        self.assertEqual(observed_tabs(events, 0, 6)[0]['state'], '已观测到生成')
        self.assertEqual(observed_tabs(events, 0, 31)[0]['state'], '已发送，等待回答')
        events.append(event('browser.tool_approval', 33, trace='one', pending=True))
        self.assertEqual(observed_tabs(events, 0, 35)[0]['state'], '等待工具批准')
        events.append(event('browser.tab_released', 38, 'a', 'one'))
        self.assertEqual(observed_tabs(events, 0, 39), [])

    def test_completion_reclamation_and_partial_rotated_log(self):
        events = [event('browser.tab_created', 1, 'a', 'one'),
                  event('browser.tab_completed', 2, 'a', 'one')]
        self.assertEqual(observed_tabs(events, 0, 4)[0]['state'], '任务已完成')
        events.append(event('browser.tab_created', 4, 'b', 'two', tabCount=5))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'launcher.jsonl'
            path.with_suffix('.jsonl.1').write_text('bad\n' + json.dumps(events[0]) + '\n')
            path.write_text('\n'.join(json.dumps(e) for e in events[1:]) + '\n{"partial')
            tabs = observed_tabs(log_tail(path), 0, 5)
            self.assertEqual([t['id'] for t in tabs], ['b'])
            with patch('desktop_widget.app_windows.LOG_TAIL', 4):
                self.assertEqual(list(log_tail(path)), [])
