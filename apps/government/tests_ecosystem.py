"""Step 3 — ecosystem statistics for government / partners."""
import json
from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile, Branch
from apps.market.models import MarketListing
from apps.market.provider_models import Provider, HireBooking, VetAppointment
from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [800]


def _org(name, bt, province, district, consent=True):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f'e-{_n[0]}', org_type='farm', business_type=bt, province=province, district=district, data_sharing_consent=consent)
    Profile.objects.create_user(email=f'e{_n[0]}@t.test', full_name='D', password='pw12345678', phone=f'097{_n[0]:08d}', organization=org, role='director', is_org_admin=True)
    return org


class EcosystemTest(TestCase):
    def setUp(self):
        gov = Organization.objects.create(name='MoA', slug='moa-e', org_type='government')
        self.admin = Profile.objects.create_user(email='a@e.test', full_name='A', password='pw12345678', phone='0955800001', organization=gov, role='gov_admin', is_org_admin=True)
        self.branch = Branch.objects.create(organization=gov, name='Chongwe DACO', kind='district', province='Lusaka', district='Chongwe')
        self.dviewer = Profile.objects.create_user(email='v@e.test', full_name='V', password='pw12345678', phone='0955800002', organization=gov, role='gov_viewer', branch=self.branch)
        fao = Organization.objects.create(name='FAO', slug='fao-e', org_type='donor')
        self.pm = Profile.objects.create_user(email='pm@e.test', full_name='PM', password='pw12345678', phone='0955800003', organization=fao, role='partner_manager')
        farmer = Organization.objects.create(name='F', slug='f-e', org_type='farm')
        self.farmer = Profile.objects.create_user(email='f@e.test', full_name='F', password='pw12345678', phone='0977800004', organization=farmer, role='director')

        self.f1 = _org('Chongwe Farm A', 'farmer', 'Lusaka', 'Chongwe')
        self.f2 = _org('Chongwe Farm B', 'farmer', 'Lusaka', 'Chongwe', consent=False)
        self.coop = _org('Chongwe Coop', 'cooperative', 'Lusaka', 'Chongwe')
        self.vet = _org('Chongwe Vets', 'vet_provider', 'Lusaka', 'Chongwe')
        self.dealer = _org('Kafue Dealer', 'agro_dealer', 'Lusaka', 'Kafue')
        self.kafue_farm = _org('Kafue Farm', 'farmer', 'Lusaka', 'Kafue')
        self.kitwe_farm = _org('Kitwe Farm', 'farmer', 'Copperbelt', 'Kitwe')
        MarketListing.objects.create(organization=self.f1, commodity='Maize', quantity_available=100, asking_price=5, status='active')
        MarketListing.objects.create(organization=self.dealer, commodity='Fertiliser', quantity_available=50, asking_price=400, status='active')
        prov = Provider.objects.create(provider_type='equipment_hire', name='Kafue Tractors', slug='kafue-tractors-e', district='Kafue', status='active', is_verified=True)
        HireBooking.objects.create(provider=prov, organization=self.kafue_farm, start_date=date.today(), end_date=date.today(), status='completed', agreed_amount=1500)
        vprov = Provider.objects.create(provider_type='vet_services', name='Mobile Vet', slug='mobile-vet-e', district='Kitwe', status='active')
        VetAppointment.objects.create(provider=vprov, organization=self.kitwe_farm, appt_type='consultation', appt_date=date.today(), status='completed')
        self.prog = Programme.objects.create(organization=fao, name='HiH', start_date=date.today(), status='active', created_by=self.pm)
        for o in (self.f1, self.vet):
            ProgrammeEnrollment.objects.create(programme=self.prog, farm=o, enrolled_by=self.pm)
        ProgrammeSupport.objects.create(programme=self.prog, farm=self.vet, support_type='cold_chain', description='fridge', value=12000, delivered_on=date.today(), created_by=self.pm)

    def test_access(self):
        q = 'query { ecoOverview { organisations } }'
        self.assertTrue(_gql(None, q).errors)
        self.assertTrue(_gql(self.farmer, q).errors)
        self.assertIsNone(_gql(self.pm, q).errors)  # partners see the ecosystem too
        self.assertIsNone(_gql(self.dviewer, q).errors)

    def test_overview_counts_everyone_not_only_consenting_farms(self):
        r = _gql(self.admin, 'query { ecoOverview { organisations farms vendors consenting consentPct districtsCovered marketplaceProviders verifiedProviders activeListings hireBookings90d vetAppointments90d programmesActive programmeParticipants programmeSupportValue byType { businessType total consenting } } }')
        self.assertIsNone(r.errors, r.errors)
        o = r.data['ecoOverview']
        self.assertEqual(o['organisations'], 8)  # 7 seeded here + the plain 'F' farm without geography
        self.assertEqual(o['vendors'], 2)
        self.assertEqual(o['farms'], 6)
        self.assertEqual(o['consenting'], 6)
        self.assertEqual(o['marketplaceProviders'], 2)
        self.assertEqual(o['verifiedProviders'], 1)
        self.assertEqual(o['activeListings'], 2)
        self.assertEqual(o['hireBookings90d'], 1)
        self.assertEqual(o['vetAppointments90d'], 1)
        self.assertEqual(o['programmesActive'], 1)
        self.assertEqual(o['programmeParticipants'], 2)
        self.assertAlmostEqual(o['programmeSupportValue'], 12000.0)
        bt = {x['businessType']: x for x in o['byType']}
        self.assertEqual(bt['vet_provider']['total'], 1)
        self.assertEqual(bt['farmer']['consenting'], 3)

    def test_farm_dashboards_exclude_vendors(self):
        r = _gql(self.admin, 'query { govOverview { farmsReporting } }')
        self.assertEqual(r.data['govOverview']['farmsReporting'], 4)  # f1, coop, kafue, kitwe: consenting farm types only; vet + dealer excluded

    def test_participants_by_district_and_branch_scope(self):
        r = _gql(self.admin, 'query { ecoParticipantsByDistrict { district total consenting farms vendors counts } }')
        rows = {x['district']: x for x in r.data['ecoParticipantsByDistrict']}
        self.assertEqual(rows['Chongwe']['total'], 4)
        self.assertEqual(rows['Chongwe']['vendors'], 1)
        self.assertEqual(json.loads(rows['Chongwe']['counts'])['farmer'], 2)
        # district-branch viewer is confined even when asking for Kafue
        r = _gql(self.dviewer, 'query { ecoParticipantsByDistrict(district: "Kafue") { district total } }')
        self.assertEqual([x['district'] for x in r.data['ecoParticipantsByDistrict']], ['Chongwe'])
        r = _gql(self.dviewer, 'query { govFilters { districts { district } } }')
        self.assertEqual([d['district'] for d in r.data['govFilters']['districts']], ['Chongwe'])

    def test_providers_and_coverage_gaps(self):
        r = _gql(self.admin, 'query { ecoProviders { providerType providers verified } ecoServiceCoverage { district farms vets dealers equipmentHire gaps coverageScore } }')
        self.assertIsNone(r.errors, r.errors)
        pv = {x['providerType']: x for x in r.data['ecoProviders']}
        self.assertEqual(pv['equipment_hire']['verified'], 1)
        cov = {x['district']: x for x in r.data['ecoServiceCoverage']}
        self.assertEqual(cov['Chongwe']['vets'], 1)
        self.assertIn('No input dealer', cov['Chongwe']['gaps'])
        self.assertEqual(cov['Kafue']['dealers'], 1)
        self.assertEqual(cov['Kafue']['equipmentHire'], 1)  # marketplace provider counts towards coverage
        self.assertIn('No veterinary service', cov['Kafue']['gaps'])
        self.assertEqual(cov['Kitwe']['vets'], 1)
        self.assertGreaterEqual(cov['Kafue']['coverageScore'], 2)

    def test_programme_coverage_and_market_activity(self):
        r = _gql(self.admin, 'query { ecoProgrammeCoverage { district programmes participants supportValue partners } ecoProgrammes { name partner participants targetParticipantTypes } ecoMarketActivity(days: 30) { hireBookings hireCompleted hireValue vetAppointments listingsActive listingsByCommodity contractsFulfilled } }')
        self.assertIsNone(r.errors, r.errors)
        pc = {x['district']: x for x in r.data['ecoProgrammeCoverage']}
        self.assertEqual(pc['Chongwe']['participants'], 2)
        self.assertEqual(pc['Chongwe']['partners'], ['FAO'])
        self.assertAlmostEqual(pc['Chongwe']['supportValue'], 12000.0)
        self.assertEqual(r.data['ecoProgrammes'][0]['participants'], 2)
        m = r.data['ecoMarketActivity']
        self.assertEqual(m['hireBookings'], 1)
        self.assertAlmostEqual(m['hireValue'], 1500.0)
        self.assertEqual(m['vetAppointments'], 1)
        self.assertEqual(json.loads(m['listingsByCommodity'])['Maize'], 1)
        # scoped to Kafue: only the tractor booking
        r = _gql(self.admin, 'query { ecoMarketActivity(district: "Kafue") { hireBookings vetAppointments listingsActive } }')
        self.assertEqual((r.data['ecoMarketActivity']['hireBookings'], r.data['ecoMarketActivity']['vetAppointments'], r.data['ecoMarketActivity']['listingsActive']), (1, 0, 1))


