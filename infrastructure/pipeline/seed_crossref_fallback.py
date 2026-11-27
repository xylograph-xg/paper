"""Runtime adapter; canonical implementation: fetch.seed_crossref_fallback."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.seed_crossref_fallback',run_name='__main__')
else:
    from ._compat import bind
    bind('seed_crossref_fallback')
