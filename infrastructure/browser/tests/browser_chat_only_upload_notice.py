"""Exercise the captured Chinese storage dialog in an isolated browser."""
from playwright.sync_api import sync_playwright
from browser.shared_page_health import snapshot_page
from browser.web_card_transport import DeferredWeb, _dismiss_chat_only_notice

ZIP = 'a' * 64 + '.zip'
NOTICE = '文件仅添加到聊天'
DESCRIPTION = '剩余存储空间不足，无法保存此文件。请移除文件以腾出空间。'


def dialog(filename=ZIP, *, title=NOTICE, desc=DESCRIPTION, extra=''):
    return f"""
      <div role="dialog" aria-modal="true" aria-labelledby="title" aria-describedby="detail">
        <h2 id="title">{title}</h2><p id="detail">{desc}</p>
        <span>{filename}</span><button id="manage">管理存储空间</button>
        <button id="close"><span>关闭对话框</span></button>{extra}
      </div>
    """


def load(page, markup, *, composer_file=ZIP):
    page.set_content(f"""
      <main><form aria-hidden="true">
        <div id="prompt-textarea" contenteditable="true"></div>
        <div data-composer-attachments><button aria-label="移除 {composer_file}">x</button></div>
        <button id="send">发送</button>
      </form></main>
      {markup}
      <script>
        window.clicked = [];
        document.addEventListener('click', e => {{
          const button = e.target.closest('button');
          if (!button) return;
          clicked.push(button.id);
          if (button.id === 'close') {{
            button.closest('[role=dialog]').remove();
            document.querySelector('form').removeAttribute('aria-hidden');
          }}
        }});
      </script>
    """)


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    try:
        page = browser.new_page()
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        receipt = {'receipt_sufficient': True, 'bundle': {'zip_name': ZIP}}
        load(page, dialog())
        snapshot = snapshot_page('isolated-original', page)
        assert snapshot['attachments'] >= 1 and snapshot['attachment_names'] == [ZIP]
        assert _dismiss_chat_only_notice(page, receipt) is True
        assert page.evaluate('clicked') == ['close']
        assert page.locator('[data-composer-attachments] button').count() == 1
        assert _dismiss_chat_only_notice(page, receipt, already_dismissed=True) is False

        rejected = [
            (dialog('wrong.zip'), ZIP, receipt, False),
            (dialog(), 'wrong.zip', receipt, False),
            (dialog(), ZIP, {**receipt, 'receipt_sufficient': False}, False),
            (dialog(desc='上传额度已用完'), ZIP, receipt, False),
            (dialog() + dialog(), ZIP, receipt, False),
            (dialog() + '<div id="nocaptcha">验证</div>', ZIP, receipt, False),
            (dialog(), ZIP, receipt, True),
        ]
        for markup, filename, detail, dismissed in rejected:
            load(page, markup, composer_file=filename)
            try:
                _dismiss_chat_only_notice(page, detail, already_dismissed=dismissed)
            except DeferredWeb:
                assert page.evaluate('clicked') == []
                assert page.locator('[role=dialog]').count() >= 1
            else:
                raise AssertionError('Unbound notice was not blocked')
        load(page, dialog(title='上传文件已达上限'))
        assert _dismiss_chat_only_notice(page, receipt) is False
        assert page.evaluate('clicked') == []
        assert not requests
        print('PASS: exact settled ZIP, modal dismissal, hidden attachment protection, seven fail-closed variants and no network')
    finally:
        browser.close()
