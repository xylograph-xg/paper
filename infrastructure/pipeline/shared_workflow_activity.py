"""Runtime adapter; canonical implementation: browser.shared_workflow_activity."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.shared_workflow_activity',run_name='__main__')
else:
    from ._compat import bind
    bind('shared_workflow_activity')
