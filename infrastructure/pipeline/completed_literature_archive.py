"""Runtime adapter; canonical implementation: reading.completed_literature_archive."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.completed_literature_archive',run_name='__main__')
else:
    from ._compat import bind
    bind('completed_literature_archive')
