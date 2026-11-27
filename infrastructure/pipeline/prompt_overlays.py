"""Runtime adapter; canonical implementation: reading.prompt_overlays."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.prompt_overlays',run_name='__main__')
else:
    from ._compat import bind
    bind('prompt_overlays')
