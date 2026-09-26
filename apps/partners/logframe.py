"""
Results framework (logframe) — step 1 of the Partner Programme Operations Suite.

* ResultChain nodes (goal → outcome → output → activity) and Indicator rows with
  baseline, target, means of verification and disaggregation dimensions.
* Auto-sourced indicators computed from the platform's own records, always
  broken down by sex / age / participant type / district when the profile
  data exists.
* Participant household profile (sex, age, household size, youth, disability)
  set by the organisation itself or by a partner that has enrolled it.
"""
import hashlib
import graphene
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import Organization, ParticipantProfile
from apps.accounts import rbac
from .models import Programme, ProgrammeEnrollment, ProgrammeSupport, IndicatorReading, ResultChain, Indicator
from .schema import _require_partner, _own_programme, _f

AGE_BANDS = [('youth', 0, 35), ('adult', 36, 59), ('senior', 60, 200)]
SEX_LABELS = {'F': 'Women', 'M': 'Men', 'X': 'Other', 'unknown': 'Not recorded'}


# ─── Demographics ─────────────────────────────────────────────────────────────

def demographics(org_ids):
    """Per-organisation demographic keys used for every disaggregation."""
    orgs = {o['id']: o for o in Organization.objects.filter(id__in=org_ids).values('id', 'business_type', 'district', 'province')}
    profiles = {p.organization_id: p for p in ParticipantProfile.objects.filter(organization_id__in=org_ids)}
    year = timezone.localdate().year
    out = {}
    for oid, o in orgs.items():
        pr = profiles.get(oid)
        sex = (pr.head_sex if pr and pr.head_sex else 'unknown')
        age = None
        if pr and pr.head_birth_year:
            a = year - pr.head_birth_year
            age = next((b for b, lo, hi in AGE_BANDS if lo <= a <= hi), 'adult')
        elif pr and pr.youth_led is not None:
            age = 'youth' if pr.youth_led else 'adult'
        out[oid] = dict(sex=sex, age=age or 'unknown', participant_type=o['business_type'] or 'unknown',
                        district=o['district'] or 'Unspecified', household=pr.household_size if pr and pr.household_size else 0,
                        youth=bool(pr and pr.is_youth), women=bool(pr and pr.head_sex == 'F'), disability=bool(pr and pr.disability),
                        has_profile=pr is not None and bool(pr.head_sex or pr.head_birth_year or pr.household_size))
    return out


def breakdown(ids, demo, dims, weight=None):
    """{dim: {category: n}} for the given organisation ids."""
    res = {d: defaultdict(float) for d in dims}
    for i in ids:
        d = demo.get(i)
        if not d:
            continue
        w = float(weight.get(i, 0)) if weight is not None else 1.0
        for dim in dims:
            res[dim][d[dim]] += w
    return {dim: {k: (int(v) if float(v).is_integer() else round(v, 2)) for k, v in sorted(vals.items())} for dim, vals in res.items()}


