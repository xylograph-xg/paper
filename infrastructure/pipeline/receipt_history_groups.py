"""Runtime adapter; canonical implementation: browser.receipt_history_groups."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.receipt_history_groups',run_name='__main__')
else:
    from ._compat import bind
    bind('receipt_history_groups')
