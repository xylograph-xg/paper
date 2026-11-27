"""Runtime adapter; canonical implementation: fetch.manual_seed_lineage."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.manual_seed_lineage',run_name='__main__')
else:
    from ._compat import bind
    bind('manual_seed_lineage')