def compute_auto(programme, source, dims):
    """Return (value, breakdown) for an auto-sourced indicator."""
    from apps.production.models import ProductionRecord
    from apps.market.models import MarketListing, TradeContract
    active = list(ProgrammeEnrollment.objects.filter(programme=programme, status='active').values_list('farm_id', flat=True))
    demo = demographics(active)
    dims = [d for d in (dims or []) if d in Indicator.DISAGGREGATIONS]
    if source == 'participants_enrolled':
        return float(len(active)), breakdown(active, demo, dims)
    if source == 'participants_women':
        ids = [i for i in active if demo[i]['women']]
        return float(len(ids)), breakdown(ids, demo, dims)
    if source == 'participants_youth':
        ids = [i for i in active if demo[i]['youth']]
        return float(len(ids)), breakdown(ids, demo, dims)
    if source == 'households_reached':
        w = {i: demo[i]['household'] or 1 for i in active}
        return float(sum(w.values())), breakdown(active, demo, dims, weight=w)
    sup = ProgrammeSupport.objects.filter(programme=programme, farm_id__in=active)
    if source == 'participants_supported':
        ids = list(sup.values_list('farm_id', flat=True).distinct())
        return float(len(ids)), breakdown(ids, demo, dims)
    if source in ('support_events', 'training_events'):
        qs = sup.filter(support_type='training') if source == 'training_events' else sup
        w = {r['farm_id']: r['n'] for r in qs.values('farm_id').annotate(n=Count('id'))}
        return float(sum(w.values())), breakdown(list(w), demo, dims, weight=w)
    if source == 'support_value':
        w = {r['farm_id']: _f(r['v']) for r in sup.values('farm_id').annotate(v=Sum('value'))}
        return float(sum(w.values())), breakdown(list(w), demo, dims, weight=w)
    if source == 'harvest_quantity':
        w = defaultdict(float)
        for r in ProductionRecord.objects.filter(organization_id__in=active, record_type='harvest', record_date__gte=programme.start_date).values('organization_id', 'data'):
            try:
                w[r['organization_id']] += float((r['data'] or {}).get('quantity') or 0)
            except (TypeError, ValueError):
                pass
        return float(sum(w.values())), breakdown(list(w), demo, dims, weight=w)
    if source == 'market_listings':
        w = {r['organization_id']: r['n'] for r in MarketListing.objects.filter(organization_id__in=active, status='active').values('organization_id').annotate(n=Count('id'))}
        return float(sum(w.values())), breakdown(list(w), demo, dims, weight=w)
    if source == 'contracts_fulfilled':
        w = {r['organization_id']: r['n'] for r in TradeContract.objects.filter(organization_id__in=active, status='fulfilled', updated_at__date__gte=programme.start_date).values('organization_id').annotate(n=Count('id'))}
        return float(sum(w.values())), breakdown(list(w), demo, dims, weight=w)
    return None, {}


def ensure_indicator_rows(programme):
    """Programmes created before the logframe (or through the legacy JSON list only) get their rows on first read."""
    if Indicator.objects.filter(programme=programme).exists() or not programme.indicators:
        return
    for order, ind in enumerate(programme.indicators):
        key = (ind.get('key') or '').strip()
        if not key or Indicator.objects.filter(programme=programme, key=key).exists():
            continue
        row = Indicator.objects.create(programme=programme, key=key, label=ind.get('label') or key, unit=ind.get('unit') or '',
                                       target=Decimal(str(ind['target'])) if ind.get('target') is not None else None, order=order)
        IndicatorReading.objects.filter(programme=programme, indicator_key=key, indicator__isnull=True).update(indicator=row)


def indicator_status(programme):
    """Every indicator with its current value, progress and breakdown (auto or latest manual reading)."""
    ensure_indicator_rows(programme)
    latest = {}
    for r in IndicatorReading.objects.filter(programme=programme).order_by('indicator_key', '-period', '-created_at'):
        latest.setdefault(r.indicator_key, r)
    out = []
    for ind in Indicator.objects.filter(programme=programme).select_related('result'):
        if ind.auto_source:
            val, bd = compute_auto(programme, ind.auto_source, ind.disaggregations)
            period = timezone.localdate()
        else:
            r = latest.get(ind.key)
            val = _f(r.value) if r else None
            bd = (r.disaggregation or {}) if r else {}
            period = r.period if r else None
        baseline = _f(ind.baseline) if ind.baseline is not None else None
        target = _f(ind.target) if ind.target is not None else None
        prog = None
        if val is not None and target is not None:
            if baseline is not None and target != baseline:
                prog = round((val - baseline) / (target - baseline) * 100, 1)
            elif target:
                prog = round(val / target * 100, 1)
        out.append(dict(indicator=ind, value=val, period=period, breakdown=bd, baseline=baseline, target=target, progress_pct=prog))
    return out


def participant_summary(org_ids):
    demo = demographics(org_ids)
    ids = list(demo)
    return dict(
        women=sum(1 for i in ids if demo[i]['women']), men=sum(1 for i in ids if demo[i]['sex'] == 'M'),
        youth=sum(1 for i in ids if demo[i]['youth']), disability=sum(1 for i in ids if demo[i]['disability']),
        with_profile=sum(1 for i in ids if demo[i]['has_profile']), households=sum(demo[i]['household'] or 1 for i in ids),
        by_sex=breakdown(ids, demo, ['sex'])['sex'] if ids else {}, by_age=breakdown(ids, demo, ['age'])['age'] if ids else {},
    )


# ─── Types ────────────────────────────────────────────────────────────────────

class ResultNodeType(graphene.ObjectType):
    id = graphene.ID()
    parent_id = graphene.ID()
    level = graphene.String()
    code = graphene.String()
    statement = graphene.String()
    assumptions = graphene.String()
    order = graphene.Int()


