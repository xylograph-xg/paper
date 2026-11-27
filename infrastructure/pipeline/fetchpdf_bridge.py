"""Runtime adapter; canonical implementation: fetch.fetchpdf_bridge."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.fetchpdf_bridge',run_name='__main__')
else:
    from ._compat import bind
    bind('fetchpdf_bridge')
