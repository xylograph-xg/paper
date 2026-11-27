"""Runtime adapter; canonical implementation: reading.card_display."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.card_display',run_name='__main__')
else:
    from ._compat import bind
    bind('card_display')