class LogframeIndicatorType(graphene.ObjectType):
    id = graphene.ID()
    result_id = graphene.ID()
    key = graphene.String()
    label = graphene.String()
    unit = graphene.String()
    baseline = graphene.Float()
    baseline_date = graphene.Date()
    target = graphene.Float()
    target_date = graphene.Date()
    means_of_verification = graphene.String()
    data_source = graphene.String()
    disaggregations = graphene.List(graphene.String)
    auto_source = graphene.String()
    order = graphene.Int()
    value = graphene.Float()
    period = graphene.Date()
    progress_pct = graphene.Float()
    breakdown = graphene.JSONString()


class LogframeType(graphene.ObjectType):
    results = graphene.List(ResultNodeType)
    indicators = graphene.List(LogframeIndicatorType)
    auto_sources = graphene.JSONString(description='[[key, label], …]')


class ParticipantProfileType(graphene.ObjectType):
    organization_id = graphene.ID()
    head_sex = graphene.String()
    head_birth_year = graphene.Int()
    head_age = graphene.Int()
    household_size = graphene.Int()
    female_members = graphene.Int()
    male_members = graphene.Int()
    youth_led = graphene.Boolean()
    is_youth = graphene.Boolean()
    disability = graphene.Boolean()
    land_ha = graphene.Float()
    has_national_id = graphene.Boolean()
    updated_at = graphene.DateTime()


def _profile_type(pr):
    if pr is None:
        return None
    return ParticipantProfileType(
        organization_id=pr.organization_id, head_sex=pr.head_sex or None, head_birth_year=pr.head_birth_year, head_age=pr.head_age(),
        household_size=pr.household_size, female_members=pr.female_members, male_members=pr.male_members, youth_led=pr.youth_led,
        is_youth=pr.is_youth, disability=pr.disability, land_ha=_f(pr.land_ha) if pr.land_ha is not None else None,
        has_national_id=bool(pr.national_id_hash), updated_at=pr.updated_at)


def _status_type(row):
    ind = row['indicator']
    return LogframeIndicatorType(
        id=ind.id, result_id=ind.result_id, key=ind.key, label=ind.label, unit=ind.unit, baseline=row['baseline'], baseline_date=ind.baseline_date,
        target=row['target'], target_date=ind.target_date, means_of_verification=ind.means_of_verification, data_source=ind.data_source,
        disaggregations=ind.disaggregations or [], auto_source=ind.auto_source or '', order=ind.order,
        value=row['value'], period=row['period'], progress_pct=row['progress_pct'], breakdown=row['breakdown'])


# ─── Queries ──────────────────────────────────────────────────────────────────

class LogframeQuery(graphene.ObjectType):
    programme_logframe = graphene.Field(LogframeType, programme_id=graphene.ID(required=True))
    my_participant_profile = graphene.Field(ParticipantProfileType)

    def resolve_programme_logframe(self, info, programme_id):
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        nodes = [ResultNodeType(id=r.id, parent_id=r.parent_id, level=r.level, code=r.code, statement=r.statement, assumptions=r.assumptions, order=r.order)
                 for r in ResultChain.objects.filter(programme=p)]
        return LogframeType(results=nodes, indicators=[_status_type(r) for r in indicator_status(p)],
                            auto_sources=[[k, l] for k, l in Indicator.AUTO_SOURCES if k])

    def resolve_my_participant_profile(self, info):
        user = info.context.user
        if user.is_anonymous or user.organization is None:
            raise Exception('Not authenticated')
        return _profile_type(ParticipantProfile.objects.filter(organization=user.organization).first())


# ─── Mutations ────────────────────────────────────────────────────────────────

class ResultInput(graphene.InputObjectType):
    level = graphene.String(required=True)
    parent_id = graphene.ID()
    code = graphene.String()
    statement = graphene.String(required=True)
    assumptions = graphene.String()
    order = graphene.Int()


