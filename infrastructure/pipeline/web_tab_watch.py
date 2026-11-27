"""Runtime adapter; canonical implementation: maintenance.web_tab_watch."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.web_tab_watch',run_name='__main__')
else:
    from ._compat import bind
    bind('web_tab_watch')
