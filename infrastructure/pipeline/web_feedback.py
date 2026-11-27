"""Runtime adapter; canonical implementation: review.web_feedback."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('review.web_feedback',run_name='__main__')
else:
    from ._compat import bind
    bind('web_feedback')
