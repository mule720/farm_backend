"""
Government dashboard tests.

  1. Access: only gov_viewer / saas_admin can read gov_* queries.
  2. Consent: only farms with data_sharing_consent=True are aggregated.
  3. Geography: province / district filters narrow the scope.
  4. De-identification: no farm name or id ever appears in gov output.
  5. Consent mutation: director-only, farm-only.
  6. Advisory: fans out to members of consenting farms in scope only.
  7. Registration: gov_viewer registers into a government org.
"""
import json
from datetime import date

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import Organization, Profile
from apps.enterprises.models import Enterprise, EnterpriseBatch
from apps.production.models import ProductionRecord
from apps.vision.models import FarmerReport
from apps.market.models import CommodityPrice, MarketListing
from apps.notifications.models import Notification
from apps.government.models import Advisory
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}),
                                    content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_seq = [0]


def _farm(name, province, district, consent, category='crop'):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(
        name=name, slug=f'farm-{n}', org_type='farm', province=province, district=district,
        data_sharing_consent=consent,
    )
    director = Profile.objects.create_user(
        email=f'd{n}@farm.test', full_name=f'{name} Director', password='pw12345678',
        phone=f'0977{n:07d}', organization=org, role='director',
    )
    hand = Profile.objects.create_user(
        email=f'h{n}@farm.test', full_name=f'{name} Hand', password='pw12345678',
        phone=f'0966{n:07d}', organization=org, role='farmhand',
    )
    ent = Enterprise.objects.create(organization=org, name=f'{name} Ent', category=category,
                                    production_type='maize', created_by=director)
    batch = EnterpriseBatch.objects.create(organization=org, enterprise=ent, name='B1',
                                           start_date=date.today(), status='active', created_by=director)
    ProductionRecord.objects.create(organization=org, enterprise=ent, batch=batch,
                                    record_date=date.today(), record_type='harvest',
                                    data={'quantity': 100}, recorded_by=director)
    FarmerReport.objects.create(organization=org, enterprise=ent, category='crop_disease',
                                title='Leaf spot', submitted_by=director)
    CommodityPrice.objects.create(organization=org, commodity='Maize', market_name='Soweto',
                                  unit='kg', price=7.5, price_date=date.today())
    MarketListing.objects.create(organization=org, enterprise=ent, commodity='Maize',
                                 quantity_available=500, asking_price=8, status='active', created_by=director)
    return org, director, hand


def _gov(name='MoA Lusaka', province='Lusaka', district=''):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(name=name, slug=f'gov-{n}', org_type='government',
                                      province=province, district=district)
    viewer = Profile.objects.create_user(
        email=f'g{n}@gov.test', full_name='Gov Viewer', password='pw12345678',
        phone=f'0955{n:07d}', organization=org, role='gov_viewer', is_org_admin=True,
    )
    return org, viewer


OVERVIEW = """
query($province: String, $district: String) {
  govOverview(province: $province, district: $district) {
    farmsReporting farmsEligible totalEnterprises activeBatches records30d
    harvestRecords30d harvestQuantity30d unresolvedReports activeListings
    provincesCovered districtsCovered
  }
}"""

DISTRICTS = """
query { govDistrictSummary { province district farms enterprises activeBatches records30d unresolvedReports } }"""

PRICES = "query { govCommodityPrices { commodity unit latestPrice avgPrice30d samples30d } }"
SUPPLY = "query { govMarketSupply { commodity listings farms quantityAvailable avgAskingPrice } }"
HOTSPOTS = "query { govHotspots { province district category reports farms } }"
FILTERS = "query { govFilters { provinces districts { province district farms } } }"
TREND = "query { govProductionTrend(weeks: 4) { label records harvestRecords harvestQuantity reports } }"
MIX = "query { govEnterpriseMix { category enterprises activeBatches farms } }"


