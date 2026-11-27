"""Minimal MIT Paperscraper extraction, avoiding its unrelated model dependencies.
Source: jannisborn/paperscraper cf33b8328c6e7cc296d40e4c09d03095fcba4a61
paperscraper/pdf/pdf.py::_chemrxiv_pdf_url. License beside this file.
"""

def pdf_url(item):
    asset = item.get('asset')
    if not isinstance(asset, dict):
        return None
    original = asset.get('original')
    if isinstance(original, dict) and original.get('url'):
        return original.get('url')
    return asset.get('url')
