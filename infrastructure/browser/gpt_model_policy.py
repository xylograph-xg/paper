"""Main-paper GPT model order; verify exact native model and High before send."""
import re,time
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from core.api import control__read_record as read_record, control__mutate_record as mutate_record

PRIMARY='GPT-6'
FALLBACK='GPT-5.6 Sol'

def model_quota(text):
    return (bool(re.search(r'GPT[- ]?6',text,re.I)) and
            bool(re.search(r'limit|quota|上限|限额|次数.*(?:用完|限制)|达到.*限制',text,re.I)) and
            not bool(re.search(r'附件|文件|attachment|file upload',text,re.I)))

def verify_picker_mode(page,picker,temporary_home):
    from web_gpt.settings import _chat, _verify_mode
    if not temporary_home or page.url!='https://chatgpt.com/?temporary-chat=true' or _chat(page).count():
        return _verify_mode(page,picker,15000)
    from playwright.sync_api import expect
    # Work and Chat use different accessible names on their native menus.
    menu=picker.locator('xpath=ancestor-or-self::*[@role="menu"][1]')
    expect(menu).to_have_accessible_name(re.compile(r'^(思考强度|Thinking effort|选择 ChatGPT 模型|Select ChatGPT model)$',re.I))


def verify(page,model, *, temporary_home=False):
    from web_gpt.settings import _picker,_verify_mode,_selected_model,_effort,HIGH
    with _picker(page) as picker:
        verify_picker_mode(page,picker,temporary_home)
        state={'mode':'chat','model':_selected_model(picker),'effort':_effort(picker)}
        if state['model']!=model or state['effort'] not in HIGH:raise RuntimeError('模型/强度不符，禁止发送：'+str(state))
    return state

def select_high(page,picker, *, fallback=True):
    from web_gpt.settings import _panel, _choose_high
    from web_gpt.settings import _effort as _read_effort, HIGH as _HIGH
    if _read_effort(picker) not in _HIGH:
        # Current menus expose effort as radio items; the old slider can
        # report aria-valuenow without changing on keyboard input.
        for label in (('High','高','Extended','扩展') if fallback else ('High','高')):
            option=picker.get_by_role('menuitemradio',name=re.compile(r'^'+re.escape(label)+r'$',re.I))
            try:
                if option.count()==1 and option.is_visible():
                    option.evaluate('(el)=>el.click()');break
            except Exception:
                continue
    if _read_effort(picker) not in _HIGH and getattr(page, '_web_gpt_background', False):
        row = _panel(picker).locator('[data-reasoning-slider=true][aria-keyshortcuts]')
        if row.count() == 1 and row.is_visible():
            slider = row.locator('[role=slider]')
            for _ in range(6):
                if _read_effort(picker) in _HIGH:
                    break
                previous = slider.get_attribute('aria-valuenow')
                current = _read_effort(picker)
                direction = 'ArrowLeft' if current.casefold() in ('x-high','extra high','极高','超高') else 'ArrowRight'
                bound = 'aria-valuemin' if direction=='ArrowLeft' else 'aria-valuemax'
                if previous == slider.get_attribute(bound):
                    break
                row.dispatch_event('keydown', dict(key=direction, code=direction, bubbles=True))
                row.dispatch_event('keyup', dict(key=direction, code=direction, bubbles=True))
                if slider.get_attribute('aria-valuenow') == previous:
                    break
    if fallback and _read_effort(picker) not in _HIGH:
        _choose_high(picker,15000)

def set_composer_high(page, guard):
    """Change only the native effort control on an owned empty composer."""
    from web_gpt.settings import _picker, _effort, HIGH
    guard()
    with _picker(page,timeout=3500) as menu:
        guard()
        select_high(page,menu,fallback=False)
        if _effort(menu) not in HIGH:
            raise ValueError('网页强度菜单未选中 High')


def configure(page,model, *, fallback=True,temporary_home=False):
    from web_gpt.settings import _chat,_picker,_panel,_verify_mode,_selected_model,_choose_high
    from playwright.sync_api import expect
    chat=_chat(page)
    if chat.count():
        attribute='aria-pressed' if chat.get_attribute('aria-pressed') is not None else 'aria-checked'
        if chat.get_attribute(attribute)!='true':
            # Menus/transient navigation can disable the home mode switch.
            # Never bypass disabled controls or accept Work as Chat.
            page.evaluate('document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",code:"Escape",bubbles:true}))')
            expect(chat).to_be_enabled(timeout=15000)
            chat.evaluate('(el)=>el.click()')
        expect(chat).to_have_attribute(attribute,'true',timeout=15000)
    with _picker(page) as picker:
        verify_picker_mode(page,picker,temporary_home);panel=_panel(picker,advanced=True)
        if panel.get_attribute('data-active')!='true':picker.get_by_role('menuitem',name=re.compile(r'^(选择模型|Choose model|Select model)$',re.I)).evaluate('(el)=>el.click()')
        expect(panel).to_have_attribute('data-active','true',timeout=15000)
        target=panel.get_by_role('menuitemradio',name=model,exact=True)
        try:
            expect(target).to_be_visible(timeout=10000)
        except AssertionError as exc:
            labels = panel.get_by_role('menuitemradio').all_inner_texts()
            if labels:
                raise RuntimeError(f'网页模型列表中找不到 {model}。可见选项为 ' + '、'.join(labels)) from exc
            raise
        if target.get_attribute('aria-disabled')=='true':raise RuntimeError('模型不可用：'+target.inner_text())
        target.evaluate('(el)=>el.click()')
    with _picker(page) as picker:
        if _selected_model(picker)!=model:raise RuntimeError('模型选择未生效，禁止发送')
        select_high(page,picker,fallback=fallback)
    return verify(page,model,temporary_home=True) if temporary_home else verify(page,model)

def configure_session(page,root):
    path=Path(root)/'gpt-model-control.json';record=read_record(path)
    model=FALLBACK if record.get('primary_quota',{}).get('next_probe_after',0)>time.time() else PRIMARY
    try:state=configure(page,model)
    except Exception as exc:
        text=str(exc)+' '+page.locator('body').inner_text(timeout=3000)[-5000:]
        if model!=PRIMARY or not model_quota(text):raise
        # Only a visible, explicitly model-specific limit allows the fallback.
        mutate_record(path,{'primary_quota':{'observed':time.time(),'evidence':text[:2000],'next_probe_after':time.time()+900,'probe_is_cooldown_not_website_reset':True}},event='gpt6_model_quota')
        model=FALLBACK;state=configure(page,model)
    mutate_record(path,{'preferred_model':PRIMARY,'fallback_model':FALLBACK,'effort':'High','last_verified':state,'updated':time.time()},event='gpt_model_verified')
    session=SimpleNamespace(page=page,_pending_answer=None,settings=state,verify_settings=lambda:verify(page,model))
    return session
