"""Runtime adapter; canonical implementation: fetch.chemrxiv_enrichment."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.chemrxiv_enrichment',run_name='__main__')
else:
    from ._compat import bind
    bind('chemrxiv_enrichment')
