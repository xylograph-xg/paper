"""Read-only file interfaces for displayed templates and exact authorization bytes."""
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def template():return (ROOT/'文献卡片模板.md').read_text()
def authorization(name,expected_sha256=None):
    path=(ROOT/'authorizations'/name).resolve()
    if not path.is_relative_to((ROOT/'authorizations').resolve()) or not path.is_file():raise ValueError('授权路径无效')
    raw=path.read_bytes()
    if expected_sha256 and hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('授权指纹不一致')
    return raw
