"""Runtime adapter; canonical implementation: browser.shared_claim_recovery."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.shared_claim_recovery',run_name='__main__')
else:
    from ._compat import bind
    bind('shared_claim_recovery')
