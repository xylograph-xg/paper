"""Isolated DOM regression; no account, network or existing browser connection."""
from playwright.sync_api import sync_playwright
from web_gpt.core import find_prompt_box, _box_text
from browser.shared_page_health import snapshot_page
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    page=browser.new_page();requests=[];page.on('request',lambda r: requests.append(r.url))
    cases=[
        '<div aria-hidden="true"><div id="prompt-textarea" contenteditable="true">protected draft</div></div>',
        '<div inert><div id="prompt-textarea" contenteditable="true">protected draft</div></div>',
        '<textarea>protected draft</textarea><div contenteditable="true"></div>',
        '<input type="text" value="protected draft"><div contenteditable="true"></div>',
        '<div style="display:none"><div id="prompt-textarea">hidden stale</div></div><textarea>protected draft</textarea>',
    ]
    for content in cases:
        page.set_content(content)
        observed=snapshot_page('synthetic',page)['draft']; expected=_box_text(find_prompt_box(page))
        assert observed==expected=='protected draft',(observed,expected)
    assert not requests
    print('PASS: 5 submission/health composer cases; zero network requests')
    browser.close()
