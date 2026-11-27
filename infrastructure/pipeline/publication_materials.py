"""Runtime adapter; canonical implementation: cards.publication_materials."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('cards.publication_materials',run_name='__main__')
else:
    from ._compat import bind
    bind('publication_materials')
