from playwright.sync_api import sync_playwright
from browser.shared_page_health import snapshot_page
with sync_playwright() as pw:
 b=pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');p=b.new_page();p.set_content('<div data-composer-body><div data-composer-attachments><button aria-label="移除 original.zip" style="opacity:0">x</button></div><div><div><div role="textbox" contenteditable="true"><p><br></p></div></div></div></div>');s=snapshot_page('owned',p);assert s['attachments']==1 and s['attachment_names']==['original.zip'];assert not s['draft'].strip();print('PASS: modern hidden-opacity remove button and outer composer attachment detected');b.close()
