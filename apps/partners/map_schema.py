"""
Step 5 — programme map: participants, support and still-eligible organisations
per district for one programme, plus the district gazetteer used by the
map-based targeting picker.
"""
import graphene
from collections import defaultdict

from django.db.models import Count, Sum

from apps.accounts.models import Organization
from apps.government.geo import DISTRICT_CENTROIDS, ZAMBIA_CENTER, locate
from .models import ProgrammeEnrollment, ProgrammeSupport
from .schema import _require_partner, _own_programme, _eligible_farms, _f


class GazetteerDistrictType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    lat = graphene.Float()
    lng = graphene.Float()


class ProgrammeMapDistrictType(graphene.ObjectType):
    province = graphene.String()
    district = graphene.String()
    lat = graphene.Float()
    lng = graphene.Float()
    approximate = graphene.Boolean()
    targeted = graphene.Boolean(description='District (or its province) is named in the programme targeting')
    participants = graphene.Int()
    participants_by_type = graphene.JSONString()
    support_events = graphene.Int()
    support_value = graphene.Float()
    eligible = graphene.Int(description='Consenting organisations matching the targeting that are not yet enrolled')
    eligible_by_type = graphene.JSONString()


class ProgrammeMapType(graphene.ObjectType):
    center_lat = graphene.Float()
    center_lng = graphene.Float()
    districts = graphene.List(ProgrammeMapDistrictType)
    unplaced_participants = graphene.Int()
    unplaced_eligible = graphene.Int()


class ProgrammeMapQuery(graphene.ObjectType):
    district_gazetteer = graphene.List(GazetteerDistrictType, province=graphene.String())
    programme_map = graphene.Field(ProgrammeMapType, programme_id=graphene.ID(required=True))

    def resolve_district_gazetteer(self, info, province=None):
        _require_partner(info)
        rows = [GazetteerDistrictType(province=p, district=d, lat=lat, lng=lng) for d, (p, lat, lng) in DISTRICT_CENTROIDS.items()
                if not province or p.lower() == province.strip().lower()]
        return sorted(rows, key=lambda r: (r.province, r.district))

    def resolve_programme_map(self, info, programme_id):
        user = _require_partner(info)
        p = _own_programme(user, programme_id)
        tp = {x.lower() for x in (p.target_provinces or [])}
        td = {x.lower() for x in (p.target_districts or [])}

        cells = {}
        unplaced_p = unplaced_e = 0

        def cell(o):
            loc = locate(o['province'], o['district'])
            if not loc:
                return None
            prov, dist, lat, lng, approx = loc
            key = (prov, (dist or prov).lower())
            return cells.setdefault(key, dict(province=prov, district=dist or prov, lat=lat, lng=lng, approximate=approx,
                                              targeted=(dist or '').lower() in td or (prov.lower() in tp and not td),
                                              participants=0, pbt=defaultdict(int), support_events=0, support_value=0.0,
                                              eligible=0, ebt=defaultdict(int), ids=[]))

        enrolled_ids = list(ProgrammeEnrollment.objects.filter(programme=p, status='active').values_list('farm_id', flat=True))
        for o in Organization.objects.filter(id__in=enrolled_ids).values('id', 'province', 'district', 'business_type'):
            c = cell(o)
            if not c:
                unplaced_p += 1
                continue
            c['participants'] += 1; c['pbt'][o['business_type']] += 1; c['ids'].append(o['id'])
        by_org = {r['farm_id']: r for r in ProgrammeSupport.objects.filter(programme=p).values('farm_id').annotate(n=Count('id'), v=Sum('value'))}
        for c in cells.values():
            for i in c['ids']:
                r = by_org.get(i)
                if r:
                    c['support_events'] += r['n']; c['support_value'] += _f(r['v'])
        for o in _eligible_farms(p).exclude(id__in=ProgrammeEnrollment.objects.filter(programme=p).values('farm_id')).values('id', 'province', 'district', 'business_type'):
            c = cell(o)
            if not c:
                unplaced_e += 1
                continue
            c['eligible'] += 1; c['ebt'][o['business_type']] += 1
        # explicitly targeted districts with nobody yet still appear (so the partner sees empty target areas)
        for d in (p.target_districts or []):
            loc = locate(None, d)
            if loc:
                cell({'province': loc[0], 'district': loc[1]})

        out = [ProgrammeMapDistrictType(province=c['province'], district=c['district'], lat=c['lat'], lng=c['lng'], approximate=c['approximate'],
                                        targeted=c['targeted'], participants=c['participants'], participants_by_type=dict(c['pbt']),
                                        support_events=c['support_events'], support_value=c['support_value'], eligible=c['eligible'],
                                        eligible_by_type=dict(c['ebt']))
               for _, c in sorted(cells.items())]
        return ProgrammeMapType(center_lat=ZAMBIA_CENTER[0], center_lng=ZAMBIA_CENTER[1], districts=out,
                                unplaced_participants=unplaced_p, unplaced_eligible=unplaced_e)