class GovAccessTest(TestCase):
    def setUp(self):
        self.farm, self.director, self.hand = _farm('Farm A', 'Lusaka', 'Chongwe', consent=True)
        self.gov_org, self.viewer = _gov()

    def test_anonymous_denied(self):
        r = _gql(None, OVERVIEW)
        self.assertTrue(r.errors and 'Not authenticated' in str(r.errors[0]))

    def test_farm_director_denied(self):
        r = _gql(self.director, OVERVIEW)
        self.assertTrue(r.errors and 'Permission denied' in str(r.errors[0]))

    def test_farmhand_denied_all_gov_queries(self):
        for q in (OVERVIEW, DISTRICTS, PRICES, SUPPLY, HOTSPOTS, FILTERS, TREND, MIX):
            r = _gql(self.hand, q)
            self.assertTrue(r.errors, f'expected denial for {q[:40]}')

    def test_gov_viewer_allowed(self):
        r = _gql(self.viewer, OVERVIEW)
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['govOverview']['farmsReporting'], 1)

    def test_saas_admin_allowed(self):
        admin = Profile.objects.create_user(email='admin@x.test', full_name='Admin', password='pw12345678',
                                            phone='0900000000', role='saas_admin')
        r = _gql(admin, OVERVIEW)
        self.assertIsNone(r.errors, r.errors)

    def test_gov_viewer_cannot_read_farm_scoped_data(self):
        """A gov_viewer's own org has no farm data; ordinary per-org resolvers stay empty."""
        r = _gql(self.viewer, 'query { enterprises { id name } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['enterprises'], [])


class GovConsentScopeTest(TestCase):
    def setUp(self):
        self.consenting, _, _ = _farm('Consenting', 'Lusaka', 'Chongwe', consent=True)
        self.private, _, _ = _farm('Private Farm', 'Lusaka', 'Chongwe', consent=False)
        self.other_prov, _, _ = _farm('Copper Farm', 'Copperbelt', 'Kitwe', consent=True, category='livestock')
        _, self.viewer = _gov()

    def test_only_consenting_farms_counted(self):
        d = _gql(self.viewer, OVERVIEW).data['govOverview']
        self.assertEqual(d['farmsReporting'], 2)
        self.assertEqual(d['farmsEligible'], 3)
        self.assertEqual(d['totalEnterprises'], 2)
        self.assertEqual(d['activeBatches'], 2)
        self.assertEqual(d['harvestRecords30d'], 2)
        self.assertAlmostEqual(d['harvestQuantity30d'], 200.0)
        self.assertEqual(d['unresolvedReports'], 2)
        self.assertEqual(d['activeListings'], 2)
        self.assertEqual(d['provincesCovered'], 2)
        self.assertEqual(d['districtsCovered'], 2)

    def test_consent_revocation_removes_farm_immediately(self):
        self.consenting.data_sharing_consent = False
        self.consenting.save()
        d = _gql(self.viewer, OVERVIEW).data['govOverview']
        self.assertEqual(d['farmsReporting'], 1)

    def test_province_filter(self):
        r = _gql(self.viewer, OVERVIEW, {'province': 'Copperbelt'})
        self.assertEqual(r.data['govOverview']['farmsReporting'], 1)
        r = _gql(self.viewer, OVERVIEW, {'province': 'lusaka'})  # case-insensitive
        self.assertEqual(r.data['govOverview']['farmsReporting'], 1)

    def test_district_filter_no_match(self):
        r = _gql(self.viewer, OVERVIEW, {'district': 'Mongu'})
        self.assertEqual(r.data['govOverview']['farmsReporting'], 0)

    def test_district_summary_excludes_private_farm(self):
        rows = _gql(self.viewer, DISTRICTS).data['govDistrictSummary']
        by = {(r['province'], r['district']): r for r in rows}
        self.assertEqual(by[('Lusaka', 'Chongwe')]['farms'], 1)   # private farm not counted
        self.assertEqual(by[('Copperbelt', 'Kitwe')]['farms'], 1)
        self.assertEqual(by[('Lusaka', 'Chongwe')]['records30d'], 1)

    def test_enterprise_mix(self):
        rows = _gql(self.viewer, MIX).data['govEnterpriseMix']
        cats = {r['category']: r for r in rows}
        self.assertEqual(set(cats), {'crop', 'livestock'})
        self.assertEqual(cats['crop']['activeBatches'], 1)

    def test_commodity_prices_and_supply(self):
        prices = _gql(self.viewer, PRICES).data['govCommodityPrices']
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]['samples30d'], 2)          # private farm's price excluded
        self.assertAlmostEqual(prices[0]['latestPrice'], 7.5)
        supply = _gql(self.viewer, SUPPLY).data['govMarketSupply']
        self.assertEqual(supply[0]['listings'], 2)
        self.assertAlmostEqual(supply[0]['quantityAvailable'], 1000.0)

    def test_hotspots(self):
        rows = _gql(self.viewer, HOTSPOTS).data['govHotspots']
        self.assertEqual(sum(r['reports'] for r in rows), 2)
        self.assertTrue(all(r['category'] == 'crop_disease' for r in rows))

    def test_trend_buckets_current_week(self):
        rows = _gql(self.viewer, TREND).data['govProductionTrend']
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]['harvestRecords'], 2)
        self.assertEqual(rows[-1]['reports'], 2)

    def test_filters_only_list_consenting_geography(self):
        d = _gql(self.viewer, FILTERS).data['govFilters']
        self.assertEqual(d['provinces'], ['Copperbelt', 'Lusaka'])
        self.assertEqual(sum(x['farms'] for x in d['districts']), 2)

    def test_output_never_contains_farm_identity(self):
        for q in (OVERVIEW, DISTRICTS, PRICES, SUPPLY, HOTSPOTS, FILTERS, TREND, MIX):
            blob = json.dumps(_gql(self.viewer, q).data)
            for org in (self.consenting, self.private, self.other_prov):
                self.assertNotIn(org.name, blob)
                self.assertNotIn(str(org.id), blob)


