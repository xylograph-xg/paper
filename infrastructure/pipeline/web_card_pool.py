"""Runtime adapter; canonical implementation: browser.web_card_pool."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.web_card_pool',run_name='__main__')
else:
    from ._compat import bind
    bind('web_card_pool')
