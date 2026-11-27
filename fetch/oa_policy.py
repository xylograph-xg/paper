"""Open-access eligibility and acquisition priority.

The pipeline deliberately separates "metadata we can discover" from "PDFs we
can fetch automatically". Subscription-publisher PDF URLs are not treated as
downloadable just because Crossref/OpenAlex exposes a link: Cloudflare and
human-verification pages are not bypassed. Only records with an OA/preprint/
repository route (or an explicit OA flag) enter the automatic download queue.
"""
from urllib.parse import urlsplit

# Hosts that have shown a high automatic-download yield in this workspace.
HIGH_HOSTS = (
    'arxiv.org', 'chemrxiv.org', 'pmc.ncbi.nlm.nih.gov', 'europepmc.org',
    'osti.gov', 'hal.science', 'nature.com', 'cambridge.org', 'aps.org',
)
# OA-friendly publishers/repositories with moderate yield. They are attempted
# after HIGH_HOSTS and before anything without an OA route.
MEDIUM_HOSTS = (
    'springer.com', 'iop.org', 'frontiersin.org', 'mdpi.com', 'silverchair.com',
    'zenodo.org', 'figshare.com', 'researchsquare.com', 'biorxiv.org', 'medrxiv.org',
)
REPOSITORY_MARKERS = ('eprints', 'repository', 'diva-portal', 'archives-ouvertes', 'hal.')
HIGH_PREFIXES = ('10.48550', '10.26434', '10.1038', '10.1103', '10.1017')
MEDIUM_PREFIXES = ('10.1007', '10.1088', '10.3390', '10.1109')


def _host(url):
    try:return (urlsplit(url).hostname or '').lower()
    except (TypeError,ValueError):return ''


def _matches(host,suffix):
    return bool(host) and (host==suffix or host.endswith('.'+suffix))


def _is_repository(host):
    return any(marker in host for marker in REPOSITORY_MARKERS)


def eligible(record):
    """True when the record has an OA/preprint/repository route."""
    if record.get('is_oa') is True:return True
    # A known DOI prefix is not an OA route by itself: Nature/Springer/APS
    # landing PDF links can still be paywalled. Only explicit OA markers or
    # repository/preprint URLs pass the automatic queue.
    channels=record.get('channels') or []
    if 'arxiv' in channels or 'chemrxiv' in channels:return True
    if record.get('arxiv_id') or record.get('open_access_pdf'):return True
    for url in record.get('pdf_urls') or []:
        host=_host(url)
        if any(_matches(host,suffix) for suffix in HIGH_HOSTS+MEDIUM_HOSTS) or _is_repository(host):return True
    return False


def priority(record):
    """0 = high-yield OA, 1 = other OA route, 2 = no automatic OA route."""
    if not eligible(record):return 2
    prefix=(record.get('doi') or '').split('/')[0]
    channels=record.get('channels') or []
    if 'arxiv' in channels or 'chemrxiv' in channels or prefix in HIGH_PREFIXES:return 0
    for url in record.get('pdf_urls') or []:
        host=_host(url)
        if any(_matches(host,suffix) for suffix in HIGH_HOSTS):return 0
    return 1
