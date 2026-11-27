"""Runtime adapter; canonical implementation: browser.restored_web_draft."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.restored_web_draft',run_name='__main__')
else:
    from ._compat import bind
    bind('restored_web_draft')
