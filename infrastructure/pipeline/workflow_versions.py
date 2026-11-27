"""Runtime adapter; canonical implementation: core.workflow_versions."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.workflow_versions',run_name='__main__')
else:
    from ._compat import bind
    bind('workflow_versions')
