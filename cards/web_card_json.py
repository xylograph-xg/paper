"""Repair JSON separators/invalid escapes; never add or change scientific fields."""
import re

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null|[{}\[\]:,]')


def object_span(raw):
    """Locate one complete explicitly JSON-marked object; ambiguity stays invalid."""
    start=raw.find('{')
    if start<0:return None
    prefix=raw[:start]
    if not prefix.strip():return None
    if (len(prefix)>2000 or any(c in prefix for c in '{}[]') or
            not re.search(r'(?:\bJSON\s*|```(?:json)?\s*)$',prefix,re.I)):
        return None
    depth=0;inside=False;escape=False
    for i in range(start,len(raw)):
        c=raw[i]
        if inside:
            if escape:escape=False
            elif c=='\\':escape=True
            elif c=='"':inside=False
        elif c=='"':inside=True
        elif c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:
                if raw[i+1:].strip() not in ('','```'):return None
                return start,i+1
    return None


def json_body(raw):
    span=object_span(raw)
    return raw[span[0]:span[1]] if span else raw


def normalize_escapes(raw):
    """Only escape syntactically invalid JSON backslashes; retain scientific text."""
    out=[];inside=False;i=0
    while i<len(raw):
        c=raw[i]
        if c=='"':inside=not inside;out.append(c);i+=1;continue
        if inside and c=='\\':
            nxt=raw[i+1:i+2]
            valid=nxt in ('"','\\','/','b','f','n','r','t') or nxt=='u' and bool(re.fullmatch(r'[0-9a-fA-F]{4}',raw[i+2:i+6]))
            if valid:out.append(raw[i:i+2]);i+=2;continue
            out.append('\\\\');i+=1;continue
        out.append(c);i+=1
    return ''.join(out)


def normalize(raw):
    span=object_span(raw)
    if span:
        start,end=span
        return raw[:start]+normalize(raw[start:end])+raw[end:]
    raw = normalize_escapes(raw)
    tokens = list(TOKEN.finditer(raw))
    # Ignore fenced/prose envelopes here; the existing strict parser owns them.
    if not tokens or any(raw[a:b].strip() for a, b in
                         zip([0] + [m.end() for m in tokens], [m.start() for m in tokens] + [len(raw)])):
        return raw
    edits = []
    for i, match in enumerate(tokens):
        token = match.group()
        following = tokens[i + 1].group() if i + 1 < len(tokens) else ''
        if token == ',' and following in ('}', ']'):
            edits.append((match.start(), match.end(), ''))
        if i and token.startswith('"') and following == ':':
            previous = tokens[i - 1].group()
            if previous in ('}', ']', 'true', 'false', 'null') or previous.startswith('"') or re.match(r'-?\d', previous):
                edits.append((match.start(), match.start(), ','))
    for start, end, text in reversed(edits):
        raw = raw[:start] + text + raw[end:]
    return raw


normalize.syntax_revision='json-envelope-v1'
