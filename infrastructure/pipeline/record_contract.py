"""Runtime adapter; canonical implementation: core.record_contract."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.record_contract',run_name='__main__')
else:
    from ._compat import bind
    bind('record_contract')
