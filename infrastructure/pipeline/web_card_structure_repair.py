"""Runtime adapter; canonical implementation: cards.web_card_structure_repair."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('cards.web_card_structure_repair',run_name='__main__')
else:
    from ._compat import bind
    bind('web_card_structure_repair')
