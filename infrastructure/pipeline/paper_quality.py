"""Runtime adapter; canonical implementation: cards.paper_quality."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('cards.paper_quality',run_name='__main__')
else:
    from ._compat import bind
    bind('paper_quality')
