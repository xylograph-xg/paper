"""Runtime adapter; canonical implementation: reading.manual_literature."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.manual_literature',run_name='__main__')
else:
    from ._compat import bind
    bind('manual_literature')
