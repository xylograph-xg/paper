"""Runtime adapter; canonical implementation: browser.gpt_model_policy."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.gpt_model_policy',run_name='__main__')
else:
    from ._compat import bind
    bind('gpt_model_policy')
