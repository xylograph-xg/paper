"""Runtime adapter; canonical implementation: reading.source_media."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.source_media',run_name='__main__')
else:
    from ._compat import bind
    bind('source_media')
