"""Runtime adapter; canonical implementation: fetch.acquisition_budget."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.acquisition_budget',run_name='__main__')
else:
    from ._compat import bind
    bind('acquisition_budget')
