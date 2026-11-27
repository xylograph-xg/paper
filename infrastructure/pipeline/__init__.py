"""Runtime compatibility project; new consumers use subproject APIs."""
from ._compat import bind
def __getattr__(name):
    try:return bind(name)
    except KeyError:raise AttributeError(name) from None
