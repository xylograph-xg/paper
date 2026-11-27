"""Isolated real Chrome input check; no production CDP or external request."""
import re
from playwright.sync_api import sync_playwright
from browser.web_editor_input import replace
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    try:
        context=browser.new_context();page=context.new_page()
        page.set_content('<div id="editor" contenteditable="true">restored draft</div><button id="send" disabled>send</button><script>document.querySelector("#editor").addEventListener("input",()=>document.querySelector("#send").disabled=!document.querySelector("#editor").innerText.trim())</script>')
        another=context.new_page();another.set_content('<p>Other page preserved</p>')
        box=page.locator('#editor');text='中文公式 α = 1\n条件 x > 0\n\n结论'
        replace(box,text)
        assert re.sub(r'\s+','',box.inner_text())==re.sub(r'\s+','',text)
        assert page.locator('#send').is_enabled()
        assert another.locator('p').inner_text()=='Other page preserved'
        replace(box,'')
        assert not box.text_content().strip()
        assert not page.locator('#send').is_enabled()
        print('Real Chrome background multiline input, send readiness and clearing passed')
    finally:browser.close()
