"""Business (participant) type persistence + vendor consent."""
import json

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


REG = 'mutation($i: RegisterInput!) { register(input: $i) { user { businessType orgType organization { businessType dataSharingConsent } } } }'


class BusinessTypeTest(TestCase):
    def test_register_defaults_to_farmer(self):
        r = _gql(None, REG, {'i': {'fullName': 'A', 'password': 'strongpass99', 'phone': '+260955100001', 'organizationName': 'Plain Farm'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['register']['user']['businessType'], 'farmer')

    def test_register_as_vendor(self):
        r = _gql(None, REG, {'i': {'fullName': 'V', 'password': 'strongpass99', 'phone': '+260955100002', 'organizationName': 'Chongwe Vets', 'businessType': 'vet_provider'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['register']['user']['organization']['businessType'], 'vet_provider')
        self.assertEqual(r.data['register']['user']['orgType'], 'farm')
        r = _gql(None, REG, {'i': {'fullName': 'X', 'password': 'strongpass99', 'phone': '+260955100003', 'organizationName': 'Bad', 'businessType': 'spaceship'}})
        self.assertTrue(r.errors)

    def test_onboarding_updates_type_and_vendor_can_consent(self):
        org = Organization.objects.create(name='Hire Co', slug='hire-co', org_type='farm')
        d = Profile.objects.create_user(email='d@hire.test', full_name='D', password='pw12345678', phone='0977100004', organization=org, role='director', is_org_admin=True)
        r = _gql(d, 'mutation { updateOrganization(input: {businessType: "equipment_hire"}) { organization { businessType } } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['updateOrganization']['organization']['businessType'], 'equipment_hire')
        r = _gql(d, 'mutation { setDataSharingConsent(consent: true) { organization { dataSharingConsent businessType } } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(r.data['setDataSharingConsent']['organization']['dataSharingConsent'])
        r = _gql(d, 'query { me { businessType } }')
        self.assertEqual(r.data['me']['businessType'], 'equipment_hire')

    def test_government_org_cannot_set_business_type(self):
        gov = Organization.objects.create(name='MoA', slug='moa-bt', org_type='government')
        a = Profile.objects.create_user(email='g@bt.test', full_name='G', password='pw12345678', phone='0955100005', organization=gov, role='gov_admin', is_org_admin=True)
        r = _gql(a, 'mutation { updateOrganization(input: {businessType: "agro_dealer"}) { organization { businessType } } }')
        self.assertTrue(r.errors)
