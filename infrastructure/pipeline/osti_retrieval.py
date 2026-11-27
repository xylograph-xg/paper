"""Runtime adapter; canonical implementation: fetch.osti_retrieval."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.osti_retrieval',run_name='__main__')
else:
    from ._compat import bind
    bind('osti_retrieval')
