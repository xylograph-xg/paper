"""Browser transport boundary; importing it never opens a browser."""
from .src.web_gpt_adapter import gpt_session, check_browser, import_root
__all__=['gpt_session','check_browser','import_root']


def open_browser(config=None):
    """Ask the existing sole owner; never independently open Chrome or CDP."""
    from core.api import catalog__load_config as load_config
    from browser.api import browser_start_request__request as request
    from browser.api import web_pool_open__request_shared as request_shared
    config=config or load_config()
    return {'startup':request(config,'cards'),'pool':request_shared(config,ensure_page=True)}
