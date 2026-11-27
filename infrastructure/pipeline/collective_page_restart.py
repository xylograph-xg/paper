"""Runtime adapter; canonical implementation: browser.collective_page_restart."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.collective_page_restart',run_name='__main__')
else:
    from ._compat import bind
    bind('collective_page_restart')
