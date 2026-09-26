"""
Government & partner dashboard — de-identified, aggregated GraphQL surface.

Every resolver here:
  * requires role gov_viewer (or saas_admin);
  * scopes to Organizations with org_type='farm' AND data_sharing_consent=True;
  * returns counts / sums only — never a farm name, member, or record body.

Farm names and IDs are deliberately absent from every output type. A
gov_viewer holds no organisation-scoped farm data of their own, so the
ordinary per-org resolvers elsewhere return nothing useful to them.
"""
import graphene
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum, Avg, Min, Max, Q
from django.utils import timezone
from graphene_django import DjangoObjectType

from apps.accounts.models import Organization, Profile
from apps.accounts import rbac
from .models import Advisory


# ─── Scope helpers ────────────────────────────────────────────────────────────

def _require_gov(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    # any government / partner role, or saas_admin
    if not user.has_role(*Profile.PARTNER_ROLES):
        raise Exception('Permission denied: government / partner access required')
    rbac.require_module(user, 'gov-dashboards', 'view')
    return user


def _branch_scope(info, province=None, district=None):
    """Members of a non-HQ branch are confined to the branch's geography."""
    user = _require_gov(info)
    bp, bd = rbac.branch_geo(user)
    if bd:
        return bp, bd
    if bp:
        return bp, district
    return province, district


FARM_TYPES = ('farmer', 'cooperative')


def _scope_orgs(province=None, district=None):
    """Consenting, active *farming* organisations (farms and cooperatives) inside the requested
    geography. Vendors are covered by the ecosystem statistics, not the production dashboards."""
    qs = Organization.objects.filter(org_type='farm', data_sharing_consent=True, is_active=True, business_type__in=FARM_TYPES)
    if province:
        qs = qs.filter(province__iexact=province.strip())
    if district:
        qs = qs.filter(district__iexact=district.strip())
    return qs


def _org_ids(province=None, district=None):
    return list(_scope_orgs(province, district).values_list('id', flat=True))


def _geo_of(org_ids):
    """Map org id → (province, district) for group-by-district rollups."""
    return {
        o['id']: (o['province'] or 'Unspecified', o['district'] or 'Unspecified')
        for o in Organization.objects.filter(id__in=org_ids).values('id', 'province', 'district')
    }


def _f(v):
    return float(v) if v is not None else 0.0


# ─── Output types ─────────────────────────────────────────────────────────────

class GovOverviewType(graphene.ObjectType):
    farms_reporting = graphene.Int()
    provinces_covered = graphene.Int()
    districts_covered = graphene.Int()
    total_enterprises = graphene.Int()
    active_batches = graphene.Int()
    records_30d = graphene.Int()
    harvest_records_30d = graphene.Int()
    harvest_quantity_30d = graphene.Float()
    open_critical_alerts = graphene.Int()
    unresolved_reports = graphene.Int()
    active_listings = graphene.Int()
    farms_eligible = graphene.Int(description='Active farm orgs on the platform, consenting or not')


class GovDistrictSummaryType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    farms = graphene.Int()
    enterprises = graphene.Int()
    active_batches = graphene.Int()
    records_30d = graphene.Int()
    open_alerts = graphene.Int()
    unresolved_reports = graphene.Int()


class GovEnterpriseMixType(graphene.ObjectType):
    category = graphene.String()
    enterprises = graphene.Int()
    active_batches = graphene.Int()
    farms = graphene.Int()


class GovTrendPointType(graphene.ObjectType):
    label = graphene.String()
    week_start = graphene.Date()
    records = graphene.Int()
    harvest_records = graphene.Int()
    harvest_quantity = graphene.Float()
    reports = graphene.Int()


class GovCommodityPriceType(graphene.ObjectType):
    commodity = graphene.String()
    unit = graphene.String()
    currency = graphene.String()
    latest_price = graphene.Float()
    latest_date = graphene.Date()
    avg_price_30d = graphene.Float()
    min_price_30d = graphene.Float()
    max_price_30d = graphene.Float()
    samples_30d = graphene.Int()


class GovMarketSupplyType(graphene.ObjectType):
    commodity = graphene.String()
    unit = graphene.String()
    listings = graphene.Int()
    farms = graphene.Int()
    quantity_available = graphene.Float()
    avg_asking_price = graphene.Float()


class GovHotspotType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    category = graphene.String()
    reports = graphene.Int()
    farms = graphene.Int()


class GovSeverityType(graphene.ObjectType):
    analysis_type = graphene.String()
    severity = graphene.String()
    count = graphene.Int()


class GovSustainabilityType(graphene.ObjectType):
    carbon_emissions_kg = graphene.Float()
    carbon_offsets_kg = graphene.Float()
    carbon_entries = graphene.Int()
    water_volume_m3 = graphene.Float()
    water_entries = graphene.Int()
    farms_with_certifications = graphene.Int()
    active_certifications = graphene.Int()


class GovDistrictOptionType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    farms = graphene.Int()


class GovFiltersType(graphene.ObjectType):
    provinces = graphene.List(graphene.String)
    districts = graphene.List(GovDistrictOptionType)


class AdvisoryType(DjangoObjectType):
    issued_by_name = graphene.String()

    class Meta:
        model = Advisory
        fields = ['id', 'title', 'message', 'category', 'priority', 'province', 'district',
                  'enterprise_category', 'farms_reached', 'recipients_reached', 'created_at']
        convert_choices_to_enum = False

    def resolve_issued_by_name(self, info):
        return self.issued_by.full_name if self.issued_by else None


# ─── Queries ──────────────────────────────────────────────────────────────────

_GEO_ARGS = dict(province=graphene.String(), district=graphene.String())


class GovernmentQuery(graphene.ObjectType):
    gov_overview = graphene.Field(GovOverviewType, **_GEO_ARGS)
    gov_district_summary = graphene.List(GovDistrictSummaryType, **_GEO_ARGS)
    gov_enterprise_mix = graphene.List(GovEnterpriseMixType, **_GEO_ARGS)
    gov_production_trend = graphene.List(GovTrendPointType, weeks=graphene.Int(), **_GEO_ARGS)
    gov_commodity_prices = graphene.List(GovCommodityPriceType, **_GEO_ARGS)
    gov_market_supply = graphene.List(GovMarketSupplyType, **_GEO_ARGS)
    gov_hotspots = graphene.List(GovHotspotType, days=graphene.Int(), **_GEO_ARGS)
    gov_diagnosis_severity = graphene.List(GovSeverityType, days=graphene.Int(), **_GEO_ARGS)
    gov_sustainability = graphene.Field(GovSustainabilityType, **_GEO_ARGS)
    gov_filters = graphene.Field(GovFiltersType)
    gov_advisories = graphene.List(AdvisoryType)

    # ── Overview ──────────────────────────────────────────────────────────
    def resolve_gov_overview(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.enterprises.models import Enterprise, EnterpriseBatch
        from apps.production.models import ProductionRecord
        from apps.devices.models import SecurityAlert
        from apps.vision.models import FarmerReport
        from apps.market.models import MarketListing

        orgs = _scope_orgs(province, district)
        ids = list(orgs.values_list('id', flat=True))
        since = timezone.localdate() - timedelta(days=30)

        harvest = ProductionRecord.objects.filter(
            organization_id__in=ids, record_type='harvest', record_date__gte=since
        ).values_list('data', flat=True)
        harvest_qty = 0.0
        harvest_n = 0
        for d in harvest:
            harvest_n += 1
            try:
                harvest_qty += float((d or {}).get('quantity') or 0)
            except (TypeError, ValueError):
                pass

        geo = orgs.values('province', 'district').distinct()
        return GovOverviewType(
            farms_reporting=len(ids),
            provinces_covered=len({g['province'] for g in geo if g['province']}),
            districts_covered=len({(g['province'], g['district']) for g in geo if g['district']}),
            total_enterprises=Enterprise.objects.filter(organization_id__in=ids, is_active=True).count(),
            active_batches=EnterpriseBatch.objects.filter(organization_id__in=ids, status='active').count(),
            records_30d=ProductionRecord.objects.filter(organization_id__in=ids, record_date__gte=since).count(),
            harvest_records_30d=harvest_n,
            harvest_quantity_30d=harvest_qty,
            open_critical_alerts=SecurityAlert.objects.filter(
                organization_id__in=ids, severity='critical', is_resolved=False).count(),
            unresolved_reports=FarmerReport.objects.filter(organization_id__in=ids, is_resolved=False).count(),
            active_listings=MarketListing.objects.filter(organization_id__in=ids, status='active').count(),
            farms_eligible=Organization.objects.filter(org_type='farm', is_active=True).count(),
        )

    # ── Registry by district (aggregated, no farm identities) ─────────────
    def resolve_gov_district_summary(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.enterprises.models import Enterprise, EnterpriseBatch
        from apps.production.models import ProductionRecord
        from apps.devices.models import SecurityAlert
        from apps.vision.models import FarmerReport

        ids = _org_ids(province, district)
        geo = _geo_of(ids)
        since = timezone.localdate() - timedelta(days=30)

        rows = defaultdict(lambda: dict(farms=0, enterprises=0, active_batches=0,
                                        records_30d=0, open_alerts=0, unresolved_reports=0))
        for oid, key in geo.items():
            rows[key]['farms'] += 1

        def _roll(qs, field):
            for r in qs.values('organization_id').annotate(n=Count('id')):
                key = geo.get(r['organization_id'])
                if key:
                    rows[key][field] += r['n']

        _roll(Enterprise.objects.filter(organization_id__in=ids, is_active=True), 'enterprises')
        _roll(EnterpriseBatch.objects.filter(organization_id__in=ids, status='active'), 'active_batches')
        _roll(ProductionRecord.objects.filter(organization_id__in=ids, record_date__gte=since), 'records_30d')
        _roll(SecurityAlert.objects.filter(organization_id__in=ids, is_resolved=False), 'open_alerts')
        _roll(FarmerReport.objects.filter(organization_id__in=ids, is_resolved=False), 'unresolved_reports')

        return [
            GovDistrictSummaryType(province=p, district=d, **vals)
            for (p, d), vals in sorted(rows.items())
        ]

    # ── Enterprise mix ────────────────────────────────────────────────────
    def resolve_gov_enterprise_mix(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.enterprises.models import Enterprise, EnterpriseBatch
        ids = _org_ids(province, district)

        ent = Enterprise.objects.filter(organization_id__in=ids, is_active=True) \
            .values('category').annotate(n=Count('id'), farms=Count('organization', distinct=True))
        batches = {
            r['enterprise__category']: r['n']
            for r in EnterpriseBatch.objects.filter(organization_id__in=ids, status='active')
            .values('enterprise__category').annotate(n=Count('id'))
        }
        return sorted(
            [GovEnterpriseMixType(category=r['category'], enterprises=r['n'],
                                  active_batches=batches.get(r['category'], 0), farms=r['farms'])
             for r in ent],
            key=lambda x: -x.enterprises,
        )

    # ── Weekly production trend ───────────────────────────────────────────
    def resolve_gov_production_trend(self, info, weeks=12, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.production.models import ProductionRecord
        from apps.vision.models import FarmerReport

        weeks = max(1, min(weeks or 12, 52))
        ids = _org_ids(province, district)
        today = timezone.localdate()
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)

        buckets = [dict(week_start=start + timedelta(weeks=i), records=0,
                        harvest_records=0, harvest_quantity=0.0, reports=0)
                   for i in range(weeks)]

        def _idx(d):
            i = (d - start).days // 7
            return i if 0 <= i < weeks else None

        for rec in ProductionRecord.objects.filter(
                organization_id__in=ids, record_date__gte=start).values('record_date', 'record_type', 'data'):
            i = _idx(rec['record_date'])
            if i is None:
                continue
            buckets[i]['records'] += 1
            if rec['record_type'] == 'harvest':
                buckets[i]['harvest_records'] += 1
                try:
                    buckets[i]['harvest_quantity'] += float((rec['data'] or {}).get('quantity') or 0)
                except (TypeError, ValueError):
                    pass

        for created in FarmerReport.objects.filter(
                organization_id__in=ids, created_at__date__gte=start).values_list('created_at', flat=True):
            i = _idx(created.date())
            if i is not None:
                buckets[i]['reports'] += 1

        return [GovTrendPointType(label=b['week_start'].strftime('%d %b'), **b) for b in buckets]

    # ── Commodity prices ──────────────────────────────────────────────────
    def resolve_gov_commodity_prices(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.market.models import CommodityPrice
        ids = _org_ids(province, district)
        since = timezone.localdate() - timedelta(days=30)

        stats = {
            (r['commodity'], r['unit'], r['currency']): r
            for r in CommodityPrice.objects.filter(organization_id__in=ids, price_date__gte=since)
            .values('commodity', 'unit', 'currency')
            .annotate(avg=Avg('price'), lo=Min('price'), hi=Max('price'), n=Count('id'))
        }
        out = []
        seen = set()
        # Latest price per commodity/unit/currency from all history (not just 30d)
        for r in CommodityPrice.objects.filter(organization_id__in=ids) \
                .order_by('commodity', 'unit', 'currency', '-price_date', '-created_at') \
                .values('commodity', 'unit', 'currency', 'price', 'price_date'):
            key = (r['commodity'], r['unit'], r['currency'])
            if key in seen:
                continue
            seen.add(key)
            s = stats.get(key, {})
            out.append(GovCommodityPriceType(
                commodity=r['commodity'], unit=r['unit'], currency=r['currency'],
                latest_price=_f(r['price']), latest_date=r['price_date'],
                avg_price_30d=_f(s.get('avg')), min_price_30d=_f(s.get('lo')),
                max_price_30d=_f(s.get('hi')), samples_30d=s.get('n', 0),
            ))
        return out

    # ── Marketplace supply ────────────────────────────────────────────────
    def resolve_gov_market_supply(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.market.models import MarketListing
        ids = _org_ids(province, district)
        rows = MarketListing.objects.filter(organization_id__in=ids, status='active') \
            .values('commodity', 'unit') \
            .annotate(n=Count('id'), farms=Count('organization', distinct=True),
                      qty=Sum('quantity_available'), avg=Avg('asking_price')) \
            .order_by('-qty')
        return [GovMarketSupplyType(commodity=r['commodity'], unit=r['unit'], listings=r['n'],
                                    farms=r['farms'], quantity_available=_f(r['qty']),
                                    avg_asking_price=_f(r['avg'])) for r in rows]

    # ── Disease / pest hotspots ───────────────────────────────────────────
    def resolve_gov_hotspots(self, info, days=90, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.vision.models import FarmerReport
        ids = _org_ids(province, district)
        geo = _geo_of(ids)
        since = timezone.now() - timedelta(days=max(1, min(days or 90, 365)))

        agg = defaultdict(lambda: dict(reports=0, farms=set()))
        for r in FarmerReport.objects.filter(organization_id__in=ids, created_at__gte=since) \
                .exclude(category='success').values('organization_id', 'category'):
            key = geo.get(r['organization_id'])
            if not key:
                continue
            a = agg[(key[0], key[1], r['category'])]
            a['reports'] += 1
            a['farms'].add(r['organization_id'])

        return sorted(
            [GovHotspotType(province=p, district=d, category=c, reports=v['reports'], farms=len(v['farms']))
             for (p, d, c), v in agg.items()],
            key=lambda x: -x.reports,
        )

    # ── AI diagnosis severity distribution ────────────────────────────────
    def resolve_gov_diagnosis_severity(self, info, days=90, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.vision.models import AIVisionAnalysis
        ids = _org_ids(province, district)
        since = timezone.now() - timedelta(days=max(1, min(days or 90, 365)))
        rows = AIVisionAnalysis.objects.filter(organization_id__in=ids, created_at__gte=since) \
            .values('analysis_type', 'severity').annotate(n=Count('id')).order_by('analysis_type')
        return [GovSeverityType(analysis_type=r['analysis_type'], severity=r['severity'], count=r['n'])
                for r in rows]

    # ── Sustainability rollup ─────────────────────────────────────────────
    def resolve_gov_sustainability(self, info, province=None, district=None):
        province, district = _branch_scope(info, province, district)
        from apps.sustainability.models import CarbonEntry, WaterUsageEntry, CertificationRecord
        ids = _org_ids(province, district)

        carbon = CarbonEntry.objects.filter(organization_id__in=ids).aggregate(
            emissions=Sum('co2e_kg', filter=Q(entry_type='emission')),
            offsets=Sum('co2e_kg', filter=Q(entry_type='offset')),
            n=Count('id'),
        )
        water = WaterUsageEntry.objects.filter(organization_id__in=ids).aggregate(
            volume=Sum('volume_m3'), n=Count('id'))
        certs = CertificationRecord.objects.filter(organization_id__in=ids, status='certified')
        return GovSustainabilityType(
            carbon_emissions_kg=_f(carbon['emissions']),
            carbon_offsets_kg=_f(carbon['offsets']),
            carbon_entries=carbon['n'],
            water_volume_m3=_f(water['volume']),
            water_entries=water['n'],
            farms_with_certifications=certs.values('organization').distinct().count(),
            active_certifications=certs.count(),
        )

    # ── Filter options ────────────────────────────────────────────────────
    def resolve_gov_filters(self, info):
        province, district = _branch_scope(info)
        rows = _scope_orgs(province, district).values('province', 'district').annotate(n=Count('id')).order_by('province', 'district')
        provinces = sorted({r['province'] for r in rows if r['province']})
        districts = [GovDistrictOptionType(province=r['province'] or 'Unspecified',
                                           district=r['district'] or 'Unspecified', farms=r['n'])
                     for r in rows]
        return GovFiltersType(provinces=provinces, districts=districts)

    # ── Advisories issued by this gov org ─────────────────────────────────
    def resolve_gov_advisories(self, info):
        user = _require_gov(info)
        return Advisory.objects.filter(organization=user.organization).select_related('issued_by')


# ─── Mutations ────────────────────────────────────────────────────────────────

class AdvisoryInput(graphene.InputObjectType):
    title = graphene.String(required=True)
    message = graphene.String(required=True)
    category = graphene.String()
    priority = graphene.String()
    province = graphene.String()
    district = graphene.String()
    enterprise_category = graphene.String()


_NOTIF_CATEGORY = {'weather': 'weather', 'disease': 'alert', 'market': 'market',
                   'programme': 'system', 'general': 'system'}


class IssueAdvisory(graphene.Mutation):
    """Broadcast an advisory to every member of every consenting farm in scope."""

    class Arguments:
        input = AdvisoryInput(required=True)

    advisory = graphene.Field(AdvisoryType)

    def mutate(self, info, input):
        from apps.notifications.models import Notification
        from apps.enterprises.models import Enterprise

        user = _require_gov(info)
        if user.organization is None:
            raise Exception('Government account has no organisation')

        category = (input.get('category') or 'general').strip()
        priority = (input.get('priority') or 'info').strip()
        if category not in dict(Advisory.CATEGORY_CHOICES):
            raise Exception('Invalid advisory category')
        if priority not in dict(Advisory.PRIORITY_CHOICES):
            raise Exception('Invalid advisory priority')

        province = (input.get('province') or '').strip()
        district = (input.get('district') or '').strip()
        ent_cat = (input.get('enterprise_category') or '').strip()
        rbac.require_module(user, 'advisories', 'create')
        # Branch members broadcast inside their branch; extension officers inside their working area.
        bp, bd = rbac.branch_geo(user)
        if bd or bp:
            province, district = bp or province, bd or ''
        elif user.role in rbac.EXTENSION_ROLES:
            org = user.organization
            if org.district:
                province, district = org.province, org.district
            elif org.province:
                province, district = org.province, ''
            else:
                raise Exception('Your organisation has no province / district set; ask a coordinator to set it')

        orgs = _scope_orgs(province or None, district or None)
        if ent_cat:
            orgs = orgs.filter(id__in=Enterprise.objects.filter(
                category=ent_cat, is_active=True).values('organization_id'))
        org_ids = list(orgs.values_list('id', flat=True))

        with transaction.atomic():
            advisory = Advisory.objects.create(
                organization=user.organization, issued_by=user,
                title=input.title.strip(), message=input.message.strip(),
                category=category, priority=priority,
                province=province, district=district, enterprise_category=ent_cat,
            )
            recipients = Profile.objects.filter(organization_id__in=org_ids, is_active=True)
            scope_label = district or province or 'National'
            Notification.objects.bulk_create([
                Notification(
                    recipient=p,
                    title=f'[{scope_label}] {advisory.title}',
                    message=f'{advisory.message}\n\n— {user.organization.name}',
                    category=_NOTIF_CATEGORY[category],
                    priority=priority,
                    action_url='/notifications',
                    ref_id=str(advisory.id),
                ) for p in recipients
            ])
            advisory.farms_reached = len(org_ids)
            advisory.recipients_reached = recipients.count()
            advisory.save(update_fields=['farms_reached', 'recipients_reached'])
        return IssueAdvisory(advisory=advisory)


class GovernmentMutation(graphene.ObjectType):
    issue_advisory = IssueAdvisory.Field()
