"""Search over the AGRINUXES user guide, so the assistant answers from what the platform really does.

The guide (docs/AGRINUXES_User_Guide.md) is split at its headings into chunks. Each chunk keeps its path
(Part > Chapter > Section) so an answer can say where to read more. Scoring is a small BM25-style
keyword match with extra weight for words in the heading, and a boost for the parts of the guide
that belong to the asker's account type. No external service and no extra package is needed.
"""
import math
import re
from functools import lru_cache

from django.conf import settings

STOP = set('''a an and are as at be but by can do does for from how i if in into is it its me my of on or our so that the
their them then there these this to up us was we what when where which who why will with you your should would could
have has had not no yes please want need like get use using make let about also any all'''.split())

# Which Part of the guide to favour for each account type, and words to favour in headings.
AUDIENCE = {
    'farmer': (('Part 1', 'Part 2', 'Part 3', 'Part 4', 'Part 5'), ()),
    'cooperative': (('Part 1', 'Part 2', 'Part 3', 'Part 4', 'Part 5'), ('cooperative',)),
    'vet_provider': (('Part 1', 'Part 6'), ('vet', 'appointment', 'prescription', 'patient')),
    'equipment_hire': (('Part 1', 'Part 6'), ('equipment', 'fleet', 'booking', 'maintenance')),
    'transport': (('Part 1', 'Part 6'), ('transport', 'vehicle', 'job')),
    'agriservices_provider': (('Part 1', 'Part 6'), ('agriservices', 'job schedule')),
    'agro_dealer': (('Part 1', 'Part 7'), ('agro dealer', 'catalog', 'stock')),
    'agrisupply_provider': (('Part 1', 'Part 7'), ('agrisupply', 'supply', 'deliver')),
    'agrifood_seller': (('Part 1', 'Part 7'), ('agrifood', 'produce')),
    'processor': (('Part 1', 'Part 7'), ('processor', 'sourcing', 'lot', 'traceab')),
    'individual': (('Part 1', 'Part 8'), ('individual', 'customer')),
    'government': (('Part 1', 'Part 8'), ('government',)),
    'extension': (('Part 1', 'Part 8'), ('extension', 'caseload', 'visit')),
    'partner': (('Part 1', 'Part 8'), ('partner', 'programme', 'logframe', 'indicator')),
    'visitor': (('Part 1',), ('register', 'account', 'sign')),
}


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        # very light stemming so "templates"/"template" and "records"/"record" meet
        if len(w) > 4 and w.endswith('ies'):
            w = w[:-3] + 'y'
        elif len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
            w = w[:-1]
        out.append(w)
    return out


def _clean(md):
    md = re.sub(r'<!--.*?-->', '', md, flags=re.S)
    md = md.replace('\\*', '*')
    md = re.sub(r'\*\*([^*]+)\*\*', r'\1', md)
    md = re.sub(r'`([^`]+)`', r'\1', md)
    return md


@lru_cache(maxsize=1)
def _index():
    path = settings.BASE_DIR / 'docs' / 'AGRINUXES_User_Guide.md'
    if not path.exists():
        return {'chunks': [], 'df': {}, 'avg': 1.0}
    raw = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    chunks, trail, buf = [], ['', '', ''], []

    def flush():
        body = _clean('\n'.join(buf)).strip()
        buf.clear()
        if len(body) < 80:
            return
        title = ' > '.join(t for t in trail if t)
        # split long sections at paragraph breaks so a chunk stays answer-sized
        paras, cur = body.split('\n\n'), ''
        pieces = []
        for p in paras:
            if len(cur) + len(p) > 1600 and cur:
                pieces.append(cur)
                cur = ''
            cur += ('\n\n' if cur else '') + p
        if cur:
            pieces.append(cur)
        for piece in pieces:
            chunks.append({'title': title, 'part': trail[0], 'heading': trail[-1] or trail[0], 'text': piece})

    for line in raw.split('\n'):
        m = re.match(r'^(#{1,3})\s+(.*)$', line)
        if m:
            flush()
            level = len(m.group(1))
            trail[level - 1] = _clean(m.group(2)).strip()
            for i in range(level, 3):
                trail[i] = ''
            continue
        buf.append(line)
    flush()

    df = {}
    for c in chunks:
        c['tf'] = {}
        for t in tokens(c['text']):
            c['tf'][t] = c['tf'].get(t, 0) + 1
        c['head_tokens'] = set(tokens(c['title']))
        c['len'] = sum(c['tf'].values()) or 1
        for t in c['tf']:
            df[t] = df.get(t, 0) + 1
    avg = sum(c['len'] for c in chunks) / max(1, len(chunks))
    return {'chunks': chunks, 'df': df, 'avg': avg}


def search(query, account_type='farmer', limit=4):
    """Return the best chunks for `query` as [{title, text, score}]."""
    idx = _index()
    chunks, df, avg = idx['chunks'], idx['df'], idx['avg']
    q = tokens(query)
    if not q or not chunks:
        return []
    n = len(chunks)
    parts, words = AUDIENCE.get(account_type, AUDIENCE['farmer'])
    scored = []
    for c in chunks:
        s = 0.0
        for t in set(q):
            f = c['tf'].get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * c['len'] / avg))
            if t in c['head_tokens']:
                s += 2.5
        if s <= 0:
            continue
        if any(c['part'].startswith(p) for p in parts):
            s *= 1.35
        low = c['title'].lower()
        if words and any(w in low for w in words):
            s *= 1.3
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [{'title': c['title'], 'heading': c['heading'], 'text': c['text'], 'score': round(s, 2)} for s, c in scored[:limit]]
