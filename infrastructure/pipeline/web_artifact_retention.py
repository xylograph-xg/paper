"""Runtime adapter; canonical implementation: maintenance.web_artifact_retention."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.web_artifact_retention',run_name='__main__')
else:
    from ._compat import bind
    bind('web_artifact_retention')
