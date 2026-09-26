"""
Ecosystem statistics — everything, not only farms.

Privacy rule (see artifact): counts of organisations by type, public
marketplace provider profiles and listings need no consent (they are public on
the marketplace already). Private ledgers (production, finances, bookings
served) are aggregated only over consenting organisations. Nothing here names
an organisation.
"""
import graphene
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone

from apps.accounts.models import Organization
from apps.accounts import rbac
from .schema import _branch_scope

FARM_TYPES = ('farmer', 'cooperative')
TYPE_LABELS = dict(Organization.BUSINESS_TYPE_CHOICES)


def _geo_q(province, district):
    q = Q()
    if province:
        q &= Q(province__iexact=province.strip())
    if district:
        q &= Q(district__iexact=district.strip())
    return q


def _orgs(province=None, district=None):
    """All active private-sector organisations in scope — consenting or not (counts only)."""
    return Organization.objects.filter(org_type='farm', is_active=True).filter(_geo_q(province, district))


def _f(v):
    return float(v) if v is not None else 0.0


# ─── Types ────────────────────────────────────────────────────────────────────

class TypeCountType(graphene.ObjectType):
    business_type = graphene.String()
    label = graphene.String()
    total = graphene.Int()
    consenting = graphene.Int()
    districts = graphene.Int()


class EcoOverviewType(graphene.ObjectType):
    organisations = graphene.Int()
    farms = graphene.Int()
    vendors = graphene.Int()
    consenting = graphene.Int()
    consent_pct = graphene.Float()
    districts_covered = graphene.Int()
    provinces_covered = graphene.Int()
    marketplace_providers = graphene.Int()
    verified_providers = graphene.Int()
    active_listings = graphene.Int()
    hire_bookings_90d = graphene.Int()
    vet_appointments_90d = graphene.Int()
    programmes_active = graphene.Int()
    programme_participants = graphene.Int()
    programme_support_value = graphene.Float()
    by_type = graphene.List(TypeCountType)


class DistrictParticipantsType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    total = graphene.Int()
    consenting = graphene.Int()
    farms = graphene.Int()
    vendors = graphene.Int()
    counts = graphene.JSONString(description='{business_type: n}')


class ProviderStatType(graphene.ObjectType):
    provider_type = graphene.String()
    label = graphene.String()
    providers = graphene.Int()
    verified = graphene.Int()
    districts = graphene.Int()
    avg_rating = graphene.Float()
    services = graphene.Int()


class CoverageRowType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    farms = graphene.Int()
    vets = graphene.Int()
    dealers = graphene.Int()
    equipment_hire = graphene.Int()
    processors = graphene.Int()
    transport = graphene.Int()
    gaps = graphene.List(graphene.String)
    coverage_score = graphene.Int(description='0–5: how many of vet / dealer / hire / processor / transport are present')


class ProgrammeCoverageRowType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    programmes = graphene.Int()
    participants = graphene.Int()
    support_value = graphene.Float()
    partners = graphene.List(graphene.String)


class ProgrammeSummaryType(graphene.ObjectType):
    name = graphene.String()
    partner = graphene.String()
    partner_type = graphene.String()
    status = graphene.String()
    participants = graphene.Int()
    districts = graphene.Int()
    support_value = graphene.Float()
    target_participant_types = graphene.List(graphene.String)


class MarketActivityType(graphene.ObjectType):
    period_days = graphene.Int()
    hire_bookings = graphene.Int()
    hire_completed = graphene.Int()
    hire_value = graphene.Float()
    vet_appointments = graphene.Int()
    vet_completed = graphene.Int()
    listings_active = graphene.Int()
    listings_by_commodity = graphene.JSONString()
    contracts_fulfilled = graphene.Int()
    contracts_value = graphene.Float()


# ─── Queries ──────────────────────────────────────────────────────────────────

_GEO = dict(province=graphene.String(), district=graphene.String())


