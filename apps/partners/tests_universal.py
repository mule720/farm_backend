"""Step 2 — government-run programmes + participant-type targeting (any consenting organisation)."""
import json

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile, Branch
from apps.accounts import rbac
from apps.enterprises.models import Enterprise
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [700]


def _biz(name, business_type, district='Chongwe', consent=True, category='crop'):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f'u-{_n[0]}', org_type='farm', business_type=business_type, province='Lusaka', district=district, data_sharing_consent=consent)
    d = Profile.objects.create_user(email=f'u{_n[0]}@t.test', full_name='D', password='pw12345678', phone=f'097{_n[0]:08d}', organization=org, role='director', is_org_admin=True)
    if business_type in ('farmer', 'cooperative'):
        Enterprise.objects.create(organization=org, name='E', category=category, production_type='maize', created_by=d)
    return org


def _gov_user(role, org=None, branch=None):
    _n[0] += 1
    org = org or Organization.objects.create(name=f'MoA {_n[0]}', slug=f'g-{_n[0]}', org_type='government', province='Lusaka')
    return Profile.objects.create_user(email=f'g{_n[0]}@t.test', full_name=role, password='pw12345678', phone=f'095{_n[0]:08d}', organization=org, role=role, is_org_admin=(role == 'gov_admin'), branch=branch)


CREATE = 'mutation($i: ProgrammeInput!) { createProgramme(input: $i) { programme { id targetParticipantTypes targetDistricts targetProvinces } } }'
ELIGIBLE = 'query($id: ID!) { programmeEligibleFarms(programmeId: $id) { name businessType } }'
ENROLL = 'mutation($p: ID!, $f: ID!) { enrollFarm(programmeId: $p, farmId: $f) { enrollmentId } }'