class ConsentMutationTest(TestCase):
    MUT = 'mutation($c: Boolean!) { setDataSharingConsent(consent: $c) { organization { dataSharingConsent dataSharingConsentedAt } } }'

    def setUp(self):
        self.farm, self.director, self.hand = _farm('Farm C', 'Southern', 'Choma', consent=False)
        _, self.viewer = _gov()

    def test_director_can_opt_in_and_out(self):
        r = _gql(self.director, self.MUT, {'c': True})
        self.assertIsNone(r.errors, r.errors)
        org = r.data['setDataSharingConsent']['organization']
        self.assertTrue(org['dataSharingConsent'])
        self.assertIsNotNone(org['dataSharingConsentedAt'])
        r = _gql(self.director, self.MUT, {'c': False})
        self.assertFalse(r.data['setDataSharingConsent']['organization']['dataSharingConsent'])
        self.assertIsNone(r.data['setDataSharingConsent']['organization']['dataSharingConsentedAt'])

    def test_farmhand_cannot_change_consent(self):
        r = _gql(self.hand, self.MUT, {'c': True})
        self.assertTrue(r.errors and 'Permission denied' in str(r.errors[0]))
        self.farm.refresh_from_db()
        self.assertFalse(self.farm.data_sharing_consent)

    def test_gov_viewer_cannot_consent_own_org(self):
        r = _gql(self.viewer, self.MUT, {'c': True})
        self.assertTrue(r.errors)


