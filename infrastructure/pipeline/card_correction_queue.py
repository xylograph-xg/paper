"""Runtime adapter; canonical implementation: correction.card_correction_queue."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('correction.card_correction_queue',run_name='__main__')
else:
    from ._compat import bind
    bind('card_correction_queue')
