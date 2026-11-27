"""Runtime adapter; canonical implementation: browser.upload_quota."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.upload_quota',run_name='__main__')
else:
    from ._compat import bind
    bind('upload_quota')
