"""Runtime adapter; canonical implementation: correction.recover_saved_publication."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('correction.recover_saved_publication',run_name='__main__')
else:
    from ._compat import bind
    bind('recover_saved_publication')
