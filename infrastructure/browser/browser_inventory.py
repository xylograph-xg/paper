"""Observe CDP pages without creating/closing tabs; tolerate closing-page races."""
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

# A Playwright Page is bound to one target for its lifetime. Values hold only
# primitive identities, never a context/page reference that could retain keys.
_TARGET_IDS = WeakKeyDictionary()
from .owner_browser_calls import bounded_call


def enumerate_pages(browser,hosts=None):
    pages={};errors=[];total=0
    connected=getattr(browser,'is_connected',None)
    if callable(connected) and connected() is False:
        return {'pages':{},'total_pages':0,'errors':['原浏览器连接已断开'],'complete':False}
    for context in browser.contexts:
        try:observed=list(context.pages)
        except Exception as exc:
            errors.append('页面列表不可读：'+str(exc)[:200]);continue
        total+=len(observed)
        for page in observed:
            session=None;target=None;detached=False
            try:
                if page.is_closed():continue
                if hosts is not None and urlsplit(page.url).hostname not in hosts:continue
                try:cached=_TARGET_IDS.get(page)
                except TypeError:cached=None
                if cached and cached[:2]==(id(browser),id(context)):
                    target=cached[2]
                else:
                    session=bounded_call(context,'new_cdp_session',page,timeout=3)
                    target=bounded_call(session,'send','Target.getTargetInfo',timeout=3)['targetInfo']['targetId']
                if not isinstance(target,str) or not target:raise ValueError('缺少原页面target_id')
                if target in pages:raise ValueError('重复页面target_id')
                pages[target]=page
            except Exception as exc:errors.append('单页核对失败：'+str(exc)[:200])
            finally:
                if session is not None:
                    try:bounded_call(session,'detach',timeout=2);detached=True
                    except Exception as exc:errors.append('单页连接释放失败：'+str(exc)[:200])
                if isinstance(target,str) and target and detached:
                    try:_TARGET_IDS[page]=(id(browser),id(context),target)
                    except TypeError:pass
    return {'pages':pages,'total_pages':total,'errors':errors,'complete':not errors}
