"""Read immutable evidence; hashes attest consistency, not independent provenance."""
import hashlib
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent

class ReportNotFoundError(ValueError):
    """The requested report is not registered or is missing."""

class ReportIntegrityError(ValueError):
    """A registered report escapes the root or has changed."""

class ReportManifestError(ValueError):
    """The manifest is unreadable or invalid."""

def list_reports():
    """Return fresh manifest entries; never cache a mutable trust baseline."""
    try:
        entries = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8'))['entries']
        seen = set()
        if not isinstance(entries, list):
            raise ValueError('entries must be a list')
        for entry in entries:
            name, digest = entry['path'], entry['sha256']
            path = PurePosixPath(name)
            if (not isinstance(name, str) or not name or path.is_absolute()
                    or '..' in path.parts or '\\' in name or str(path) != name
                    or name in seen or not re.fullmatch('[0-9a-f]{64}', digest)):
                raise ValueError('invalid or duplicate entry')
            seen.add(name)
        return entries
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReportManifestError('报告清单损坏或不可读') from exc

def read_report(name):
    entry = next((x for x in list_reports() if x['path'] == name), None)
    if entry is None:
        raise ReportNotFoundError('报告未登记')
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ReportIntegrityError('报告路径越界')
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ReportNotFoundError('登记报告缺失') from exc
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ReportIntegrityError('原报告指纹变化')
    return raw

def resolve_report_link(source, href):
    """Resolve local historical links only when an unambiguous report exists.

    Returns a registered path or None for external, missing or ambiguous links.
    Does not open URLs or rewrite evidence; callers retain URL fragments.
    """
    names = {entry['path'] for entry in list_reports()}
    if source not in names:
        raise ReportNotFoundError('源报告未登记')
    url = urlsplit(href)
    if url.scheme or url.netloc or url.path.startswith('/'):
        return None
    target = unquote(url.path)
    if not target:
        return source
    candidate = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
    if candidate in names:
        return candidate
    # Only legacy ../basename links qualify: do not guess arbitrary project paths.
    parts = PurePosixPath(target).parts
    if len(parts) < 2 or any(part != '..' for part in parts[:-1]):
        return None
    matches = [name for name in names if PurePosixPath(name).name == parts[-1]]
    return matches[0] if len(matches) == 1 else None
