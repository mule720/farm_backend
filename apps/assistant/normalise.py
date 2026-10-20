"""Be forgiving about how the model spells an action: camelCase or snake_case keys, a template or cycle type given by its
name instead of its id, and the farm's only template filled in when the model leaves it out."""
import re

from . import farm_kb


def _snake(s):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', str(s or '')).replace('-', '_').lower()


def _plain(s):
    return re.sub(r'[^a-z0-9]+', '', str(s or '').casefold())


def resolve_template(value, owned):
    v = str(value or '').strip()
    ts = farm_kb.kb()['templates']
    if v in ts:
        return v
    p = _plain(v)
    for tid, t in ts.items():
        if p and (p == _plain(t['name']) or p == _plain(tid)):
            return tid
    for tid, t in ts.items():
        if p and (p in _plain(t['name']) or _plain(t['name']) in p):
            return tid
    owned = [o for o in owned if o in ts]
    return owned[0] if len(set(owned)) == 1 else None


def resolve_variant(value, tid):
    t = farm_kb.template(tid)
    p = _plain(value)
    if not t or not p:
        return None
    types = farm_kb.kb()['categories'].get(t['category'], {}).get('cycleTypes', [])
    for c in types:
        if p == _plain(c['id']) or p == _plain(c['label']):
            return c['id']
    for c in types:
        lab = _plain(c['label'])
        if p in lab or lab in p:
            return c['id']
    return None


ALIAS = {
    'startcycle': 'start_cycle', 'start': 'start_cycle', 'create_cycle': 'start_cycle', 'new_cycle': 'start_cycle',
    'customise': 'customise_template', 'customize_template': 'customise_template', 'update_template': 'customise_template',
}


def normalise(a, owned=()):
    if not isinstance(a, dict):
        return a
    b = {_snake(k): v for k, v in a.items()}
    raw_type = _snake(b.get('type', ''))
    t = ALIAS.get(raw_type, raw_type)
    out = dict(a)
    out['type'] = t
    if t in ('start_cycle', 'customise_template', 'add_enterprise'):
        tid = resolve_template(b.get('template_id') or b.get('template'), owned)
        if tid:
            out['templateId'] = tid
    if t == 'start_cycle':
        var = resolve_variant(b.get('variant_id') or b.get('variant') or b.get('cycle_type') or b.get('cycle_type_id'), out.get('templateId'))
        if var:
            out['variantId'] = var
        if not out.get('name'):
            out['name'] = b.get('cycle_name')
        if isinstance(b.get('setup_values') or b.get('setup'), dict):
            out['setupValues'] = b.get('setup_values') or b.get('setup')
        if b.get('start_date'):
            out['startDate'] = b['start_date']
    if t == 'customise_template':
        for src, dst in (('add_fields', 'addFields'), ('add_care', 'addCare'), ('fields', 'addFields'), ('care', 'addCare')):
            if b.get(src) and not out.get(dst):
                out[dst] = b[src]
        for c in out.get('addCare') or []:
            if isinstance(c, dict):
                for src, dst in (('start_day', 'startDay'), ('end_day', 'endDay'), ('repeat_every_days', 'repeatEveryDays'), ('withdrawal_days', 'withdrawalDays')):
                    if c.get(src) is not None and c.get(dst) is None:
                        c[dst] = c[src]
    return out
