"""Runtime adapter; canonical implementation: browser.owner_upload_jobs."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.owner_upload_jobs',run_name='__main__')
else:
    from ._compat import bind
    bind('owner_upload_jobs')
