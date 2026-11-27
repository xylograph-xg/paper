"""Runtime adapter; canonical implementation: browser.page_retirement."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.page_retirement',run_name='__main__')
else:
    from ._compat import bind
    bind('page_retirement')