class EcosystemQuery(graphene.ObjectType):
    eco_overview = graphene.Field(EcoOverviewType, **_GEO)
    eco_participants_by_district = graphene.List(DistrictParticipantsType, **_GEO)
    eco_providers = graphene.List(ProviderStatType, **_GEO)
    eco_service_coverage = graphene.List(CoverageRowType, **_GEO)
    eco_programme_coverage = graphene.List(ProgrammeCoverageRowType, **_GEO)
    eco_programmes = graphene.List(ProgrammeSummaryType, **_GEO)
    eco_market_activity = graphene.Field(MarketActivityType, days=graphene.Int(), **_GEO)

    def resolve_eco_overview(self, info, province=None, district=None):
        from apps.market.provider_models import Provider, HireBooking, VetAppointment
        from apps.market.models import MarketListing
        from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport
        province, district = _branch_scope(info, province, district)
        orgs = _orgs(province, district)
        ids = list(orgs.values_list('id', flat=True))
        rows = orgs.values('business_type').annotate(n=Count('id'), c=Count('id', filter=Q(data_sharing_consent=True)),
                                                     d=Count('district', distinct=True))
        by_type = [TypeCountType(business_type=r['business_type'], label=TYPE_LABELS.get(r['business_type'], r['business_type']),
                                 total=r['n'], consenting=r['c'], districts=r['d']) for r in rows.order_by('-n')]
        total = sum(r.total for r in by_type)
        consenting = sum(r.consenting for r in by_type)
        farms = sum(r.total for r in by_type if r.business_type in FARM_TYPES)
        prov = Provider.objects.filter(status='active').filter(_geo_q(None, district)) if district else Provider.objects.filter(status='active')
        since = timezone.localdate() - timedelta(days=90)
        enr = ProgrammeEnrollment.objects.filter(farm_id__in=ids, status='active')
        prog_ids = enr.values_list('programme_id', flat=True).distinct()
        geo = orgs.values('province', 'district').distinct()
        return EcoOverviewType(
            organisations=total, farms=farms, vendors=total - farms, consenting=consenting,
            consent_pct=round(consenting / total * 100, 1) if total else 0.0,
            districts_covered=len({(g['province'], g['district']) for g in geo}), provinces_covered=len({g['province'] for g in geo if g['province']}),
            marketplace_providers=prov.count(), verified_providers=prov.filter(is_verified=True).count(),
            active_listings=MarketListing.objects.filter(organization_id__in=ids, status='active').count(),
            hire_bookings_90d=HireBooking.objects.filter(organization_id__in=ids, start_date__gte=since).count(),
            vet_appointments_90d=VetAppointment.objects.filter(organization_id__in=ids, appt_date__gte=since).count(),
            programmes_active=Programme.objects.filter(id__in=prog_ids, status='active').count(),
            programme_participants=enr.values('farm_id').distinct().count(),
            programme_support_value=_f(ProgrammeSupport.objects.filter(farm_id__in=ids).aggregate(v=Sum('value'))['v']),
            by_type=by_type,
        )

    def resolve_eco_participants_by_district(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        rows = _orgs(province, district).values('province', 'district', 'business_type').annotate(
            n=Count('id'), c=Count('id', filter=Q(data_sharing_consent=True)))
        acc = defaultdict(lambda: {'total': 0, 'consenting': 0, 'farms': 0, 'vendors': 0, 'counts': defaultdict(int)})
        for r in rows:
            k = (r['province'] or 'Unspecified', r['district'] or 'Unspecified')
            a = acc[k]
            a['total'] += r['n']; a['consenting'] += r['c']; a['counts'][r['business_type']] += r['n']
            if r['business_type'] in FARM_TYPES:
                a['farms'] += r['n']
            else:
                a['vendors'] += r['n']
        return [DistrictParticipantsType(province=k[0], district=k[1], total=v['total'], consenting=v['consenting'], farms=v['farms'],
                                         vendors=v['vendors'], counts=dict(v['counts'])) for k, v in sorted(acc.items())]

    def resolve_eco_providers(self, info, province=None, district=None):
        from apps.market.provider_models import Provider, PROVIDER_TYPE_CHOICES
        province, district = _branch_scope(info, province, district)
        qs = Provider.objects.filter(status='active')
        if district:
            qs = qs.filter(district__iexact=district)
        labels = dict(PROVIDER_TYPE_CHOICES)
        rows = qs.values('provider_type').annotate(n=Count('id'), v=Count('id', filter=Q(is_verified=True)), d=Count('district', distinct=True),
                                                    r=Avg('avg_rating'), s=Count('services', distinct=True)).order_by('-n')
        return [ProviderStatType(provider_type=r['provider_type'], label=labels.get(r['provider_type'], r['provider_type']), providers=r['n'],
                                 verified=r['v'], districts=r['d'], avg_rating=round(_f(r['r']), 2), services=r['s']) for r in rows]

    def resolve_eco_service_coverage(self, info, province=None, district=None):
        from apps.market.provider_models import Provider
        province, district = _branch_scope(info, province, district)
        rows = _orgs(province, district).values('province', 'district', 'business_type').annotate(n=Count('id'))
        acc = defaultdict(lambda: defaultdict(int))
        for r in rows:
            acc[(r['province'] or 'Unspecified', r['district'] or 'Unspecified')][r['business_type']] += r['n']
        # Marketplace providers count towards coverage too (public profiles)
        prov_map = {'vet_services': 'vet_provider', 'agro_dealer': 'agro_dealer', 'equipment_hire': 'equipment_hire', 'processing': 'processor', 'transport': 'transport'}
        for pr in Provider.objects.filter(status='active').exclude(district='').values('district', 'provider_type').annotate(n=Count('id')):
            key = next((k for k in acc if k[1].lower() == pr['district'].lower()), None)
            bt = prov_map.get(pr['provider_type'])
            if key and bt:
                acc[key][f'prov_{bt}'] += pr['n']
        out = []
        for (p, d), c in sorted(acc.items()):
            farms = c.get('farmer', 0) + c.get('cooperative', 0)
            vets = c.get('vet_provider', 0) + c.get('prov_vet_provider', 0)
            dealers = c.get('agro_dealer', 0) + c.get('prov_agro_dealer', 0) + c.get('agrisupply_provider', 0)
            hire = c.get('equipment_hire', 0) + c.get('prov_equipment_hire', 0)
            proc = c.get('processor', 0) + c.get('prov_processor', 0) + c.get('agrifood_seller', 0)
            trans = c.get('transport', 0) + c.get('prov_transport', 0)
            gaps = []
            if farms:
                if not vets: gaps.append('No veterinary service')
                if not dealers: gaps.append('No input dealer')
                if not hire: gaps.append('No equipment hire')
                if not proc: gaps.append('No processor / buyer')
                if not trans: gaps.append('No transport')
            score = sum(1 for x in (vets, dealers, hire, proc, trans) if x)
            out.append(CoverageRowType(province=p, district=d, farms=farms, vets=vets, dealers=dealers, equipment_hire=hire, processors=proc,
                                       transport=trans, gaps=gaps, coverage_score=score))
        return out

    def resolve_eco_programme_coverage(self, info, province=None, district=None):
        from apps.partners.models import ProgrammeEnrollment, ProgrammeSupport
        province, district = _branch_scope(info, province, district)
        ids = list(_orgs(province, district).values_list('id', flat=True))
        geo = {o['id']: (o['province'] or 'Unspecified', o['district'] or 'Unspecified') for o in Organization.objects.filter(id__in=ids).values('id', 'province', 'district')}
        acc = defaultdict(lambda: {'programmes': set(), 'participants': set(), 'support': 0.0, 'partners': set()})
        for e in ProgrammeEnrollment.objects.filter(farm_id__in=ids, status='active').select_related('programme__organization'):
            a = acc[geo[e.farm_id]]
            a['programmes'].add(e.programme_id); a['participants'].add(e.farm_id); a['partners'].add(e.programme.organization.name)
        for s in ProgrammeSupport.objects.filter(farm_id__in=ids).values('farm_id').annotate(v=Sum('value')):
            acc[geo[s['farm_id']]]['support'] += _f(s['v'])
        return [ProgrammeCoverageRowType(province=k[0], district=k[1], programmes=len(v['programmes']), participants=len(v['participants']),
                                         support_value=v['support'], partners=sorted(v['partners'])) for k, v in sorted(acc.items())]

    def resolve_eco_programmes(self, info, province=None, district=None):
        from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport
        province, district = _branch_scope(info, province, district)
        ids = set(_orgs(province, district).values_list('id', flat=True))
        out = []
        for p in Programme.objects.exclude(status='planning').select_related('organization'):
            enr = list(ProgrammeEnrollment.objects.filter(programme=p, status='active').values_list('farm_id', flat=True))
            in_scope = [i for i in enr if i in ids]
            if province or district:
                if not in_scope:
                    continue
            geo = Organization.objects.filter(id__in=in_scope or enr).values('province', 'district').distinct().count()
            out.append(ProgrammeSummaryType(
                name=p.name, partner=p.organization.name, partner_type=p.organization.org_type, status=p.status,
                participants=len(in_scope) if (province or district) else len(enr), districts=geo,
                support_value=_f(ProgrammeSupport.objects.filter(programme=p, farm_id__in=(in_scope or enr)).aggregate(v=Sum('value'))['v']),
                target_participant_types=p.target_participant_types or []))
        return out

    def resolve_eco_market_activity(self, info, days=90, province=None, district=None):
        from apps.market.provider_models import HireBooking, VetAppointment
        from apps.market.models import MarketListing, TradeContract
        province, district = _branch_scope(info, province, district)
        ids = list(_orgs(province, district).values_list('id', flat=True))
        since = timezone.localdate() - timedelta(days=days)
        hb = HireBooking.objects.filter(organization_id__in=ids, start_date__gte=since)
        va = VetAppointment.objects.filter(organization_id__in=ids, appt_date__gte=since)
        lst = MarketListing.objects.filter(organization_id__in=ids, status='active')
        tc = TradeContract.objects.filter(organization_id__in=ids, status='fulfilled', updated_at__date__gte=since)
        return MarketActivityType(
            period_days=days, hire_bookings=hb.count(), hire_completed=hb.filter(status='completed').count(),
            hire_value=_f(hb.aggregate(v=Sum('agreed_amount'))['v']),
            vet_appointments=va.count(), vet_completed=va.filter(status='completed').count(),
            listings_active=lst.count(), listings_by_commodity={r['commodity']: r['n'] for r in lst.values('commodity').annotate(n=Count('id')).order_by('-n')[:15]},
            contracts_fulfilled=tc.count(), contracts_value=_f(tc.aggregate(v=Sum('total_value'))['v']),
        )


# ─── National map (step 4) ────────────────────────────────────────────────────

from .geo import locate, ZAMBIA_CENTER  # noqa: E402


class EcoMapDistrictType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    lat = graphene.Float()
    lng = graphene.Float()
    approximate = graphene.Boolean(description='True when placed at the province centroid (district not in the gazetteer)')
    organisations = graphene.Int()
    farms = graphene.Int()
    vendors = graphene.Int()
    consenting = graphene.Int()
    counts = graphene.JSONString(description='{business_type: n}')
    coverage_score = graphene.Int()
    gaps = graphene.List(graphene.String)
    programmes = graphene.Int()
    participants = graphene.Int()
    support_value = graphene.Float()
    partners = graphene.List(graphene.String)
    hotspot_reports = graphene.Int(description='Disease / pest reports in the last 90 days (consenting farms only)')
    hotspot_categories = graphene.JSONString()
    stations = graphene.Int()
    providers = graphene.Int(description='Marketplace provider profiles in the district')


class EcoMapPointType(graphene.ObjectType):
    layer = graphene.String()
    label = graphene.String()
    kind = graphene.String()
    lat = graphene.Float()
    lng = graphene.Float()
    district = graphene.String()
    verified = graphene.Boolean()


class EcoMapType(graphene.ObjectType):
    center_lat = graphene.Float()
    center_lng = graphene.Float()
    districts = graphene.List(EcoMapDistrictType)
    points = graphene.List(EcoMapPointType)
    unplaced = graphene.Int(description='Organisations with no usable province / district')


def _round(v):
    return round(float(v), 2)  # ~1 km — enough to keep a station from pinpointing a farm


class EcosystemMapQuery(graphene.ObjectType):
    eco_map = graphene.Field(EcoMapType, **_GEO)

    def resolve_eco_map(self, info, province=None, district=None):
        from apps.market.provider_models import Provider
        from apps.partners.models import ProgrammeEnrollment, ProgrammeSupport
        from apps.vision.models import FarmerReport
        from apps.weather.models import WeatherStation
        province, district = _branch_scope(info, province, district)
        orgs = list(_orgs(province, district).values('id', 'province', 'district', 'business_type', 'data_sharing_consent'))

        cells = {}
        org_key = {}
        unplaced = 0
        for o in orgs:
            loc = locate(o['province'], o['district'])
            if not loc:
                unplaced += 1
                continue
            prov, dist, lat, lng, approx = loc
            key = (prov, dist or '')
            org_key[o['id']] = key
            c = cells.setdefault(key, dict(province=prov, district=dist or prov, lat=lat, lng=lng, approximate=approx, organisations=0, farms=0,
                                           vendors=0, consenting=0, counts=defaultdict(int), programmes=set(), participants=set(), support=0.0,
                                           partners=set(), hotspot=0, hotspot_cats=defaultdict(int), stations=0, providers=0, consenting_ids=[]))
            c['organisations'] += 1
            c['counts'][o['business_type']] += 1
            if o['business_type'] in FARM_TYPES:
                c['farms'] += 1
            else:
                c['vendors'] += 1
            if o['data_sharing_consent']:
                c['consenting'] += 1
                c['consenting_ids'].append(o['id'])

        ids = list(org_key)
        for e in ProgrammeEnrollment.objects.filter(farm_id__in=ids, status='active').select_related('programme__organization'):
            c = cells[org_key[e.farm_id]]
            c['programmes'].add(e.programme_id); c['participants'].add(e.farm_id); c['partners'].add(e.programme.organization.name)
        for s in ProgrammeSupport.objects.filter(farm_id__in=ids).values('farm_id').annotate(v=Sum('value')):
            cells[org_key[s['farm_id']]]['support'] += _f(s['v'])

        consenting_ids = [i for c in cells.values() for i in c['consenting_ids']]
        since = timezone.now() - timedelta(days=90)
        for r in FarmerReport.objects.filter(organization_id__in=consenting_ids, created_at__gte=since).exclude(category='success').values('organization_id', 'category'):
            c = cells[org_key[r['organization_id']]]
            c['hotspot'] += 1; c['hotspot_cats'][r['category']] += 1

        points = []
        for st in WeatherStation.objects.filter(organization_id__in=consenting_ids, latitude__isnull=False, longitude__isnull=False).values('organization_id', 'latitude', 'longitude'):
            c = cells[org_key[st['organization_id']]]
            c['stations'] += 1
            points.append(EcoMapPointType(layer='station', label='Weather station · ' + c['district'], kind='station', lat=_round(st['latitude']),
                                          lng=_round(st['longitude']), district=c['district'], verified=None))

        prov_qs = Provider.objects.filter(status='active')
        if district:
            prov_qs = prov_qs.filter(district__iexact=district)
        by_lower = {k[1].lower(): k for k in cells}
        for p in prov_qs.values('name', 'provider_type', 'district', 'latitude', 'longitude', 'is_verified'):
            key = by_lower.get((p['district'] or '').lower())
            if key:
                cells[key]['providers'] += 1
            lat, lng = p['latitude'], p['longitude']
            if lat is None or lng is None:
                loc = locate(None, p['district'])
                if not loc:
                    continue
                lat, lng = loc[2], loc[3]
            if province and not key:
                continue
            points.append(EcoMapPointType(layer='provider', label=p['name'], kind=p['provider_type'], lat=float(lat), lng=float(lng),
                                          district=p['district'], verified=p['is_verified']))

        # coverage score reuses the same rules as ecoServiceCoverage
        cov = {(r.province, r.district): r for r in EcosystemQuery.resolve_eco_service_coverage(self, info, province, district)}
        out = []
        for key, c in sorted(cells.items()):
            cr = next((v for k, v in cov.items() if k[1].lower() == c['district'].lower()), None)
            out.append(EcoMapDistrictType(
                province=c['province'], district=c['district'], lat=c['lat'], lng=c['lng'], approximate=c['approximate'],
                organisations=c['organisations'], farms=c['farms'], vendors=c['vendors'], consenting=c['consenting'], counts=dict(c['counts']),
                coverage_score=cr.coverage_score if cr else 0, gaps=cr.gaps if cr else [],
                programmes=len(c['programmes']), participants=len(c['participants']), support_value=c['support'], partners=sorted(c['partners']),
                hotspot_reports=c['hotspot'], hotspot_categories=dict(c['hotspot_cats']), stations=c['stations'], providers=c['providers']))
        return EcoMapType(center_lat=ZAMBIA_CENTER[0], center_lng=ZAMBIA_CENTER[1], districts=out, points=points, unplaced=unplaced)