class UpsertResult(graphene.Mutation):
    class Arguments:
        programme_id = graphene.ID(required=True)
        id = graphene.ID()
        input = ResultInput(required=True)

    result = graphene.Field(ResultNodeType)

    def mutate(self, info, programme_id, input, id=None):
        user = rbac.require_module(_require_partner(info), 'programmes', 'edit')
        p = _own_programme(user, programme_id)
        if input.level not in ResultChain.LEVEL_ORDER:
            raise Exception('Level must be goal, outcome, output or activity')
        parent = None
        if input.get('parent_id'):
            parent = ResultChain.objects.filter(programme=p, id=input.parent_id).first()
            if parent is None:
                raise Exception('Parent result not found')
            if ResultChain.LEVEL_ORDER[parent.level] >= ResultChain.LEVEL_ORDER[input.level]:
                raise Exception(f'A{"n" if input.level[0] in "ao" else ""} {input.level} cannot sit under a {parent.level}')
        elif input.level != 'goal' and ResultChain.objects.filter(programme=p).exists() and input.level == 'activity':
            raise Exception('An activity must sit under an output')
        r = ResultChain.objects.filter(programme=p, id=id).first() if id else ResultChain(programme=p)
        if id and r is None:
            raise Exception('Result not found')
        r.level, r.parent, r.statement = input.level, parent, input.statement.strip()
        r.code = (input.get('code') or '').strip()
        r.assumptions = (input.get('assumptions') or '').strip()
        if input.get('order') is not None:
            r.order = input.order
        elif not id:
            r.order = ResultChain.objects.filter(programme=p, parent=parent).count()
        r.save()
        return UpsertResult(result=ResultNodeType(id=r.id, parent_id=r.parent_id, level=r.level, code=r.code, statement=r.statement, assumptions=r.assumptions, order=r.order))


