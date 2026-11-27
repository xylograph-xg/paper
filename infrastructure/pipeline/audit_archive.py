"""Runtime adapter; canonical implementation: maintenance.audit_archive."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.audit_archive',run_name='__main__')
else:
    from ._compat import bind
    bind('audit_archive')
