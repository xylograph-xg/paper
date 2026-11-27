"""Runtime adapter; canonical implementation: review.review_tabs."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('review.review_tabs',run_name='__main__')
else:
    from ._compat import bind
    bind('review_tabs')
