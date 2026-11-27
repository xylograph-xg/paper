"""Runtime adapter; canonical implementation: review.card_evaluation."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('review.card_evaluation',run_name='__main__')
else:
    from ._compat import bind
    bind('card_evaluation')
