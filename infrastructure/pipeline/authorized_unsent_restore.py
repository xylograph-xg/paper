"""Runtime adapter; canonical implementation: browser.authorized_unsent_restore."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.authorized_unsent_restore',run_name='__main__')
else:
    from ._compat import bind
    bind('authorized_unsent_restore')
