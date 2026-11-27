"""Runtime adapter; canonical implementation: maintenance.recovery_backup."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.recovery_backup',run_name='__main__')
else:
    from ._compat import bind
    bind('recovery_backup')
