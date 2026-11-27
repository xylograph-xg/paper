"""Runtime adapter; canonical implementation: browser.web_upload_bundle."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.web_upload_bundle',run_name='__main__')
else:
    from ._compat import bind
    bind('web_upload_bundle')
