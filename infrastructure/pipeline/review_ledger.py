"""Runtime adapter; canonical implementation: review.review_ledger."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('review.review_ledger',run_name='__main__')
else:
    from ._compat import bind
    bind('review_ledger')
