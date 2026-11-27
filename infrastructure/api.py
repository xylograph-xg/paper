"""Public gateways to existing shared components; no service startup."""
from importlib import import_module
_GATEWAYS={'core_api':'core.api','browser_api':'browser.api','maintenance_api':'maintenance.api','article_api':'article.api'}
__all__=list(_GATEWAYS)
def __getattr__(name):
    if name not in _GATEWAYS:raise AttributeError(name)
    return import_module(_GATEWAYS[name])
