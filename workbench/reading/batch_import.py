"""Conservative identity matching for unbound PDF uploads."""
import re
from core.api import catalog__doi as doi, catalog__title_key as title_key
from core.api import services__validate_pdf as validate_pdf


def match_pdf(path,papers):
    text=validate_pdf(path)
    found={doi(x.rstrip('.,;)')) for x in re.findall(r'10\.\d{4,9}/[^\s<>"\[\]]+',text)}
    matches=[p for p in papers if doi(p['metadata'].get('doi')) in found]
    if len(matches)==1 and title_key(matches[0]['title']) in title_key(text):
        return matches[0]['id'],'首页 DOI 唯一匹配'
    if len(matches)==1:
        return None,'识别到 DOI 但题名未确认，请确认（可能为引用或补充材料）'
    if len(matches)>1:
        return None,'首页包含多个库内 DOI，请确认对应论文'
    # Titles must appear contiguously, rather than as scattered words in references.
    normalized=title_key(text)
    matches=[p for p in papers if len(title_key(p['title']).split())>=5 and title_key(p['title']) in normalized]
    if len(matches)==1:
        return matches[0]['id'],'首页完整题名唯一匹配'
    return None,'无法唯一匹配，请确认对应论文'
