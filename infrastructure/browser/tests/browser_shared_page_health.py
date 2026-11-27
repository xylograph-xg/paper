"""Disposable real-DOM health checks; no account, CDP attach or network."""
import hashlib
import json
import os
import tempfile
from core.api import paths__WorkspacePath as Path

from playwright.sync_api import sync_playwright
from browser.shared_page_health import classify, snapshot_page


def main():
    prompt = '只处理 web-card-11111111-1111-4111-8111-111111111111-input123；文献引用 Stopped thinking、分析已暂停。'
    with tempfile.TemporaryDirectory(prefix='paper-health-dom-') as folder, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.environ.get(
            'PAPER_TEST_CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        page = browser.new_page()
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        record_path = Path(folder) / 'attempt.json'
        (record_path.parent / 'prompt-actual.txt').write_text(prompt)
        record = {'target_id': 'synthetic-original', 'state': 'submitted', 'send_click_started': True,
                  'conversation_url': 'https://chatgpt.com/c/synthetic-original',
                  'actual_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                  '_ledger_path': str(record_path)}
        record_path.write_text(json.dumps(record))
        user = '<section data-talvt-turn-state="complete"><div data-message-author-role="user">' + prompt + '</div></section>'
        footer = '<footer role="alert">Stopped thinking · ChatGPT 可能会出错 · 回答已完成</footer>'
        sidebar = '<aside><div role="alert">Something went wrong: 无法加载历史记录</div></aside>'
        cases = []

        def read(content):
            page.set_content(content)
            snapshot = snapshot_page('synthetic-original', page)
            assert snapshot['inspection_complete'], snapshot
            return snapshot

        def stable(snapshot):
            # Receipt tests are pure synthetic data; set its synthetic formal URL.
            snapshot = {**snapshot, 'url': record['conversation_url'], 'checked_at': 100.0}
            first = classify(snapshot, {'state': 'needs_inspection'}, record, urls=[snapshot['url']])
            return classify({**snapshot, 'checked_at': 120.0}, {'state': 'needs_inspection'}, record,
                            urls=[snapshot['url']], previous=first)

        try:
            from web_gpt.core import find_prompt_box, _box_text
            for composer in (
                '<div id="prompt-textarea" style="display:none"></div><div id="prompt-textarea" contenteditable="true">protected draft</div>',
                '<div id="prompt-textarea" style="display:none"></div><div role="textbox" contenteditable="true">protected draft</div>',
                '<div contenteditable="true"><span style="display:none">protected draft</span><br></div>',
            ):
                snapshot = read('<main>' + composer + '</main>')
                assert snapshot['draft'] == _box_text(find_prompt_box(page)), snapshot
                assert 'protected draft' in snapshot['draft'], snapshot
                blank = {**snapshot, 'url': 'https://chatgpt.com/', 'checked_at': 100.0}
                health = classify(blank, {'state':'ready_blank','never_submitted':True}, None,
                                  record_paths=[])
                assert health['health'] == 'dirty' and not health['replace_allowed'], health
            cases.append('composer_matches_submission_and_protects_hidden_text')

            snapshot=read('<main><form><div id="prompt-textarea" contenteditable="true"></div><div role="progressbar" aria-label="上传中" style="width:40px;height:10px"></div></form></main>')
            assert snapshot['uploading'] is True, snapshot
            assert classify(snapshot,{'state':'needs_inspection'},None)['health']=='uploading'
            snapshot=read('<main><form><div id="prompt-textarea" contenteditable="true"></div><div role="progressbar" style="display:none"></div></form><aside><div role="progressbar" style="width:40px;height:10px"></div></aside></main>')
            assert snapshot['uploading'] is False,snapshot
            cases.append('actual_composer_upload_progress_protected')

            snapshot = read(sidebar + '<main>' + user + footer + '<div id="prompt-textarea"></div></main>')
            assert snapshot['user_turn_complete'] and not snapshot['terminal_complete'], snapshot
            assert not snapshot['terminal_stopped'] and snapshot['errors'] == [], snapshot
            assert not stable(snapshot)['replace_allowed'], snapshot
            cases.append('user_quote_sidebar_footer_protected')

            previous = '<section data-talvt-turn-state="complete"><h4 data-conversation-role="assistant"></h4><div role="status">Stopped thinking</div><div role="alert">Something went wrong</div></section>'
            snapshot = read('<main>' + previous + user + '<div id="prompt-textarea"></div></main>')
            assert not snapshot['terminal_stopped'] and snapshot['errors'] == [], snapshot
            assert not stable(snapshot)['replace_allowed'], snapshot
            cases.append('previous_assistant_status_is_not_current')

            assistant = '<section data-talvt-turn-state="complete"><h4 data-conversation-role="assistant">ChatGPT 说：</h4><div role="status">Stopped thinking</div></section>'
            snapshot = read('<main>' + user + assistant + '<div id="prompt-textarea"></div></main>')
            assert snapshot['terminal_complete'] and snapshot['terminal_stopped'], snapshot
            assert snapshot['answer_texts'] == [], snapshot
            assert stable(snapshot)['health'] == 'terminal_empty', snapshot
            cases.append('explicit_empty_assistant_h4_terminal')

            for label in ('分析已暂停','已暂停思考','Analysis paused'):
                paused='<section data-talvt-turn-state="in_progress"><h4 data-conversation-role="assistant"></h4><button>'+label+'</button></section>'
                snapshot=read('<main>'+user+paused+'<div id="prompt-textarea"></div></main>')
                assert snapshot['terminal_stopped'] and not snapshot['terminal_complete'],snapshot
                assert snapshot['streaming'] is False and snapshot['answer_texts']==[],snapshot
                current={**snapshot,'url':record['conversation_url'],'checked_at':100.0}
                health=classify(current,{'state':'busy'},record,urls=[current['url']])
                assert health['health']=='terminal_empty' and not health['replace_allowed'],health
            cases.append('explicit_current_analysis_paused_uses_empty_terminal_guard')

            activity='<div class="group/activity-header"><span aria-live="polite">分析已暂停</span></div>'
            actual_user='<h4 class="sr-only">你说：</h4><div data-chatgpt-search-unit-key="fallback-turn-0:0:user">'+prompt+'</div>'
            combined='<div data-talvt-turn-state="in_progress">'+actual_user+activity+'</div>'
            snapshot=read('<main>'+combined+'<div id="prompt-textarea"></div></main>')
            assert snapshot['terminal_stopped'] and not snapshot['terminal_complete'],snapshot
            current={**snapshot,'url':record['conversation_url'],'checked_at':100.0}
            health=classify(current,{'state':'busy'},record,urls=[current['url']])
            assert health['health']=='terminal_empty' and not health['replace_allowed'],health
            for protected in (
                '<div data-talvt-turn-state="in_progress"><div data-chatgpt-search-unit-key="fallback-turn-0:0:user">'+activity+'</div></div>',
                combined+user,
                user+'<aside>'+activity+'</aside>',
                '<div data-talvt-turn-state="in_progress">'+actual_user+'<span aria-live="polite">分析已暂停</span></div>',
            ):
                snapshot=read('<main>'+protected+'<div id="prompt-textarea"></div></main>')
                assert not snapshot['terminal_stopped'],snapshot
            cases.append('roleless_current_activity_header_without_user_or_history_matches')

            def transcript(*turns):
                return ('<main><div data-thread-find-target="conversation">' +
                        ''.join(f'<div data-turn-key="{i}">{turn}</div>' for i, turn in enumerate(turns)) +
                        '</div><div id="prompt-textarea"></div></main>')

            for message in ('消息传输超时。请重试。', '消息流中的错误'):
                alert = f'<aside role="alert" class="text-danger"><div>{message}</div><button>重试</button></aside>'
                snapshot = read(transcript(actual_user + alert))
                assert snapshot['terminal_stream_error'].startswith(message), snapshot
                current = {**snapshot, 'url': record['conversation_url'], 'checked_at': 100.0}
                busy = {'state': 'busy'}
                health = classify(current, busy, record, urls=[current['url']])
                assert health['health'] == 'terminal_empty' and not health['replace_allowed'], health
                for protected in (
                    {**current, 'streaming': True},
                    {**current, 'uploading': True},
                    {**current, 'draft': 'new draft'},
                    {**current, 'answer_texts': ['incomplete answer']},
                    {**current, 'user_texts': ['different request']},
                ):
                    assert classify(protected, busy, record, urls=[current['url']])['health'] == 'busy'
                assert classify(current, {**busy, 'submission_unknown': True}, record,
                                urls=[current['url']])['health'] == 'busy'
                assert classify(current, busy, record, urls=[current['url']] * 2)['health'] == 'busy'
                for protected in (
                    transcript(alert, actual_user),
                    transcript('<aside>' + alert + '</aside>' + actual_user),
                    transcript(actual_user.replace(prompt, prompt + alert)),
                    transcript(actual_user + '<div data-message-author-role="assistant">' + alert + '</div>'),
                    transcript(actual_user + '<div hidden>' + alert + '</div>'),
                ):
                    assert not read(protected)['terminal_stream_error']
            cases.append('native_current_stream_error_uses_empty_terminal_guard')

            empty_assistant = '<section data-talvt-turn-state="complete"><div data-message-author-role="assistant"></div></section>'
            snapshot = read('<main>' + user + empty_assistant + '<div id="prompt-textarea"></div></main>')
            assert snapshot['terminal_complete'] and snapshot['answer_element_count'] == 1, snapshot
            assert snapshot['answer_texts'] == [], snapshot
            assert page.locator('div[data-message-author-role="assistant"]:visible').count() == 0
            assert stable(snapshot)['health'] == 'terminal_empty', snapshot
            cases.append('zero_height_empty_assistant_is_not_a_reply')

            whitespace_assistant = '<section data-talvt-turn-state="complete"><div data-message-author-role="assistant" style="width:100px;height:20px;white-space:pre"> \n\t</div></section>'
            snapshot = read('<main>' + user + whitespace_assistant + '<div id="prompt-textarea"></div></main>')
            assert snapshot['terminal_complete'] and snapshot['answer_element_count'] == 1, snapshot
            assert snapshot['answer_texts'] == [], snapshot
            assert page.locator('div[data-message-author-role="assistant"]:visible').count() == 1
            assert stable(snapshot)['health'] == 'terminal_empty', snapshot
            cases.append('visible_whitespace_assistant_is_not_a_reply')

            system = '<section data-talvt-turn-state="complete" data-message-author-role="system"><div role="status">Stopped generating</div></section>'
            snapshot = read('<main>' + user + system + '<div id="prompt-textarea"></div></main>')
            assert snapshot['terminal_stopped'] and not snapshot['terminal_complete'], snapshot
            assert stable(snapshot)['health'] == 'terminal_no_response', snapshot
            cases.append('explicit_current_system_stop')

            snapshot = read('<main>' + user + '<section data-talvt-turn-state="complete"><h4 data-conversation-role="assistant"></h4><div role="alert">Something went wrong</div></section>' + footer + '</main>')
            assert snapshot['errors'] == ['Something went wrong'], snapshot
            assert stable(snapshot)['health']=='terminal_empty',snapshot
            assert not stable(snapshot)['replace_allowed'],snapshot
            cases.append('current_assistant_error_retained')

            snapshot = read('<div id="main-frame-error">net::ERR_SSL_PROTOCOL_ERROR</div>')
            assert snapshot['errors'] == ['net::ERR_SSL_PROTOCOL_ERROR'], snapshot
            cases.append('chrome_frame_error_retained')

            # Real DOM fixtures, including portal menus outside main. No live
            # account/profile and no upload, navigation or external request.
            science = '<section data-talvt-turn-state="complete"><div data-message-author-role="assistant">PLQY达到性能上限；TT人口30%限制。There are too many files in the research dataset. Quota is a scientific parameter.</div></section>'
            snapshot = read('<main>' + user + science + '<div id="prompt-textarea"></div></main>')
            assert not snapshot['quota'] and not snapshot['quota_notice'], snapshot
            cases.append('scientific_limit_and_too_many_words_are_not_quota')

            excluded_notices = {
                'user': '<div data-message-author-role="user"><div role="alert">Upload limit reached. Try again at 23:45.</div></div>',
                'assistant': '<div data-message-author-role="assistant"><div role="alert">附件上传已达到上限。请于23:45重试。</div></div>',
                'sidebar': '<aside><div data-testid="toast">Upload limit reached.</div></aside>',
                'hidden_attribute': '<div role="alert" hidden>Upload limit reached.</div>',
                'hidden_ancestor': '<div hidden><div role="dialog">Upload limit reached.</div></div>',
                'aria_hidden_ancestor': '<div aria-hidden="true"><div role="alert">Upload limit reached.</div></div>',
                'display_none': '<div role="alert" style="display:none">Upload limit reached.</div>',
                'visibility_hidden': '<div role="status" style="visibility:hidden">Upload limit reached.</div>',
                'draft': '<div id="prompt-textarea" role="status">Upload limit reached.</div>',
                'conversation_wrapper': '<div role="dialog">' + science + '</div>',
                'old_system_turn': '<section data-talvt-turn-state="complete" data-message-author-role="system"><div role="status">You have reached your GPT-6 limit.</div></section>' + user,
            }
            for name, content in excluded_notices.items():
                snapshot = read('<main>' + content + '</main>')
                assert not snapshot['quota'] and not snapshot['quota_notices'], (name, snapshot)
                cases.append(name + '_quota_text_excluded')

            notices = {
                'portal_upload_menu': '<div data-radix-popper-content-wrapper><div role="menu">文件附件数量限制。请于10月9日 23:45后重试。</div></div>',
                'visible_alert': '<div role="alert">Upload limit reached. Try again at 23:45.</div>',
                'visible_dialog': '<div role="dialog">You have reached your GPT-6 limit. Try again later.</div>',
                'visible_toast': '<div data-testid="toast">Too many files uploaded. Try again later.</div>',
                'current_system_turn': '<section data-talvt-turn-state="complete" data-message-author-role="system">您已达到GPT-6使用上限，请稍后重试。</section>',
            }
            for name, content in notices.items():
                snapshot = read('<main>' + user + '<div id="prompt-textarea"></div></main>' + content)
                assert snapshot['quota'] and snapshot['quota_notice'], (name, snapshot)
                assert all(n['source'] in ('visible_notice_ui', 'current_system_turn') for n in snapshot['quota_notices'])
                result = stable(snapshot)
                assert result['health'] == 'quota' and not result['replace_allowed'] and not result['requeue_allowed'], result
                if name == 'portal_upload_menu':
                    assert '23:45' in result['evidence']['quota_notice'], result
                cases.append(name + '_quota_preserved')

            snapshot = read('<div role="status">There are too many scientific energy levels.</div>')
            assert not snapshot['quota'], snapshot
            cases.append('generic_too_many_notice_is_not_a_file_or_request_limit')
            assert not requests, requests
            print(json.dumps({'state': 'pass', 'cases': cases, 'network_requests': len(requests),
                              'playwright_visible_selector_handled': True}, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
