"""Isolated genuine ProseMirror DOM; fixture bundle is an explicit local artifact."""
import os,re
from core.api import paths__WorkspacePath as Path
from playwright.sync_api import sync_playwright
from browser.web_editor_input import replace
from web_gpt.core import _box_text
bundle=Path(os.environ.get('PAPER_EDITOR_TEST_BUNDLE','data/editor-diagnostic-runtime/bundle.js'))
if not bundle.is_file():raise RuntimeError('Build the isolated ProseMirror fixture bundle before this test')
dense=lambda t:re.sub(r'\s+','',t)
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    context=browser.new_context();page=context.new_page();requests=[];page.on('request',lambda r:requests.append(r.url))
    page.set_content('<div id="host"></div><input id="other-field" value="preserved">')
    page.add_script_tag(path=str(bundle));box=page.locator('[contenteditable=true]')
    other=context.new_page();other.set_content('<p>Other page preserved</p>')
    # The real site's handler may prevent synthetic paste without committing
    # any text. Background input must work even with such an interception.
    box.evaluate("el=>el.addEventListener('paste',e=>{e.preventDefault();e.stopImmediatePropagation()},true)")
    # Reproduce the archived symptom at the input boundary: the text-input
    # handler accepts only the first paragraph of a multiline insertion.
    box.evaluate("""el => el.addEventListener('beforeinput', event => {
      if (event.inputType !== 'insertText' || !event.data?.includes('\\n')) return;
      event.preventDefault();
      document.execCommand('insertText', false, event.data.split('\\n')[0]);
    })""")
    box.focus()
    session=context.new_cdp_session(page)
    session.send('Input.insertText',{'text':'首行\n被截断的后文'})
    page.wait_for_timeout(150)
    assert _box_text(box)=='首行'
    session.detach()
    page.locator('#other-field').focus()
    prompts=['中文公式 α = 1\n条件 x > 0\n\n结论', '\n'.join('第%d段，符号 γ、δ，JSON \\n，公式 x_i = 1/2，原文 <script> & 证据。'%i for i in range(221)), '再次替换\n新材料']
    for text in prompts:
        replace(box,text);page.wait_for_timeout(100)
        assert dense(_box_text(box))==dense(text)
        assert dense(page.evaluate('view.state.doc.textContent'))==dense(text)
        assert page.evaluate("view.state.doc.textBetween(0, view.state.doc.content.size, '\\n')")==text
        assert page.evaluate("document.activeElement.id")=='other-field'
        assert page.locator('#other-field').input_value()=='preserved'
        assert not box.locator('script').count()
        assert other.locator('p').inner_text()=='Other page preserved'
    replace(box,'');assert not _box_text(box).strip();assert page.evaluate('view.state.doc.textContent')==''
    assert not requests
    print('PASS: genuine ProseMirror multi-paragraph Unicode, repeat replacement, clearing; model/DOM agreement; no network or other page changes')
    browser.close()
