"""Runtime adapter; canonical implementation: maintenance.organize_ssd."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.organize_ssd',run_name='__main__')
else:
    from ._compat import bind
    bind('organize_ssd')