class DeleteResult(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        user = rbac.require_module(_require_partner(info), 'programmes', 'edit')
        r = ResultChain.objects.filter(id=id).select_related('programme').first()
        if r is None:
            raise Exception('Result not found')
        _own_programme(user, r.programme_id)
        r.delete()  # children cascade; indicators keep existing with result=NULL
        return DeleteResult(ok=True)


class LogframeIndicatorInput(graphene.InputObjectType):
    key = graphene.String()
    label = graphene.String(required=True)
    unit = graphene.String()
    result_id = graphene.ID()
    baseline = graphene.Float()
    baseline_date = graphene.Date()
    target = graphene.Float()
    target_date = graphene.Date()
    means_of_verification = graphene.String()
    data_source = graphene.String()
    disaggregations = graphene.List(graphene.String)
    auto_source = graphene.String()
    order = graphene.Int()


def _slug(s):
    import re
    return re.sub(r'[^a-z0-9]+', '_', (s or '').strip().lower()).strip('_')[:60]


class UpsertIndicator(graphene.Mutation):
    class Arguments:
        programme_id = graphene.ID(required=True)
        id = graphene.ID()
        input = LogframeIndicatorInput(required=True)

    indicator = graphene.Field(LogframeIndicatorType)

    def mutate(self, info, programme_id, input, id=None):
        user = rbac.require_module(_require_partner(info), 'programmes', 'edit')
        p = _own_programme(user, programme_id)
        ind = Indicator.objects.filter(programme=p, id=id).first() if id else Indicator(programme=p)
        if id and ind is None:
            raise Exception('Indicator not found')
        key = _slug(input.get('key') or input.label)
        if not key:
            raise Exception('Indicator needs a label')
        if Indicator.objects.filter(programme=p, key=key).exclude(id=ind.id).exists():
            raise Exception(f'Indicator key "{key}" already exists in this programme')
        if input.get('result_id'):
            res = ResultChain.objects.filter(programme=p, id=input.result_id).first()
            if res is None:
                raise Exception('Result not found')
            ind.result = res
        elif input.get('result_id') is None and 'result_id' in input:
            ind.result = None
        dims = [d for d in (input.get('disaggregations') or []) if d in Indicator.DISAGGREGATIONS]
        auto = (input.get('auto_source') or '').strip()
        if auto and auto not in dict(Indicator.AUTO_SOURCES):
            raise Exception('Unknown auto source')
        ind.key, ind.label, ind.unit = key, input.label.strip(), (input.get('unit') or '').strip()
        ind.baseline = Decimal(str(input.baseline)) if input.get('baseline') is not None else None
        ind.baseline_date = input.get('baseline_date')
        ind.target = Decimal(str(input.target)) if input.get('target') is not None else None
        ind.target_date = input.get('target_date')
        ind.means_of_verification = (input.get('means_of_verification') or '').strip()
        ind.data_source = (input.get('data_source') or '').strip()
        ind.disaggregations, ind.auto_source = dims, auto
        if input.get('order') is not None:
            ind.order = input.order
        elif not id:
            ind.order = Indicator.objects.filter(programme=p).count()
        ind.save()
        # keep the legacy JSON mirror in step for old readers
        p.indicators = [i.as_legacy() for i in Indicator.objects.filter(programme=p)]
        p.save(update_fields=['indicators'])
        row = next(r for r in indicator_status(p) if r['indicator'].id == ind.id)
        return UpsertIndicator(indicator=_status_type(row))


class DeleteIndicator(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        user = rbac.require_module(_require_partner(info), 'programmes', 'edit')
        ind = Indicator.objects.filter(id=id).first()
        if ind is None:
            raise Exception('Indicator not found')
        p = _own_programme(user, ind.programme_id)
        ind.delete()
        p.indicators = [i.as_legacy() for i in Indicator.objects.filter(programme=p)]
        p.save(update_fields=['indicators'])
        return DeleteIndicator(ok=True)


class ParticipantProfileInput(graphene.InputObjectType):
    head_sex = graphene.String()
    head_birth_year = graphene.Int()
    household_size = graphene.Int()
    female_members = graphene.Int()
    male_members = graphene.Int()
    youth_led = graphene.Boolean()
    disability = graphene.Boolean()
    land_ha = graphene.Float()
    national_id = graphene.String(description='Stored only as a salted hash')


def _can_edit_profile(user, org):
    if user.organization_id == org.id:
        return user.role == 'director' or getattr(user, 'is_org_admin', False)
    if org.org_type != 'farm':
        return False
    # partner / government staff: only for organisations enrolled in one of their programmes
    if user.role == 'saas_admin':
        return True
    if user.has_role(*rbac.PROGRAMME_ROLES) and user.organization is not None:
        try:
            rbac.require_module(user, 'programmes', 'edit')
        except Exception:
            return False
        return ProgrammeEnrollment.objects.filter(farm=org, programme__organization=user.organization).exists()
    return False


class SetParticipantProfile(graphene.Mutation):
    class Arguments:
        organization_id = graphene.ID(description='Defaults to the caller’s own organisation')
        input = ParticipantProfileInput(required=True)

    profile = graphene.Field(ParticipantProfileType)

    def mutate(self, info, input, organization_id=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        org = Organization.objects.filter(id=organization_id).first() if organization_id else user.organization
        if org is None:
            raise Exception('Organisation not found')
        if not _can_edit_profile(user, org):
            raise Exception('Permission denied: only the organisation’s director / admin or a partner it is enrolled with can set this profile')
        pr, _ = ParticipantProfile.objects.get_or_create(organization=org)
        if input.get('head_sex') is not None:
            if input.head_sex and input.head_sex not in dict(ParticipantProfile.SEX_CHOICES):
                raise Exception('Sex must be F, M or X')
            pr.head_sex = input.head_sex or ''
        year = timezone.localdate().year
        if input.get('head_birth_year') is not None:
            if input.head_birth_year and not (year - 110 <= input.head_birth_year <= year - 10):
                raise Exception('Birth year looks wrong')
            pr.head_birth_year = input.head_birth_year or None
        for f in ('household_size', 'female_members', 'male_members'):
            if input.get(f) is not None:
                if input[f] < 0 or input[f] > 60:
                    raise Exception(f'{f.replace("_", " ")} out of range')
                setattr(pr, f, input[f] or None)
        if input.get('youth_led') is not None:
            pr.youth_led = input.youth_led
        if input.get('disability') is not None:
            pr.disability = input.disability
        if input.get('land_ha') is not None:
            if input.land_ha < 0:
                raise Exception('Land cannot be negative')
            pr.land_ha = Decimal(str(input.land_ha))
        if input.get('national_id') is not None:
            nid = ''.join(ch for ch in input.national_id if ch.isalnum()).upper()
            pr.national_id_hash = hashlib.sha256((settings.SECRET_KEY + ':' + nid).encode()).hexdigest() if nid else ''
        pr.updated_by = user
        pr.save()
        return SetParticipantProfile(profile=_profile_type(pr))


class LogframeMutation(graphene.ObjectType):
    upsert_result = UpsertResult.Field()
    delete_result = DeleteResult.Field()
    upsert_indicator = UpsertIndicator.Field()
    delete_indicator = DeleteIndicator.Field()
    set_participant_profile = SetParticipantProfile.Field()