class AdvisoryTest(TestCase):
    MUT = """
    mutation($input: AdvisoryInput!) {
      issueAdvisory(input: $input) { advisory { id title farmsReached recipientsReached province district } }
    }"""

    def setUp(self):
        self.lsk, self.lsk_dir, self.lsk_hand = _farm('LSK Farm', 'Lusaka', 'Chongwe', consent=True)
        self.priv, self.priv_dir, _ = _farm('Private', 'Lusaka', 'Chongwe', consent=False)
        self.cb, self.cb_dir, _ = _farm('CB Farm', 'Copperbelt', 'Kitwe', consent=True, category='livestock')
        self.gov_org, self.viewer = _gov()

    def test_district_scoped_advisory_reaches_only_consenting_farms_in_scope(self):
        r = _gql(self.viewer, self.MUT, {'input': {
            'title': 'Armyworm alert', 'message': 'Scout fields now.',
            'category': 'disease', 'priority': 'critical', 'province': 'Lusaka', 'district': 'Chongwe'}})
        self.assertIsNone(r.errors, r.errors)
        a = r.data['issueAdvisory']['advisory']
        self.assertEqual(a['farmsReached'], 1)
        self.assertEqual(a['recipientsReached'], 2)  # director + farmhand of LSK Farm
        self.assertEqual(Notification.objects.filter(recipient=self.lsk_dir).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.lsk_hand).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.priv_dir).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.cb_dir).count(), 0)
        n = Notification.objects.get(recipient=self.lsk_dir)
        self.assertEqual(n.priority, 'critical')
        self.assertEqual(n.category, 'alert')
        self.assertIn('Chongwe', n.title)
        self.assertEqual(n.ref_id, a['id'])

    def test_national_advisory_with_enterprise_category(self):
        r = _gql(self.viewer, self.MUT, {'input': {
            'title': 'FMD vaccination', 'message': 'Report to district vet.',
            'category': 'programme', 'enterpriseCategory': 'livestock'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['issueAdvisory']['advisory']['farmsReached'], 1)
        self.assertEqual(Notification.objects.filter(recipient=self.cb_dir).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.lsk_dir).count(), 0)

    def test_farm_director_cannot_issue(self):
        r = _gql(self.lsk_dir, self.MUT, {'input': {'title': 'x', 'message': 'y'}})
        self.assertTrue(r.errors and 'Permission denied' in str(r.errors[0]))
        self.assertEqual(Advisory.objects.count(), 0)

    def test_invalid_category_rejected(self):
        r = _gql(self.viewer, self.MUT, {'input': {'title': 'x', 'message': 'y', 'category': 'nope'}})
        self.assertTrue(r.errors)

    def test_advisory_list_scoped_to_issuing_org(self):
        _gql(self.viewer, self.MUT, {'input': {'title': 'A1', 'message': 'm'}})
        _, other_viewer = _gov('MoA Copperbelt', 'Copperbelt')
        r = _gql(other_viewer, 'query { govAdvisories { title } }')
        self.assertEqual(r.data['govAdvisories'], [])
        r = _gql(self.viewer, 'query { govAdvisories { title issuedByName } }')
        self.assertEqual(r.data['govAdvisories'][0]['title'], 'A1')


class GovRegistrationTest(TestCase):
    REG = """
    mutation($input: RegisterInput!) {
      register(input: $input) { token user { role organization { orgType province district } } }
    }"""

    def test_gov_viewer_registers_into_government_org(self):
        r = _gql(None, self.REG, {'input': {
            'fullName': 'DACO Chongwe', 'password': 'strongpass99', 'phone': '+260955111222',
            'organizationName': 'Ministry of Agriculture — Chongwe', 'role': 'gov_viewer',
            'orgType': 'government', 'province': 'Lusaka', 'district': 'Chongwe'}})
        self.assertIsNone(r.errors, r.errors)
        u = r.data['register']['user']
        self.assertEqual(u['role'], 'gov_viewer')
        self.assertEqual(u['organization']['orgType'], 'government')
        self.assertEqual(u['organization']['district'], 'Chongwe')

    def test_gov_viewer_cannot_register_farm_org_type(self):
        r = _gql(None, self.REG, {'input': {
            'fullName': 'X', 'password': 'strongpass99', 'phone': '+260955111333',
            'organizationName': 'Sneaky', 'role': 'gov_viewer', 'orgType': 'farm'}})
        self.assertTrue(r.errors)

    def test_director_registration_stays_farm(self):
        r = _gql(None, self.REG, {'input': {
            'fullName': 'F', 'password': 'strongpass99', 'phone': '+260955111444',
            'organizationName': 'Real Farm', 'role': 'director', 'orgType': 'government'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['register']['user']['organization']['orgType'], 'farm')
