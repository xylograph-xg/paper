"""Runtime adapter; canonical implementation: reading.batch_import."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.batch_import',run_name='__main__')
else:
    from ._compat import bind
    bind('batch_import')
