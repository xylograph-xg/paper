"""Compatibility entry for installed panels and the original browser owner."""
from oled_formulas.api import control_pilot, enabled, run


if __name__ == '__main__':
    from runpy import run_module
    run_module('oled_formulas', run_name='__main__')
