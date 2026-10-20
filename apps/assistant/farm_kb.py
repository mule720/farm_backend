"""Full knowledge of the 94 built-in templates for the AI guide: cycle types, set-up questions, stages, daily record boxes and starter
care guides. Generated from the app's own code (apps/assistant/data/farm_knowledge.json), so what the guide says matches what the screen shows.
"""
import json
import re
from datetime import date
from functools import lru_cache

from django.conf import settings

from . import knowledge

CARE_KINDS = {'feed', 'water', 'vaccination', 'medication', 'spray', 'fertiliser', 'weighing', 'inspection', 'task'}
FIELD_TYPES = {'number', 'text', 'select'}

# words people use that the template names do not
ALIASES = {
    'village': 'indigenous', 'local': 'indigenous', 'roadrunner': 'indigenous', 'kienyeji': 'indigenous',
    'hen': 'chicken', 'hens': 'chicken', 'cockerel': 'chicken', 'eggs': 'layer', 'egg': 'layer', 'cattle': 'beef',
    'cow': 'dairy', 'cows': 'dairy', 'bream': 'tilapia', 'fish': 'tilapia', 'beans': 'soybean', 'corn': 'maize', 'mealie': 'maize',
    'honey': 'honeybee', 'bees': 'honeybee', 'pig': 'piggery', 'pigs': 'piggery', 'goat': 'goat', 'goats': 'goat',
}


@lru_cache(maxsize=1)
def kb():
    path = settings.BASE_DIR / 'apps' / 'assistant' / 'data' / 'farm_knowledge.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'templates': {}, 'categories': {}}


def template(tid):
    return kb()['templates'].get(tid)


def variants_of(tid):
    t = template(tid)
    return {v['id'] for v in kb()['categories'].get(t['category'], {}).get('cycleTypes', [])} if t else set()


def _tok(text):
    out = []
    for w in knowledge.tokens(text):
        out.append(ALIASES.get(w, w))
    return set(out)


def relevant(question, owned=(), limit=3):
    """Template ids to describe in full: what the farm already runs, plus the best matches for what was asked."""
    ids = [t for t in owned if t in kb()['templates']]
    q = _tok(question)
    scored = []
    for tid, t in kb()['templates'].items():
        name = _tok(t['name'])
        extra = _tok(f"{t['species']} {t['purpose']}")
        s = 3 * len(q & name) + len(q & extra)
        if s:
            scored.append((s, tid))
    scored.sort(key=lambda x: -x[0])
    for _, tid in scored:
        if tid not in ids:
            ids.append(tid)
        if len(ids) >= limit + len(owned):
            break
    return ids[:limit + len(owned)]


def _cd(c):
    bits = [f"{c['kind']}: {c['title']}"]
    if c.get('product'):
        bits.append(c['product'])
    if c.get('dose'):
        bits.append(c['dose'])
    when = f"day {c['from']}" + (f"-{c['to']}" if c.get('to') not in (None, c['from']) else '')
    if c.get('every'):
        when += f" every {c['every']}d"
    if c.get('withdrawal'):
        when += f", withdrawal {c['withdrawal']}d"
    return ' | '.join(bits) + f' ({when})'


def describe(tid, care_limit=22):
    t = template(tid)
    if not t:
        return ''
    cat = kb()['categories'].get(t['category'], {})
    lines = [f"TEMPLATE id={tid}: {t['name']} (category {t['category']})"]
    if t.get('purpose'):
        lines.append(f"  Purpose: {t['purpose']}")
    lines.append('  Stages (come from the template, the same for every cycle type): ' + '; '.join(s['name'] for s in t['stages']))
    lines.append('  Cycle types you can pick in step 1 of the New Cycle wizard: ' + '; '.join(
        f"{v['id']} = {v['label']} ({v['about']})" for v in cat.get('cycleTypes', [])))
    qs = cat.get('setupQuestions', [])
    if qs:
        lines.append('  Set-up questions in step 2 (setupValues keys): ' + '; '.join(
            f"{q['id']} = {q['label']}" + (f" [{q['unit']}]" if q.get('unit') else '') + (f" options {q['options']}" if q.get('options') else '') for q in qs))
    lines.append('  Daily Log boxes: ' + '; '.join(
        f"{f['label']}" + (f" [{f['unit']}]" if f.get('unit') else '') + ('*' if f.get('required') else '') for f in t['fields']))
    care = t['care'][:care_limit]
    if care:
        lines.append('  Starter care guide (days count from day 0): ' + ' ; '.join(_cd(c) for c in care))
    return '\n'.join(lines)


def knowledge_block(question, owned=()):
    ids = relevant(question, owned)
    return '\n\n'.join(describe(i) for i in ids)


# ── validating what the model asks the app to do ─────────────────────────────
def _num(v, lo=0, hi=5000):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _s(v, n):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def clean_start_cycle(a):
    tid = a.get('templateId')
    t = template(tid)
    if not t or a.get('variantId') not in variants_of(tid):
        return None
    out = {'type': 'start_cycle', 'templateId': tid, 'variantId': a['variantId'], 'name': _s(a.get('name'), 60) or f"{t['name']} 1"}
    sd = _s(a.get('startDate'), 10)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', sd):
        try:
            date.fromisoformat(sd)
            out['startDate'] = sd
        except ValueError:
            pass
    known = {q['id'] for q in kb()['categories'].get(t['category'], {}).get('setupQuestions', [])}
    sv = a.get('setupValues') if isinstance(a.get('setupValues'), dict) else {}
    out['setupValues'] = {k: _s(v, 60) for k, v in sv.items() if k in known and v not in (None, '')}
    out['label'] = _s(a.get('label'), 60) or f"Start {out['name']}"
    return out


def clean_customise(a):
    tid = a.get('templateId')
    if not template(tid):
        return None
    fields, care = [], []
    for f in (a.get('addFields') or [])[:6]:
        if not isinstance(f, dict) or not _s(f.get('label'), 40):
            continue
        ft = f.get('type') if f.get('type') in FIELD_TYPES else 'number'
        item = {'label': _s(f['label'], 40), 'type': ft, 'unit': _s(f.get('unit'), 12), 'required': bool(f.get('required'))}
        if ft == 'select':
            opts = [_s(o, 30) for o in (f.get('options') or []) if _s(o, 30)][:8]
            if len(opts) < 2:
                continue
            item['options'] = opts
        for k in ('min', 'max', 'target'):
            n = _num(f.get(k), -1e6, 1e6)
            if n is not None:
                item[k] = n
        fields.append(item)
    for c in (a.get('addCare') or [])[:8]:
        if not isinstance(c, dict) or c.get('kind') not in CARE_KINDS or not _s(c.get('title'), 80):
            continue
        start = _num(c.get('startDay'), 0, 3000)
        if start is None:
            continue
        item = {'kind': c['kind'], 'title': _s(c['title'], 80), 'startDay': int(start)}
        for k, n in (('product', 80), ('dose', 60), ('method', 60), ('notes', 160)):
            if _s(c.get(k), n):
                item[k] = _s(c.get(k), n)
        for k in ('endDay', 'repeatEveryDays', 'withdrawalDays'):
            v = _num(c.get(k), 0, 3000)
            if v is not None:
                item[k] = int(v)
        care.append(item)
    if not fields and not care:
        return None
    return {'type': 'customise_template', 'templateId': tid, 'addFields': fields, 'addCare': care,
            'name': _s(a.get('name'), 60), 'label': _s(a.get('label'), 60) or 'Save these to my template'}
