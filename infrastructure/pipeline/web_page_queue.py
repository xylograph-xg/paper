"""Runtime adapter; canonical implementation: browser.web_page_queue."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.web_page_queue',run_name='__main__')
else:
    from ._compat import bind
    bind('web_page_queue')
