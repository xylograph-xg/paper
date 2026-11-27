"""Runtime adapter; canonical implementation: correction.card_correction_lane."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('correction.card_correction_lane',run_name='__main__')
else:
    from ._compat import bind
    bind('card_correction_lane')
