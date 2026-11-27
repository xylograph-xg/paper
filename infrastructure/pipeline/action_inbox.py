"""Runtime adapter; canonical implementation: core.action_inbox."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.action_inbox',run_name='__main__')
else:
    from ._compat import bind
    bind('action_inbox')