class NationalMapTest(EcosystemTest):
    def test_map_places_districts_and_layers(self):
        from apps.weather.models import WeatherStation
        from apps.vision.models import FarmerReport
        WeatherStation.objects.create(organization=self.f1, name='S1', latitude=-15.3312345, longitude=28.6812345)
        WeatherStation.objects.create(organization=self.f2, name='S2', latitude=-15.30, longitude=28.60)  # not consenting -> hidden
        FarmerReport.objects.create(organization=self.f1, category='pest', title='fall armyworm')
        FarmerReport.objects.create(organization=self.f2, category='disease', title='hidden: no consent')
        r = _gql(self.admin, 'query { ecoMap { centerLat unplaced districts { province district lat lng approximate organisations farms vendors consenting coverageScore gaps programmes participants supportValue partners hotspotReports hotspotCategories stations providers } points { layer label kind lat lng district verified } } }')
        self.assertIsNone(r.errors, r.errors)
        m = r.data['ecoMap']
        self.assertEqual(m['unplaced'], 1)  # the plain 'F' farm has no geography
        d = {x['district']: x for x in m['districts']}
        ch = d['Chongwe']
        self.assertEqual((ch['province'], ch['organisations'], ch['farms'], ch['vendors'], ch['consenting']), ('Lusaka', 4, 3, 1, 3))
        self.assertAlmostEqual(ch['lat'], -15.33); self.assertFalse(ch['approximate'])
        self.assertEqual(ch['programmes'], 1); self.assertEqual(ch['participants'], 2); self.assertEqual(ch['partners'], ['FAO'])
        self.assertEqual(ch['hotspotReports'], 1)  # non-consenting farm's report is not counted
        self.assertEqual(json.loads(ch['hotspotCategories']), {'pest': 1})
        self.assertEqual(ch['stations'], 1)
        self.assertIn('No input dealer', ch['gaps'])
        self.assertEqual(d['Kafue']['providers'], 1)
        self.assertEqual(d['Kafue']['coverageScore'], 2)
        pts = {(p['layer'], p['label']): p for p in m['points']}
        st = pts[('station', 'Weather station · Chongwe')]
        self.assertEqual((st['lat'], st['lng']), (-15.33, 28.68))  # rounded, never the exact farm point
        self.assertEqual(len([p for p in m['points'] if p['layer'] == 'station']), 1)
        kt = pts[('provider', 'Kafue Tractors')]
        self.assertTrue(kt['verified']); self.assertAlmostEqual(kt['lat'], -15.77)  # placed at district centroid when no coordinates

    def test_map_unknown_district_falls_back_to_province(self):
        _org('Nowhere Farm', 'farmer', 'Western', 'Imaginary')
        r = _gql(self.admin, 'query { ecoMap { districts { district province approximate lat } } }')
        row = next(x for x in r.data['ecoMap']['districts'] if x['district'] == 'Imaginary')
        self.assertTrue(row['approximate']); self.assertEqual(row['province'], 'Western'); self.assertAlmostEqual(row['lat'], -15.6)

    def test_map_branch_scope(self):
        r = _gql(self.dviewer, 'query { ecoMap { districts { district } points { layer } } }')
        self.assertEqual([x['district'] for x in r.data['ecoMap']['districts']], ['Chongwe'])
        self.assertEqual([p['layer'] for p in r.data['ecoMap']['points']], [])
