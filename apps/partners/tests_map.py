"""Step 5 — programme map + gazetteer + district-filtered eligibility."""
import json
from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [900]


def _org(name, bt, province, district, consent=True):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f'pm-{_n[0]}', org_type='farm', business_type=bt, province=province, district=district, data_sharing_consent=consent)
    Profile.objects.create_user(email=f'pm{_n[0]}@t.test', full_name='D', password='pw12345678', phone=f'096{_n[0]:08d}', organization=org, role='director', is_org_admin=True)
    return org


class ProgrammeMapTest(TestCase):
    def setUp(self):
        fao = Organization.objects.create(name='FAO', slug='fao-pm', org_type='donor')
        self.pm = Profile.objects.create_user(email='pm@pm.test', full_name='PM', password='pw12345678', phone='0955900001', organization=fao, role='partner_manager')
        other = Organization.objects.create(name='Other NGO', slug='ngo-pm', org_type='ngo')
        self.other = Profile.objects.create_user(email='o@pm.test', full_name='O', password='pw12345678', phone='0955900002', organization=other, role='partner_manager')
        farm = Organization.objects.create(name='F', slug='f-pm', org_type='farm')
        self.farmer = Profile.objects.create_user(email='f@pm.test', full_name='F', password='pw12345678', phone='0977900003', organization=farm, role='director')
        self.a = _org('Chongwe A', 'farmer', 'Lusaka', 'Chongwe')
        self.b = _org('Chongwe B', 'farmer', 'Lusaka', 'Chongwe')
        self.vet = _org('Chongwe Vet', 'vet_provider', 'Lusaka', 'Chongwe')
        self.k = _org('Kafue K', 'farmer', 'Lusaka', 'Kafue')
        self.nc = _org('Kafue no-consent', 'farmer', 'Lusaka', 'Kafue', consent=False)
        self.kitwe = _org('Kitwe farm', 'farmer', 'Copperbelt', 'Kitwe')
        self.nowhere = _org('No geo', 'farmer', '', '')
        self.p = Programme.objects.create(organization=fao, name='HiH', start_date=date.today(), status='active', created_by=self.pm,
                                          target_provinces=['Lusaka'], target_districts=['Chongwe', 'Kafue', 'Chilanga'], target_participant_types=['farmer'])
        ProgrammeEnrollment.objects.create(programme=self.p, farm=self.a, enrolled_by=self.pm)
        ProgrammeEnrollment.objects.create(programme=self.p, farm=self.nowhere, enrolled_by=self.pm)
        ProgrammeSupport.objects.create(programme=self.p, farm=self.a, support_type='seed', description='maize seed', value=800, delivered_on=date.today(), created_by=self.pm)
        ProgrammeSupport.objects.create(programme=self.p, farm=self.a, support_type='training', description='GAP', value=200, delivered_on=date.today(), created_by=self.pm)

    Q = 'query($id: ID!) { programmeMap(programmeId: $id) { centerLat unplacedParticipants unplacedEligible districts { province district lat approximate targeted participants participantsByType supportEvents supportValue eligible eligibleByType } } }'

    def test_access(self):
        self.assertTrue(_gql(None, self.Q, {'id': str(self.p.id)}).errors)
        self.assertTrue(_gql(self.farmer, self.Q, {'id': str(self.p.id)}).errors)
        self.assertTrue(_gql(self.other, self.Q, {'id': str(self.p.id)}).errors)  # not their programme
        self.assertIsNone(_gql(self.pm, self.Q, {'id': str(self.p.id)}).errors)

    def test_map_rows(self):
        r = _gql(self.pm, self.Q, {'id': str(self.p.id)})
        self.assertIsNone(r.errors, r.errors)
        m = r.data['programmeMap']
        self.assertEqual(m['unplacedParticipants'], 1)  # 'No geo' farm is enrolled but cannot be placed
        d = {x['district']: x for x in m['districts']}
        ch = d['Chongwe']
        self.assertTrue(ch['targeted'])
        self.assertEqual(ch['participants'], 1)
        self.assertEqual(json.loads(ch['participantsByType']), {'farmer': 1})
        self.assertEqual((ch['supportEvents'], ch['supportValue']), (2, 1000.0))
        self.assertEqual(ch['eligible'], 1)  # Chongwe B; the vet is excluded by participant type
        self.assertEqual(json.loads(ch['eligibleByType']), {'farmer': 1})
        kf = d['Kafue']
        self.assertEqual((kf['participants'], kf['eligible']), (0, 1))  # non-consenting farm is not eligible
        self.assertIn('Chilanga', d)  # targeted but empty district still drawn
        self.assertEqual((d['Chilanga']['participants'], d['Chilanga']['eligible']), (0, 0))
        self.assertTrue(d['Chilanga']['targeted'])
        self.assertNotIn('Kitwe', d)  # outside targeting -> neither eligible nor enrolled

    def test_gazetteer_and_district_filtered_eligibility(self):
        r = _gql(self.pm, 'query { districtGazetteer(province: "Lusaka") { province district lat lng } }')
        self.assertIsNone(r.errors, r.errors)
        names = [x['district'] for x in r.data['districtGazetteer']]
        self.assertIn('Chongwe', names); self.assertNotIn('Kitwe', names)
        self.assertTrue(len(_gql(self.pm, 'query { districtGazetteer { district } }').data['districtGazetteer']) > 100)
        self.assertTrue(_gql(self.farmer, 'query { districtGazetteer { district } }').errors)
        r = _gql(self.pm, 'query($id: ID!) { programmeEligibleFarms(programmeId: $id, district: "kafue") { name } }', {'id': str(self.p.id)})
        self.assertEqual([x['name'] for x in r.data['programmeEligibleFarms']], ['Kafue K'])
