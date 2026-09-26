"""
Supporting partners (FAO, donors, NGOs) — programme management & M&E.

A partner_manager belongs to a government / ngo / donor organisation and:
  * creates programmes with targeting (province / district / enterprise
    category), a budget, an enrolment target and a results framework;
  * enrols farms that have opted in to data sharing (identity visible for
    enrolled farms only — that is what enrolment means);
  * records support delivered (inputs, grants, training) per farm;
  * records indicator readings and sees live, computed results from the
    enrolled farms' own records;
  * sends notices to enrolled farms.

Farmers see the programmes they are in and what they received.
"""
import graphene
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum, Q
from django.utils import timezone
from graphene_django import DjangoObjectType

from apps.accounts.models import Organization, Profile
from apps.accounts import rbac
from .models import Programme, ProgrammeEnrollment, ProgrammeSupport, IndicatorReading, Indicator


# ─── Guards ───────────────────────────────────────────────────────────────────

def _require_partner(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    # Any government or partner role may reach programmes; the module matrix decides read vs write
    if not user.has_role(*rbac.PROGRAMME_ROLES):  # or saas_admin
        raise Exception('Permission denied: government / partner access required')
    if user.role in rbac.PROGRAMME_ROLES and (user.organization is None or user.organization.org_type == 'farm'):
        raise Exception('Programme managers must belong to a government / partner organisation')
    rbac.require_module(user, 'programmes', 'view')
    return user


def _require_farm_member(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    if user.organization is None or user.organization.org_type != 'farm':
        raise Exception('Permission denied: farm account required')
    return user


def _own_programme(user, programme_id):
    qs = Programme.objects.all() if user.role == 'saas_admin' else Programme.objects.filter(organization=user.organization)
    try:
        return qs.get(id=programme_id)
    except Programme.DoesNotExist:
        raise Exception('Programme not found')


def _eligible_farms(programme):
    """Consenting private-sector organisations (farms and every vendor type) matching the targeting."""
    from apps.enterprises.models import Enterprise
    qs = Organization.objects.filter(org_type='farm', data_sharing_consent=True, is_active=True)
    if programme.target_participant_types:
        qs = qs.filter(business_type__in=programme.target_participant_types)
    if programme.target_provinces:
        q = Q()
        for p in programme.target_provinces:
            q |= Q(province__iexact=p)
        qs = qs.filter(q)
    if programme.target_districts:
        q = Q()
        for d in programme.target_districts:
            q |= Q(district__iexact=d)
        qs = qs.filter(q)
    if programme.target_enterprise_categories:
        qs = qs.filter(id__in=Enterprise.objects.filter(
            category__in=programme.target_enterprise_categories, is_active=True).values('organization_id'))
    return qs


def _f(v):
    return float(v) if v is not None else 0.0


# ─── Types ────────────────────────────────────────────────────────────────────

class IndicatorType(graphene.ObjectType):
    key = graphene.String()
    label = graphene.String()
    unit = graphene.String()
    baseline = graphene.Float()
    target = graphene.Float()
    latest_value = graphene.Float()
    latest_period = graphene.Date()
    progress_pct = graphene.Float()
    auto_source = graphene.String()
    breakdown = graphene.JSONString()


class IndicatorReadingType(DjangoObjectType):
    recorded_by_name = graphene.String()

    class Meta:
        model = IndicatorReading
        fields = ['id', 'indicator_key', 'period', 'value', 'notes', 'created_at']

    disaggregation = graphene.JSONString()

    def resolve_disaggregation(self, info):
        return self.disaggregation or {}

    def resolve_recorded_by_name(self, info):
        return self.recorded_by.full_name if self.recorded_by else None


class ProgrammeResultsType(graphene.ObjectType):
    """Live results computed from enrolled farms' own records."""
    farms_enrolled = graphene.Int()
    farms_active = graphene.Int()
    districts = graphene.Int()
    enterprises = graphene.Int()
    active_batches = graphene.Int()
    records_since_start = graphene.Int()
    harvest_records_since_start = graphene.Int()
    harvest_quantity_since_start = graphene.Float()
    reports_resolved_since_start = graphene.Int()
    reports_open = graphene.Int()
    support_events = graphene.Int()
    support_value = graphene.Float()
    farms_supported = graphene.Int()
    budget_used_pct = graphene.Float()
    enrolment_pct = graphene.Float()
    market_listings = graphene.Int()
    contracts_fulfilled = graphene.Int()
    participants_by_type = graphene.JSONString()
    participants_women = graphene.Int()
    participants_men = graphene.Int()
    participants_youth = graphene.Int()
    participants_disability = graphene.Int()
    participants_with_profile = graphene.Int()
    households_reached = graphene.Int()
    participants_by_sex = graphene.JSONString()
    participants_by_age = graphene.JSONString()


class IndicatorDefType(graphene.ObjectType):
    key = graphene.String()
    label = graphene.String()
    unit = graphene.String()
    target = graphene.Float()


class ProgrammeType(DjangoObjectType):
    organization_name = graphene.String()
    results = graphene.Field(ProgrammeResultsType)
    indicator_status = graphene.List(IndicatorType)
    # JSONFields would otherwise be exposed as JSON-encoded strings; give them real shapes.
    target_provinces = graphene.List(graphene.String)
    target_districts = graphene.List(graphene.String)
    target_enterprise_categories = graphene.List(graphene.String)
    target_participant_types = graphene.List(graphene.String)
    indicators = graphene.List(IndicatorDefType)

    class Meta:
        model = Programme
        fields = ['id', 'name', 'code', 'description', 'funder', 'status', 'start_date', 'end_date',
                  'budget', 'currency', 'target_farms', 'created_at', 'updated_at']
        convert_choices_to_enum = False

    def resolve_organization_name(self, info):
        return self.organization.name

    def resolve_target_provinces(self, info):
        return self.target_provinces or []

    def resolve_target_districts(self, info):
        return self.target_districts or []

    def resolve_target_enterprise_categories(self, info):
        return self.target_enterprise_categories or []

    def resolve_target_participant_types(self, info):
        return self.target_participant_types or []

    def resolve_indicators(self, info):
        from .logframe import ensure_indicator_rows
        ensure_indicator_rows(self)
        rows = list(Indicator.objects.filter(programme=self))
        if rows:
            return [IndicatorDefType(key=i.key, label=i.label, unit=i.unit, target=_f(i.target) if i.target is not None else None) for i in rows]
        return [IndicatorDefType(key=i.get('key'), label=i.get('label'), unit=i.get('unit'), target=i.get('target'))
                for i in (self.indicators or [])]

    def resolve_results(self, info):
        return _results(self)

    def resolve_indicator_status(self, info):
        from .logframe import indicator_status
        return [IndicatorType(key=r['indicator'].key, label=r['indicator'].label, unit=r['indicator'].unit, baseline=r['baseline'], target=r['target'],
                              latest_value=r['value'], latest_period=r['period'], progress_pct=r['progress_pct'],
                              auto_source=r['indicator'].auto_source or '', breakdown=r['breakdown'])
                for r in indicator_status(self)]


class EnrolledFarmType(graphene.ObjectType):
    enrollment_id = graphene.ID()
    farm_id = graphene.ID()
    name = graphene.String()
    business_type = graphene.String()
    market_listings = graphene.Int()
    contracts_fulfilled = graphene.Int()
    province = graphene.String()
    district = graphene.String()
    status = graphene.String()
    cohort = graphene.String()
    enrolled_at = graphene.DateTime()
    enterprises = graphene.Int()
    enterprise_categories = graphene.List(graphene.String)
    records_since_start = graphene.Int()
    harvest_quantity_since_start = graphene.Float()
    support_events = graphene.Int()
    support_value = graphene.Float()
    head_sex = graphene.String()
    head_age = graphene.Int()
    is_youth = graphene.Boolean()
    household_size = graphene.Int()
    has_profile = graphene.Boolean()


class EligibleFarmType(graphene.ObjectType):
    farm_id = graphene.ID()
    name = graphene.String()
    business_type = graphene.String()
    province = graphene.String()
    district = graphene.String()
    enterprises = graphene.Int()
    enterprise_categories = graphene.List(graphene.String)


class SupportType(DjangoObjectType):
    farm_name = graphene.String()
    farm_id = graphene.ID()
    programme_name = graphene.String()

    class Meta:
        model = ProgrammeSupport
        fields = ['id', 'support_type', 'description', 'quantity', 'unit', 'value', 'currency',
                  'delivered_on', 'reference', 'created_at']
        convert_choices_to_enum = False

    def resolve_farm_name(self, info):
        return self.farm.name

    def resolve_farm_id(self, info):
        return self.farm_id

    def resolve_programme_name(self, info):
        return self.programme.name


class SupportByTypeType(graphene.ObjectType):
    support_type = graphene.String()
    events = graphene.Int()
    farms = graphene.Int()
    value = graphene.Float()


class ProgrammeDistrictType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    farms = graphene.Int()
    records_since_start = graphene.Int()
    harvest_quantity_since_start = graphene.Float()
    support_value = graphene.Float()


class MyProgrammeType(graphene.ObjectType):
    programme_id = graphene.ID()
    name = graphene.String()
    partner_name = graphene.String()
    funder = graphene.String()
    status = graphene.String()
    cohort = graphene.String()
    enrolled_at = graphene.DateTime()
    support = graphene.List(SupportType)


class PartnerOverviewType(graphene.ObjectType):
    programmes = graphene.Int()
    active_programmes = graphene.Int()
    farms_enrolled = graphene.Int()
    total_budget = graphene.Float()
    support_value = graphene.Float()
    districts_reached = graphene.Int()


# ─── Results computation ──────────────────────────────────────────────────────

def _results(programme):
    from apps.enterprises.models import Enterprise, EnterpriseBatch
    from apps.production.models import ProductionRecord
    from apps.vision.models import FarmerReport
    from apps.market.models import MarketListing, TradeContract

    enr = ProgrammeEnrollment.objects.filter(programme=programme)
    ids = list(enr.values_list('farm_id', flat=True))
    active_ids = list(enr.filter(status='active').values_list('farm_id', flat=True))
    start = programme.start_date

    harvest = ProductionRecord.objects.filter(
        organization_id__in=ids, record_type='harvest', record_date__gte=start).values_list('data', flat=True)
    hq, hn = 0.0, 0
    for d in harvest:
        hn += 1
        try:
            hq += float((d or {}).get('quantity') or 0)
        except (TypeError, ValueError):
            pass
    sup = ProgrammeSupport.objects.filter(programme=programme).aggregate(
        n=Count('id'), v=Sum('value'), farms=Count('farm', distinct=True))
    budget = _f(programme.budget)
    geo = Organization.objects.filter(id__in=ids).values('province', 'district').distinct()
    from .logframe import participant_summary
    demo = participant_summary(active_ids)
    return ProgrammeResultsType(
        farms_enrolled=len(ids), farms_active=len(active_ids),
        districts=len({(g['province'], g['district']) for g in geo}),
        enterprises=Enterprise.objects.filter(organization_id__in=ids, is_active=True).count(),
        active_batches=EnterpriseBatch.objects.filter(organization_id__in=ids, status='active').count(),
        records_since_start=ProductionRecord.objects.filter(organization_id__in=ids, record_date__gte=start).count(),
        harvest_records_since_start=hn, harvest_quantity_since_start=hq,
        reports_resolved_since_start=FarmerReport.objects.filter(
            organization_id__in=ids, is_resolved=True, updated_at__date__gte=start).count(),
        reports_open=FarmerReport.objects.filter(organization_id__in=ids, is_resolved=False).count(),
        support_events=sup['n'], support_value=_f(sup['v']), farms_supported=sup['farms'],
        budget_used_pct=(round(_f(sup['v']) / budget * 100, 1) if budget else 0.0),
        enrolment_pct=(round(len(ids) / programme.target_farms * 100, 1) if programme.target_farms else 0.0),
        market_listings=MarketListing.objects.filter(organization_id__in=ids, status='active').count(),
        contracts_fulfilled=TradeContract.objects.filter(organization_id__in=ids, status='fulfilled', updated_at__date__gte=start).count(),
        participants_by_type={r['business_type']: r['n'] for r in Organization.objects.filter(id__in=ids).values('business_type').annotate(n=Count('id'))},
        participants_women=demo['women'], participants_men=demo['men'], participants_youth=demo['youth'], participants_disability=demo['disability'],
        participants_with_profile=demo['with_profile'], households_reached=demo['households'], participants_by_sex=demo['by_sex'], participants_by_age=demo['by_age'],
    )


# ─── Queries ──────────────────────────────────────────────────────────────────

class PartnerQuery(graphene.ObjectType):
    partner_overview = graphene.Field(PartnerOverviewType)
    partner_programmes = graphene.List(ProgrammeType, status=graphene.String())
    partner_programme = graphene.Field(ProgrammeType, id=graphene.ID(required=True))
    programme_enrolled_farms = graphene.List(EnrolledFarmType, programme_id=graphene.ID(required=True))
    programme_eligible_farms = graphene.List(EligibleFarmType, programme_id=graphene.ID(required=True), search=graphene.String(), district=graphene.String())
    programme_support = graphene.List(SupportType, programme_id=graphene.ID(required=True), farm_id=graphene.ID())
    programme_support_by_type = graphene.List(SupportByTypeType, programme_id=graphene.ID(required=True))
    programme_districts = graphene.List(ProgrammeDistrictType, programme_id=graphene.ID(required=True))
    programme_indicator_readings = graphene.List(IndicatorReadingType, programme_id=graphene.ID(required=True), indicator_key=graphene.String())
    # Farmer-facing
    my_programmes = graphene.List(MyProgrammeType)

    def resolve_partner_overview(self, info):
        user = _require_partner(info)
        progs = Programme.objects.filter(organization=user.organization)
        ids = list(progs.values_list('id', flat=True))
        enr = ProgrammeEnrollment.objects.filter(programme_id__in=ids)
        farm_ids = enr.values('farm_id').distinct()
        return PartnerOverviewType(
            programmes=len(ids), active_programmes=progs.filter(status='active').count(),
            farms_enrolled=farm_ids.count(),
            total_budget=_f(progs.aggregate(b=Sum('budget'))['b']),
            support_value=_f(ProgrammeSupport.objects.filter(programme_id__in=ids).aggregate(v=Sum('value'))['v']),
            districts_reached=Organization.objects.filter(id__in=farm_ids).values('province', 'district').distinct().count(),
        )

    def resolve_partner_programmes(self, info, status=None):
        user = _require_partner(info)
        qs = Programme.objects.filter(organization=user.organization)
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_partner_programme(self, info, id):
        return _own_programme(_require_partner(info), id)

    def resolve_programme_enrolled_farms(self, info, programme_id):
        from apps.enterprises.models import Enterprise
        from apps.production.models import ProductionRecord
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        enr = list(ProgrammeEnrollment.objects.filter(programme=p).select_related('farm'))
        ids = [e.farm_id for e in enr]
        cats = defaultdict(list)
        for r in Enterprise.objects.filter(organization_id__in=ids, is_active=True).values('organization_id', 'category'):
            cats[r['organization_id']].append(r['category'])
        recs = {r['organization_id']: r['n'] for r in ProductionRecord.objects.filter(
            organization_id__in=ids, record_date__gte=p.start_date).values('organization_id').annotate(n=Count('id'))}
        hq = defaultdict(float)
        for r in ProductionRecord.objects.filter(organization_id__in=ids, record_type='harvest',
                                                 record_date__gte=p.start_date).values('organization_id', 'data'):
            try:
                hq[r['organization_id']] += float((r['data'] or {}).get('quantity') or 0)
            except (TypeError, ValueError):
                pass
        sup = {r['farm_id']: r for r in ProgrammeSupport.objects.filter(programme=p)
               .values('farm_id').annotate(n=Count('id'), v=Sum('value'))}
        from apps.market.models import MarketListing, TradeContract
        lst = {r['organization_id']: r['n'] for r in MarketListing.objects.filter(organization_id__in=ids, status='active').values('organization_id').annotate(n=Count('id'))}
        ctr = {r['organization_id']: r['n'] for r in TradeContract.objects.filter(organization_id__in=ids, status='fulfilled').values('organization_id').annotate(n=Count('id'))}
        from apps.accounts.models import ParticipantProfile
        prof = {x.organization_id: x for x in ParticipantProfile.objects.filter(organization_id__in=ids)}
        return [EnrolledFarmType(
            head_sex=(prof[e.farm_id].head_sex or None) if e.farm_id in prof else None, head_age=prof[e.farm_id].head_age() if e.farm_id in prof else None,
            is_youth=prof[e.farm_id].is_youth if e.farm_id in prof else None, household_size=prof[e.farm_id].household_size if e.farm_id in prof else None,
            has_profile=e.farm_id in prof,
            enrollment_id=e.id, farm_id=e.farm_id, name=e.farm.name, business_type=e.farm.business_type, province=e.farm.province,
            market_listings=lst.get(e.farm_id, 0), contracts_fulfilled=ctr.get(e.farm_id, 0),
            district=e.farm.district, status=e.status, cohort=e.cohort, enrolled_at=e.enrolled_at,
            enterprises=len(cats.get(e.farm_id, [])), enterprise_categories=sorted(set(cats.get(e.farm_id, []))),
            records_since_start=recs.get(e.farm_id, 0), harvest_quantity_since_start=hq.get(e.farm_id, 0.0),
            support_events=sup.get(e.farm_id, {}).get('n', 0), support_value=_f(sup.get(e.farm_id, {}).get('v')),
        ) for e in enr]

    def resolve_programme_eligible_farms(self, info, programme_id, search=None, district=None):
        from apps.enterprises.models import Enterprise
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        qs = _eligible_farms(p).exclude(id__in=ProgrammeEnrollment.objects.filter(programme=p).values('farm_id'))
        if search:
            qs = qs.filter(name__icontains=search.strip())
        if district:
            qs = qs.filter(district__iexact=district.strip())
        farms = list(qs.order_by('name')[:200])
        cats = defaultdict(list)
        for r in Enterprise.objects.filter(organization_id__in=[f.id for f in farms], is_active=True).values('organization_id', 'category'):
            cats[r['organization_id']].append(r['category'])
        return [EligibleFarmType(farm_id=f.id, name=f.name, business_type=f.business_type, province=f.province, district=f.district,
                                 enterprises=len(cats.get(f.id, [])), enterprise_categories=sorted(set(cats.get(f.id, []))))
                for f in farms]

    def resolve_programme_support(self, info, programme_id, farm_id=None):
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        qs = ProgrammeSupport.objects.filter(programme=p).select_related('farm', 'programme')
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        return qs

    def resolve_programme_support_by_type(self, info, programme_id):
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        rows = ProgrammeSupport.objects.filter(programme=p).values('support_type') \
            .annotate(n=Count('id'), farms=Count('farm', distinct=True), v=Sum('value')).order_by('-v')
        return [SupportByTypeType(support_type=r['support_type'], events=r['n'], farms=r['farms'], value=_f(r['v'])) for r in rows]

    def resolve_programme_districts(self, info, programme_id):
        from apps.production.models import ProductionRecord
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        ids = list(ProgrammeEnrollment.objects.filter(programme=p).values_list('farm_id', flat=True))
        geo = {o['id']: (o['province'] or 'Unspecified', o['district'] or 'Unspecified')
               for o in Organization.objects.filter(id__in=ids).values('id', 'province', 'district')}
        rows = defaultdict(lambda: dict(farms=0, records_since_start=0, harvest_quantity_since_start=0.0, support_value=0.0))
        for oid, key in geo.items():
            rows[key]['farms'] += 1
        for r in ProductionRecord.objects.filter(organization_id__in=ids, record_date__gte=p.start_date).values('organization_id', 'record_type', 'data'):
            key = geo.get(r['organization_id'])
            if not key:
                continue
            rows[key]['records_since_start'] += 1
            if r['record_type'] == 'harvest':
                try:
                    rows[key]['harvest_quantity_since_start'] += float((r['data'] or {}).get('quantity') or 0)
                except (TypeError, ValueError):
                    pass
        for r in ProgrammeSupport.objects.filter(programme=p).values('farm_id').annotate(v=Sum('value')):
            key = geo.get(r['farm_id'])
            if key:
                rows[key]['support_value'] += _f(r['v'])
        return [ProgrammeDistrictType(province=k[0], district=k[1], **v) for k, v in sorted(rows.items())]

    def resolve_programme_indicator_readings(self, info, programme_id, indicator_key=None):
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        qs = IndicatorReading.objects.filter(programme=p).select_related('recorded_by')
        if indicator_key:
            qs = qs.filter(indicator_key=indicator_key)
        return qs

    def resolve_my_programmes(self, info):
        user = _require_farm_member(info)
        enr = ProgrammeEnrollment.objects.filter(farm=user.organization).select_related('programme', 'programme__organization')
        out = []
        for e in enr:
            out.append(MyProgrammeType(
                programme_id=e.programme_id, name=e.programme.name, partner_name=e.programme.organization.name,
                funder=e.programme.funder, status=e.status, cohort=e.cohort, enrolled_at=e.enrolled_at,
                support=ProgrammeSupport.objects.filter(programme=e.programme, farm=user.organization).select_related('farm', 'programme'),
            ))
        return out


# ─── Mutations ────────────────────────────────────────────────────────────────

class IndicatorInput(graphene.InputObjectType):
    key = graphene.String(required=True)
    label = graphene.String(required=True)
    unit = graphene.String()
    target = graphene.Float()


class ProgrammeInput(graphene.InputObjectType):
    name = graphene.String()
    code = graphene.String()
    description = graphene.String()
    funder = graphene.String()
    status = graphene.String()
    start_date = graphene.Date()
    end_date = graphene.Date()
    budget = graphene.Float()
    currency = graphene.String()
    target_provinces = graphene.List(graphene.String)
    target_districts = graphene.List(graphene.String)
    target_enterprise_categories = graphene.List(graphene.String)
    target_participant_types = graphene.List(graphene.String)
    target_farms = graphene.Int()
    indicators = graphene.List(IndicatorInput)


def _sync_indicator_rows(p):
    """Mirror the quick indicator list from the programme form into Indicator rows (never deletes rows that carry extra logframe detail)."""
    if not getattr(p, '_sync_indicator_rows', False):
        return
    existing = {i.key: i for i in Indicator.objects.filter(programme=p)}
    keep = set()
    for order, ind in enumerate(p.indicators or []):
        keep.add(ind['key'])
        row = existing.get(ind['key'])
        if row is None:
            Indicator.objects.create(programme=p, key=ind['key'], label=ind['label'], unit=ind['unit'],
                                     target=Decimal(str(ind['target'])) if ind['target'] is not None else None, order=order)
        else:
            row.label, row.unit, row.order = ind['label'], ind['unit'], order
            row.target = Decimal(str(ind['target'])) if ind['target'] is not None else None
            row.save(update_fields=['label', 'unit', 'target', 'order'])
    for key, row in existing.items():
        if key not in keep and not (row.result_id or row.auto_source or row.baseline is not None or row.means_of_verification):
            row.delete()
    p.indicators = [i.as_legacy() for i in Indicator.objects.filter(programme=p)]
    Programme.objects.filter(id=p.id).update(indicators=p.indicators)


def _apply_programme_input(p, input):
    simple = ['name', 'code', 'description', 'funder', 'start_date', 'end_date', 'currency', 'target_farms']
    for f in simple:
        v = input.get(f)
        if v is not None:
            setattr(p, f, v.strip() if isinstance(v, str) else v)
    if input.get('status') is not None:
        if input.status not in dict(Programme.STATUS_CHOICES):
            raise Exception('Invalid programme status')
        p.status = input.status
    if input.get('budget') is not None:
        if input.budget < 0:
            raise Exception('Budget cannot be negative')
        p.budget = Decimal(str(input.budget))
    for f in ('target_provinces', 'target_districts', 'target_enterprise_categories', 'target_participant_types'):
        v = input.get(f)
        if v is not None:
            setattr(p, f, [x.strip() for x in v if x and x.strip()])
    valid_types = dict(Organization.BUSINESS_TYPE_CHOICES)
    bad = [t for t in (p.target_participant_types or []) if t not in valid_types]
    if bad:
        raise Exception(f'Unknown participant type(s): {", ".join(bad)}')
    if input.get('indicators') is not None:
        keys = set()
        inds = []
        for i in input.indicators:
            k = i.key.strip()
            if not k or k in keys:
                raise Exception('Indicator keys must be unique and non-empty')
            keys.add(k)
            inds.append({'key': k, 'label': i.label.strip(), 'unit': (i.get('unit') or '').strip(),
                         'target': float(i.target) if i.get('target') is not None else None})
        p.indicators = inds
        p._sync_indicator_rows = True
    if p.end_date and p.start_date and p.end_date < p.start_date:
        raise Exception('End date must be after start date')


def _confine_to_branch(user, p):
    """A member of a district / provincial branch can only run programmes inside that geography."""
    bp, bd = rbac.branch_geo(user)
    if bd:
        if p.target_districts and any(d.lower() != bd.lower() for d in p.target_districts):
            raise Exception(f'Your branch only runs programmes in {bd}')
        p.target_districts = [bd]
        p.target_provinces = [bp] if bp else p.target_provinces
    elif bp:
        if p.target_provinces and any(x.lower() != bp.lower() for x in p.target_provinces):
            raise Exception(f'Your branch only runs programmes in {bp}')
        p.target_provinces = [bp]


class CreateProgramme(graphene.Mutation):
    class Arguments:
        input = ProgrammeInput(required=True)

    programme = graphene.Field(ProgrammeType)

    def mutate(self, info, input):
        user = rbac.require_module(_require_partner(info), 'programmes', 'create')
        if not (input.get('name') or '').strip():
            raise Exception('Programme name is required')
        if not input.get('start_date'):
            raise Exception('Start date is required')
        p = Programme(organization=user.organization, created_by=user, start_date=input.start_date)
        _apply_programme_input(p, input)
        _confine_to_branch(user, p)
        p.save()
        _sync_indicator_rows(p)
        return CreateProgramme(programme=p)


class UpdateProgramme(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = ProgrammeInput(required=True)

    programme = graphene.Field(ProgrammeType)

    def mutate(self, info, id, input):
        user = rbac.require_module(_require_partner(info), 'programmes', 'edit')
        p = _own_programme(user, id)
        _apply_programme_input(p, input)
        _confine_to_branch(user, p)
        p.save()
        _sync_indicator_rows(p)
        return UpdateProgramme(programme=p)


class EnrollFarm(graphene.Mutation):
    class Arguments:
        programme_id = graphene.ID(required=True)
        farm_id = graphene.ID(required=True)
        cohort = graphene.String()
        notes = graphene.String()

    enrollment_id = graphene.ID()

    def mutate(self, info, programme_id, farm_id, cohort=None, notes=None):
        from apps.notifications.models import Notification
        user = rbac.require_module(_require_partner(info), 'enrolment', 'create')
        p = _own_programme(user, programme_id)
        if p.status in ('closed', 'suspended'):
            raise Exception(f'Programme is {p.status}; enrolment is not open')
        try:
            farm = _eligible_farms(p).get(id=farm_id)
        except Organization.DoesNotExist:
            raise Exception('Farm is not eligible: it must have opted in to data sharing and match the programme targeting')
        with transaction.atomic():
            e, created = ProgrammeEnrollment.objects.get_or_create(
                programme=p, farm=farm, defaults={'enrolled_by': user, 'cohort': cohort or '', 'notes': notes or ''})
            if not created:
                if e.status == 'active':
                    raise Exception('Farm is already enrolled')
                e.status, e.ended_at, e.enrolled_at = 'active', None, timezone.now()
                if cohort is not None:
                    e.cohort = cohort
                e.save()
            Notification.objects.bulk_create([
                Notification(recipient=m, title=f'Enrolled in {p.name}',
                             message=f'{user.organization.name} has enrolled your farm in "{p.name}"'
                                     f'{" (" + p.funder + ")" if p.funder else ""}. You will receive programme notices and support records here.',
                             category='system', priority='info', action_url='/settings', ref_id=str(e.id))
                for m in Profile.objects.filter(organization=farm, is_active=True)
            ])
        return EnrollFarm(enrollment_id=e.id)


class UpdateEnrollment(graphene.Mutation):
    class Arguments:
        enrollment_id = graphene.ID(required=True)
        status = graphene.String()
        cohort = graphene.String()
        notes = graphene.String()

    ok = graphene.Boolean()

    def mutate(self, info, enrollment_id, status=None, cohort=None, notes=None):
        user = rbac.require_module(_require_partner(info), 'enrolment', 'edit')
        try:
            e = ProgrammeEnrollment.objects.select_related('programme').get(id=enrollment_id)
        except ProgrammeEnrollment.DoesNotExist:
            raise Exception('Enrolment not found')
        _own_programme(user, e.programme_id)
        if status is not None:
            if status not in dict(ProgrammeEnrollment.STATUS_CHOICES):
                raise Exception('Invalid enrolment status')
            e.status = status
            e.ended_at = None if status == 'active' else timezone.now()
        if cohort is not None:
            e.cohort = cohort
        if notes is not None:
            e.notes = notes
        e.save()
        return UpdateEnrollment(ok=True)


class SupportInput(graphene.InputObjectType):
    programme_id = graphene.ID(required=True)
    farm_id = graphene.ID(required=True)
    support_type = graphene.String(required=True)
    description = graphene.String(required=True)
    quantity = graphene.Float()
    unit = graphene.String()
    value = graphene.Float()
    currency = graphene.String()
    delivered_on = graphene.Date(required=True)
    reference = graphene.String()
    notify_farm = graphene.Boolean()


class RecordSupport(graphene.Mutation):
    class Arguments:
        input = SupportInput(required=True)

    support = graphene.Field(SupportType)

    def mutate(self, info, input):
        from apps.notifications.models import Notification
        user = rbac.require_module(_require_partner(info), 'support', 'create')
        p = _own_programme(user, input.programme_id)
        if input.support_type not in dict(ProgrammeSupport.TYPE_CHOICES):
            raise Exception('Invalid support type')
        if not ProgrammeEnrollment.objects.filter(programme=p, farm_id=input.farm_id, status='active').exists():
            raise Exception('Farm is not actively enrolled in this programme')
        if (input.get('value') or 0) < 0 or (input.get('quantity') or 0) < 0:
            raise Exception('Value and quantity cannot be negative')
        with transaction.atomic():
            s = ProgrammeSupport.objects.create(
                programme=p, farm_id=input.farm_id, support_type=input.support_type,
                description=input.description.strip(), quantity=Decimal(str(input.get('quantity') or 1)),
                unit=(input.get('unit') or '').strip(), value=Decimal(str(input.get('value') or 0)),
                currency=(input.get('currency') or p.currency).strip(), delivered_on=input.delivered_on,
                reference=(input.get('reference') or '').strip(), created_by=user,
            )
            if input.get('notify_farm', True):
                label = dict(ProgrammeSupport.TYPE_CHOICES)[s.support_type]
                Notification.objects.bulk_create([
                    Notification(recipient=m, title=f'{p.name}: {label} received'[:200],
                                 message=f'{s.description} ({s.quantity:g} {s.unit}'.rstrip() + f'; value {s.currency} {s.value}). '
                                         f'Ref: {s.reference or "—"}.',
                                 category='financial', priority='info', action_url='/settings', ref_id=str(s.id))
                    for m in Profile.objects.filter(organization_id=input.farm_id, is_active=True)
                ])
        return RecordSupport(support=s)


class RecordIndicatorReading(graphene.Mutation):
    class Arguments:
        programme_id = graphene.ID(required=True)
        indicator_key = graphene.String(required=True)
        period = graphene.Date(required=True)
        value = graphene.Float(required=True)
        notes = graphene.String()
        disaggregation = graphene.JSONString(description='{"sex": {"F": 12, "M": 8}, "age": {"youth": 5, "adult": 15}}')

    reading = graphene.Field(IndicatorReadingType)

    def mutate(self, info, programme_id, indicator_key, period, value, notes=None, disaggregation=None):
        user = rbac.require_module(_require_partner(info), 'me', 'create')
        p = _own_programme(user, programme_id)
        ind = Indicator.objects.filter(programme=p, key=indicator_key).first()
        if ind is None and indicator_key not in {i.get('key') for i in (p.indicators or [])}:
            raise Exception('Unknown indicator for this programme')
        if ind is not None and ind.auto_source:
            raise Exception('This indicator is computed automatically from platform records; it does not take manual readings')
        dis = {}
        for dim, cats in (disaggregation or {}).items():
            if dim not in Indicator.DISAGGREGATIONS or not isinstance(cats, dict):
                raise Exception(f'Unknown disaggregation dimension "{dim}"')
            clean = {}
            for k, v in cats.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    raise Exception(f'Disaggregation value for {dim}/{k} must be a number')
                if fv < 0:
                    raise Exception('Disaggregation values cannot be negative')
                clean[str(k)] = fv
            if clean and abs(sum(clean.values()) - float(value)) > 0.01 and dim in ('sex', 'age'):
                raise Exception(f'{dim} breakdown ({sum(clean.values()):g}) must add up to the total ({value:g})')
            dis[dim] = clean
        r = IndicatorReading.objects.create(programme=p, indicator=ind, indicator_key=indicator_key, period=period,
                                            value=Decimal(str(value)), disaggregation=dis, notes=(notes or '').strip(), recorded_by=user)
        return RecordIndicatorReading(reading=r)


class SendProgrammeNotice(graphene.Mutation):
    """Notice to every member of every actively enrolled farm."""

    class Arguments:
        programme_id = graphene.ID(required=True)
        title = graphene.String(required=True)
        message = graphene.String(required=True)
        priority = graphene.String()

    farms = graphene.Int()
    recipients = graphene.Int()

    def mutate(self, info, programme_id, title, message, priority=None):
        from apps.notifications.models import Notification
        user = rbac.require_module(_require_partner(info), 'notices', 'create')
        p = _own_programme(user, programme_id)
        pr = (priority or 'info').strip()
        if pr not in ('info', 'warning', 'critical'):
            raise Exception('Invalid priority')
        farm_ids = list(ProgrammeEnrollment.objects.filter(programme=p, status='active').values_list('farm_id', flat=True))
        members = list(Profile.objects.filter(organization_id__in=farm_ids, is_active=True))
        Notification.objects.bulk_create([
            Notification(recipient=m, title=f'[{p.name}] {title.strip()}'[:200],
                         message=f'{message.strip()}\n\n— {user.organization.name}',
                         category='system', priority=pr, action_url='/notifications', ref_id=str(p.id))
            for m in members
        ])
        return SendProgrammeNotice(farms=len(farm_ids), recipients=len(members))


class GenerateProgrammeReport(graphene.Mutation):
    """Donor results report (PDF or Excel) for a programme, optionally for a reporting period."""
    class Arguments:
        programme_id = graphene.ID(required=True)
        format = graphene.String(description="'pdf' (default) or 'xlsx'")
        period_start = graphene.Date()
        period_end = graphene.Date()

    url = graphene.String()

    def mutate(self, info, programme_id, format='pdf', period_start=None, period_end=None):
        from .reports import build_programme_report_pdf, build_programme_report_xlsx
        user = rbac.require_module(_require_partner(info), 'programmes', 'view')  # observers may export too
        p = _own_programme(user, programme_id)
        if period_start and period_end and period_end < period_start:
            raise Exception('Period end must be after period start')
        fmt = (format or 'pdf').lower()
        if fmt == 'xlsx':
            return GenerateProgrammeReport(url=build_programme_report_xlsx(p, period_start, period_end))
        if fmt != 'pdf':
            raise Exception("Format must be 'pdf' or 'xlsx'")
        return GenerateProgrammeReport(url=build_programme_report_pdf(p, period_start, period_end))


class PartnerMutation(graphene.ObjectType):
    generate_programme_report = GenerateProgrammeReport.Field()
    create_programme = CreateProgramme.Field()
    update_programme = UpdateProgramme.Field()
    enroll_farm = EnrollFarm.Field()
    update_enrollment = UpdateEnrollment.Field()
    record_support = RecordSupport.Field()
    record_indicator_reading = RecordIndicatorReading.Field()
    send_programme_notice = SendProgrammeNotice.Field()
