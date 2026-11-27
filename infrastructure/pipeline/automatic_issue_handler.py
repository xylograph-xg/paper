"""Runtime adapter; canonical implementation: core.automatic_issue_handler."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.automatic_issue_handler',run_name='__main__')
else:
    from ._compat import bind
    bind('automatic_issue_handler')