class GovernmentProgrammesTest(TestCase):
    def setUp(self):
        self.admin = _gov_user('gov_admin')
        self.gov = self.admin.organization
        self.viewer = _gov_user('gov_viewer', self.gov)
        self.sup = _gov_user('extension_supervisor', self.gov)
        self.officer = _gov_user('extension_officer', self.gov)
        self.farm = _biz('Chongwe Farm', 'farmer')
        self.vet = _biz('Chongwe Vets', 'vet_provider')
        self.dealer = _biz('Kafue Agro Dealer', 'agro_dealer', district='Kafue')
        self.private_vet = _biz('Private Vet', 'vet_provider', consent=False)

    def test_catalogue_and_roles(self):
        mods = {m for m, _, _ in rbac.modules_for('government')}
        self.assertTrue({'programmes', 'enrolment', 'support', 'me', 'notices'} <= mods)
        self.assertTrue(rbac.can(self.admin, 'programmes', 'create'))
        self.assertTrue(rbac.can(self.sup, 'enrolment', 'create'))
        self.assertTrue(rbac.can(self.viewer, 'programmes', 'view'))
        self.assertFalse(rbac.can(self.viewer, 'programmes', 'create'))
        self.assertFalse(rbac.can(self.officer, 'enrolment', 'create'))

    def test_gov_admin_runs_programme_enrolling_any_participant_type(self):
        r = _gql(self.admin, CREATE, {'i': {'name': 'FISP 2026/27', 'startDate': '2026-09-01', 'status': 'active', 'targetParticipantTypes': ['farmer', 'vet_provider', 'agro_dealer']}})
        self.assertIsNone(r.errors, r.errors)
        pid = r.data['createProgramme']['programme']['id']
        self.assertEqual(r.data['createProgramme']['programme']['targetParticipantTypes'], ['farmer', 'vet_provider', 'agro_dealer'])
        rows = {x['name']: x['businessType'] for x in _gql(self.admin, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']}
        self.assertEqual(rows, {'Chongwe Farm': 'farmer', 'Chongwe Vets': 'vet_provider', 'Kafue Agro Dealer': 'agro_dealer'})  # private vet excluded (no consent)
        for org in (self.vet, self.dealer):
            self.assertIsNone(_gql(self.admin, ENROLL, {'p': pid, 'f': str(org.id)}).errors)
        r = _gql(self.admin, 'query($id: ID!) { programmeEnrolledFarms(programmeId: $id) { name businessType } partnerProgramme(id: $id) { results { farmsEnrolled participantsByType } } }', {'id': pid})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual({x['businessType'] for x in r.data['programmeEnrolledFarms']}, {'vet_provider', 'agro_dealer'})
        self.assertEqual(json.loads(r.data['partnerProgramme']['results']['participantsByType']), {'vet_provider': 1, 'agro_dealer': 1})

    def test_targeting_by_participant_type_only(self):
        pid = _gql(self.admin, CREATE, {'i': {'name': 'Vet network', 'startDate': '2026-09-01', 'status': 'active', 'targetParticipantTypes': ['vet_provider']}}).data['createProgramme']['programme']['id']
        names = {x['name'] for x in _gql(self.admin, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']}
        self.assertEqual(names, {'Chongwe Vets'})
        self.assertTrue(_gql(self.admin, ENROLL, {'p': pid, 'f': str(self.farm.id)}).errors)  # not eligible
        self.assertTrue(_gql(self.admin, CREATE, {'i': {'name': 'X', 'startDate': '2026-09-01', 'targetParticipantTypes': ['spaceship']}}).errors)

    def test_empty_targeting_means_any_consenting_org(self):
        pid = _gql(self.admin, CREATE, {'i': {'name': 'Open', 'startDate': '2026-09-01', 'status': 'active'}}).data['createProgramme']['programme']['id']
        self.assertEqual(len(_gql(self.admin, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']), 3)

    def test_viewer_reads_supervisor_writes_officer_reads(self):
        pid = _gql(self.sup, CREATE, {'i': {'name': 'Sup prog', 'startDate': '2026-09-01', 'status': 'active'}}).data['createProgramme']['programme']['id']
        self.assertTrue(_gql(self.viewer, CREATE, {'i': {'name': 'V', 'startDate': '2026-09-01'}}).errors)
        self.assertIsNone(_gql(self.viewer, 'query { partnerProgrammes { id } }').errors)
        self.assertIsNone(_gql(self.officer, ELIGIBLE, {'id': pid}).errors)
        self.assertTrue(_gql(self.officer, ENROLL, {'p': pid, 'f': str(self.vet.id)}).errors)
        self.assertIsNone(_gql(self.sup, ENROLL, {'p': pid, 'f': str(self.vet.id)}).errors)
        # partner org cannot see the government's programme
        fao = Organization.objects.create(name='FAO', slug='fao-u', org_type='donor')
        pm = Profile.objects.create_user(email='pm@fao.u', full_name='PM', password='pw12345678', phone='0955999001', organization=fao, role='partner_manager')
        self.assertEqual(_gql(pm, 'query { partnerProgrammes { id } }').data['partnerProgrammes'], [])
        self.assertTrue(_gql(pm, ELIGIBLE, {'id': pid}).errors)

    def test_branch_member_programme_confined_to_district(self):
        b = Branch.objects.create(organization=self.gov, name='Chongwe DACO', kind='district', province='Lusaka', district='Chongwe')
        dsup = _gov_user('extension_supervisor', self.gov, branch=b)
        r = _gql(dsup, CREATE, {'i': {'name': 'District drive', 'startDate': '2026-09-01', 'status': 'active'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['createProgramme']['programme']['targetDistricts'], ['Chongwe'])
        pid = r.data['createProgramme']['programme']['id']
        names = {x['name'] for x in _gql(dsup, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']}
        self.assertEqual(names, {'Chongwe Farm', 'Chongwe Vets'})  # Kafue dealer excluded
        self.assertTrue(_gql(dsup, CREATE, {'i': {'name': 'Elsewhere', 'startDate': '2026-09-01', 'targetDistricts': ['Kafue']}}).errors)

    def test_vendor_support_types_and_report(self):
        pid = _gql(self.admin, CREATE, {'i': {'name': 'Cold chain', 'startDate': '2026-09-01', 'status': 'active'}}).data['createProgramme']['programme']['id']
        _gql(self.admin, ENROLL, {'p': pid, 'f': str(self.vet.id)})
        r = _gql(self.admin, 'mutation($i: SupportInput!) { recordSupport(input: $i) { support { supportType } } }',
                 {'i': {'programmeId': pid, 'farmId': str(self.vet.id), 'supportType': 'cold_chain', 'description': 'Vaccine fridge', 'value': 12000, 'deliveredOn': '2026-09-10'}})
        self.assertIsNone(r.errors, r.errors)
        from django.test import override_settings
        import tempfile, os
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp(), MEDIA_URL='/media/'):
            r = _gql(self.admin, 'mutation($id: ID!) { generateProgrammeReport(programmeId: $id) { url } }', {'id': pid})
            self.assertIsNone(r.errors, r.errors)
            self.assertTrue(r.data['generateProgrammeReport']['url'].endswith('.pdf'))
