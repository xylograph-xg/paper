"""Runtime adapter; canonical implementation: workbench.tailscale_access."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('workbench.tailscale_access',run_name='__main__')
else:
    from ._compat import bind
    bind('tailscale_access')
