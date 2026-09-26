"""
Supporting partner (FAO / donor / NGO) programme tests.

  1. Access: partner_manager only; must sit in a partner org; programmes are
     scoped to the owning organisation.
  2. Programme CRUD + validation (status, dates, indicators).
  3. Eligibility: consenting + targeting (province / district / category).
  4. Enrolment (notifies farm; idempotent re-enrol; closed programme blocks).
  5. Support ledger + notification; only for actively enrolled farms.
  6. Live results + indicator progress; district rollup; notices.
  7. Farmer sees own programmes and support only.
"""
import json
from datetime import date, timedelta

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import Organization, Profile
from apps.enterprises.models import Enterprise, EnterpriseBatch
from apps.production.models import ProductionRecord
from apps.notifications.models import Notification
from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport, IndicatorReading
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_seq = [500]


def _farm(name, province, district, consent=True, category='crop'):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(name=name, slug=f'pfarm-{n}', org_type='farm', province=province,
                                      district=district, data_sharing_consent=consent)
    d = Profile.objects.create_user(email=f'pd{n}@farm.test', full_name=f'{name} Director', password='pw12345678',
                                    phone=f'0977{n:07d}', organization=org, role='director')
    ent = Enterprise.objects.create(organization=org, name=f'{name} ent', category=category, production_type='maize', created_by=d)
    b = EnterpriseBatch.objects.create(organization=org, enterprise=ent, name='B', start_date=date.today(), status='active', created_by=d)
    ProductionRecord.objects.create(organization=org, enterprise=ent, batch=b, record_date=date.today(),
                                    record_type='harvest', data={'quantity': 250}, recorded_by=d)
    return org, d


def _partner(name='FAO Zambia', org_type='donor'):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(name=name, slug=f'partner-{n}', org_type=org_type)
    return org, Profile.objects.create_user(email=f'pm{n}@fao.test', full_name=f'{name} PM', password='pw12345678',
                                            phone=f'0955{n:07d}', organization=org, role='partner_manager')


CREATE = """mutation($input: ProgrammeInput!) { createProgramme(input: $input) { programme { id name status targetFarms indicators { key target } } } }"""
PROGS = """query { partnerProgrammes { id name status results { farmsEnrolled supportValue enrolmentPct } } }"""
ELIGIBLE = """query($id: ID!) { programmeEligibleFarms(programmeId: $id) { farmId name district } }"""
ENROLL = """mutation($p: ID!, $f: ID!, $c: String) { enrollFarm(programmeId: $p, farmId: $f, cohort: $c) { enrollmentId } }"""
ENROLLED = """query($id: ID!) { programmeEnrolledFarms(programmeId: $id) { farmId name status cohort harvestQuantitySinceStart supportEvents supportValue } }"""
SUPPORT = """mutation($input: SupportInput!) { recordSupport(input: $input) { support { id farmName supportType value } } }"""
DETAIL = """query($id: ID!) { partnerProgramme(id: $id) { name results { farmsEnrolled farmsActive districts harvestQuantitySinceStart supportEvents supportValue farmsSupported budgetUsedPct enrolmentPct } indicatorStatus { key target latestValue progressPct } } }"""


def _create(user, **over):
    inp = {'name': 'Hand-in-Hand Zambia', 'funder': 'FAO', 'startDate': str(date.today() - timedelta(days=30)),
           'budget': 100000, 'currency': 'USD', 'targetFarms': 4, 'status': 'active',
           'targetProvinces': ['Lusaka'],
           'indicators': [{'key': 'yield', 'label': 'Maize yield', 'unit': 't/ha', 'target': 3.5},
                          {'key': 'income', 'label': 'HH income', 'unit': 'ZMW', 'target': 12000}]}
    inp.update(over)
    r = _gql(user, CREATE, {'input': inp})
    assert r.errors is None, r.errors
    return r.data['createProgramme']['programme']['id']


class PartnerAccessTest(TestCase):
    def setUp(self):
        self.farm, self.director = _farm('Farm A', 'Lusaka', 'Chongwe')
        self.org, self.pm = _partner()
        self.other_org, self.other_pm = _partner('WFP', 'ngo')
        gov = Organization.objects.create(name='MoA', slug='moa-p', org_type='government')
        self.viewer = Profile.objects.create_user(email='gv@moa.test', full_name='GV', password='pw12345678',
                                                  phone='0955000099', organization=gov, role='gov_viewer')

    def test_anonymous_farmer_denied_gov_viewer_read_only(self):
        for u in (None, self.director):
            self.assertTrue(_gql(u, PROGS).errors, f'expected denial for {u}')
        # Government roles read programmes (step 2: government runs programmes too); a viewer cannot create
        self.assertIsNone(_gql(self.viewer, PROGS).errors)
        self.assertTrue(_gql(self.viewer, CREATE, {'input': {'name': 'X', 'startDate': '2026-01-01'}}).errors)

    def test_partner_manager_in_farm_org_rejected(self):
        bad = Profile.objects.create_user(email='bad@farm.test', full_name='B', password='pw12345678',
                                          phone='0955000098', organization=self.farm, role='partner_manager')
        self.assertTrue('partner organisation' in str(_gql(bad, PROGS).errors[0]))

    def test_programmes_scoped_to_own_org(self):
        pid = _create(self.pm)
        self.assertEqual(len(_gql(self.pm, PROGS).data['partnerProgrammes']), 1)
        self.assertEqual(_gql(self.other_pm, PROGS).data['partnerProgrammes'], [])
        self.assertTrue(_gql(self.other_pm, DETAIL, {'id': pid}).errors)
        self.assertTrue(_gql(self.other_pm, ENROLL, {'p': pid, 'f': str(self.farm.id)}).errors)

    def test_partner_manager_sees_gov_aggregates(self):
        r = _gql(self.pm, 'query { govOverview { farmsReporting } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['govOverview']['farmsReporting'], 1)


class ProgrammeValidationTest(TestCase):
    def setUp(self):
        _, self.pm = _partner()

    def test_requires_name_and_start(self):
        self.assertTrue(_gql(self.pm, CREATE, {'input': {'startDate': '2026-01-01'}}).errors)
        self.assertTrue(_gql(self.pm, CREATE, {'input': {'name': 'X'}}).errors)

    def test_invalid_status_and_dates(self):
        r = _gql(self.pm, CREATE, {'input': {'name': 'X', 'startDate': '2026-01-01', 'status': 'bogus'}})
        self.assertTrue(r.errors)
        r = _gql(self.pm, CREATE, {'input': {'name': 'X', 'startDate': '2026-06-01', 'endDate': '2026-01-01'}})
        self.assertTrue('End date' in str(r.errors[0]))

    def test_duplicate_indicator_keys_rejected(self):
        r = _gql(self.pm, CREATE, {'input': {'name': 'X', 'startDate': '2026-01-01',
                                             'indicators': [{'key': 'a', 'label': 'A'}, {'key': 'a', 'label': 'B'}]}})
        self.assertTrue(r.errors)

    def test_update(self):
        pid = _create(self.pm)
        r = _gql(self.pm, 'mutation($id: ID!, $i: ProgrammeInput!) { updateProgramme(id: $id, input: $i) { programme { status budget targetDistricts } } }',
                 {'id': pid, 'i': {'status': 'suspended', 'budget': 250000, 'targetDistricts': ['Chongwe', ' Kafue ']}})
        self.assertIsNone(r.errors, r.errors)
        p = r.data['updateProgramme']['programme']
        self.assertEqual(p['status'], 'suspended')
        self.assertEqual(float(p['budget']), 250000)
        self.assertEqual(p['targetDistricts'], ['Chongwe', 'Kafue'])


class EligibilityAndEnrolmentTest(TestCase):
    def setUp(self):
        self.lsk_crop, self.lsk_dir = _farm('Lusaka Crop', 'Lusaka', 'Chongwe')
        self.lsk_live, _ = _farm('Lusaka Livestock', 'Lusaka', 'Kafue', category='livestock')
        self.lsk_private, self.priv_dir = _farm('Lusaka Private', 'Lusaka', 'Chongwe', consent=False)
        self.cb_crop, _ = _farm('Copperbelt Crop', 'Copperbelt', 'Kitwe')
        _, self.pm = _partner()

    def test_eligibility_by_province(self):
        pid = _create(self.pm)
        names = {f['name'] for f in _gql(self.pm, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']}
        self.assertEqual(names, {'Lusaka Crop', 'Lusaka Livestock'})

    def test_eligibility_by_district_and_category(self):
        pid = _create(self.pm, targetProvinces=[], targetDistricts=['chongwe', 'Kafue'], targetEnterpriseCategories=['crop'])
        names = {f['name'] for f in _gql(self.pm, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']}
        self.assertEqual(names, {'Lusaka Crop'})

    def test_no_targeting_means_all_consenting(self):
        pid = _create(self.pm, targetProvinces=[])
        self.assertEqual(len(_gql(self.pm, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']), 3)

    def test_enroll_notifies_and_removes_from_eligible(self):
        pid = _create(self.pm)
        r = _gql(self.pm, ENROLL, {'p': pid, 'f': str(self.lsk_crop.id), 'c': 'Season A'})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(Notification.objects.filter(recipient=self.lsk_dir, title__startswith='Enrolled in').count(), 1)
        self.assertNotIn('Lusaka Crop', {f['name'] for f in _gql(self.pm, ELIGIBLE, {'id': pid}).data['programmeEligibleFarms']})
        rows = _gql(self.pm, ENROLLED, {'id': pid}).data['programmeEnrolledFarms']
        self.assertEqual(rows[0]['cohort'], 'Season A')
        self.assertAlmostEqual(rows[0]['harvestQuantitySinceStart'], 250.0)

    def test_enroll_ineligible_rejected(self):
        pid = _create(self.pm)
        for farm in (self.lsk_private, self.cb_crop):
            r = _gql(self.pm, ENROLL, {'p': pid, 'f': str(farm.id)})
            self.assertTrue(r.errors and 'not eligible' in str(r.errors[0]))
        self.assertEqual(ProgrammeEnrollment.objects.count(), 0)

    def test_double_enroll_rejected_and_withdraw_reenroll(self):
        pid = _create(self.pm)
        r = _gql(self.pm, ENROLL, {'p': pid, 'f': str(self.lsk_crop.id)})
        eid = r.data['enrollFarm']['enrollmentId']
        self.assertTrue('already enrolled' in str(_gql(self.pm, ENROLL, {'p': pid, 'f': str(self.lsk_crop.id)}).errors[0]))
        r = _gql(self.pm, 'mutation($e: ID!) { updateEnrollment(enrollmentId: $e, status: "withdrawn") { ok } }', {'e': eid})
        self.assertTrue(r.data['updateEnrollment']['ok'])
        self.assertEqual(_gql(self.pm, ENROLLED, {'id': pid}).data['programmeEnrolledFarms'][0]['status'], 'withdrawn')
        r = _gql(self.pm, ENROLL, {'p': pid, 'f': str(self.lsk_crop.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(ProgrammeEnrollment.objects.filter(programme_id=pid).count(), 1)

    def test_closed_programme_blocks_enrolment(self):
        pid = _create(self.pm, status='closed')
        self.assertTrue('closed' in str(_gql(self.pm, ENROLL, {'p': pid, 'f': str(self.lsk_crop.id)}).errors[0]))


class SupportAndResultsTest(TestCase):
    def setUp(self):
        self.f1, self.d1 = _farm('Farm One', 'Lusaka', 'Chongwe')
        self.f2, self.d2 = _farm('Farm Two', 'Lusaka', 'Kafue')
        self.f3, self.d3 = _farm('Farm Three', 'Lusaka', 'Kafue')
        _, self.pm = _partner()
        self.pid = _create(self.pm)
        for f in (self.f1, self.f2):
            _gql(self.pm, ENROLL, {'p': self.pid, 'f': str(f.id)})

    def _support(self, farm, **over):
        inp = {'programmeId': self.pid, 'farmId': str(farm.id), 'supportType': 'input_voucher',
               'description': '50kg D-compound + 10kg seed', 'quantity': 1, 'value': 1800, 'currency': 'ZMW',
               'deliveredOn': str(date.today()), 'reference': 'V-0001'}
        inp.update(over)
        return _gql(self.pm, SUPPORT, {'input': inp})

    def test_record_support_notifies_and_rolls_up(self):
        r = self._support(self.f1)
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['recordSupport']['support']['farmName'], 'Farm One')
        self._support(self.f1, supportType='training', description='FAW IPM training', value=0)
        self._support(self.f2, supportType='cash_grant', description='Grant', value=5000)
        n = Notification.objects.filter(recipient=self.d1, title__contains='Input Voucher received')
        self.assertEqual(n.count(), 1)
        self.assertIn('V-0001', n.first().message)

        d = _gql(self.pm, DETAIL, {'id': self.pid}).data['partnerProgramme']
        res = d['results']
        self.assertEqual(res['farmsEnrolled'], 2)
        self.assertEqual(res['districts'], 2)
        self.assertEqual(res['supportEvents'], 3)
        self.assertAlmostEqual(res['supportValue'], 6800.0)
        self.assertEqual(res['farmsSupported'], 2)
        self.assertAlmostEqual(res['enrolmentPct'], 50.0)
        self.assertAlmostEqual(res['harvestQuantitySinceStart'], 500.0)

        by = {r['supportType']: r for r in _gql(self.pm, 'query($id: ID!) { programmeSupportByType(programmeId: $id) { supportType events farms value } }',
                                                {'id': self.pid}).data['programmeSupportByType']}
        self.assertEqual(by['input_voucher']['farms'], 1)
        self.assertAlmostEqual(by['cash_grant']['value'], 5000.0)

        rows = _gql(self.pm, ENROLLED, {'id': self.pid}).data['programmeEnrolledFarms']
        one = next(r for r in rows if r['name'] == 'Farm One')
        self.assertEqual(one['supportEvents'], 2)
        self.assertAlmostEqual(one['supportValue'], 1800.0)

    def test_support_requires_active_enrolment(self):
        r = self._support(self.f3)
        self.assertTrue('not actively enrolled' in str(r.errors[0]))
        self.assertEqual(ProgrammeSupport.objects.count(), 0)
        self.assertTrue(self._support(self.f1, supportType='helicopter').errors)
        self.assertTrue(self._support(self.f1, value=-5).errors)

    def test_indicator_readings_and_progress(self):
        m = 'mutation($p: ID!, $k: String!, $d: Date!, $v: Float!) { recordIndicatorReading(programmeId: $p, indicatorKey: $k, period: $d, value: $v) { reading { id } } }'
        self.assertIsNone(_gql(self.pm, m, {'p': self.pid, 'k': 'yield', 'd': '2026-06-30', 'v': 2.1}).errors)
        self.assertIsNone(_gql(self.pm, m, {'p': self.pid, 'k': 'yield', 'd': '2026-09-30', 'v': 2.8}).errors)
        self.assertTrue(_gql(self.pm, m, {'p': self.pid, 'k': 'nope', 'd': '2026-09-30', 'v': 1}).errors)
        st = {i['key']: i for i in _gql(self.pm, DETAIL, {'id': self.pid}).data['partnerProgramme']['indicatorStatus']}
        self.assertAlmostEqual(st['yield']['latestValue'], 2.8)
        self.assertAlmostEqual(st['yield']['progressPct'], 80.0)
        self.assertIsNone(st['income']['latestValue'])

    def test_district_rollup(self):
        self._support(self.f2, value=5000)
        rows = _gql(self.pm, 'query($id: ID!) { programmeDistricts(programmeId: $id) { district farms harvestQuantitySinceStart supportValue } }',
                    {'id': self.pid}).data['programmeDistricts']
        by = {r['district']: r for r in rows}
        self.assertEqual(by['Chongwe']['farms'], 1)
        self.assertAlmostEqual(by['Kafue']['supportValue'], 5000.0)
        self.assertAlmostEqual(by['Kafue']['harvestQuantitySinceStart'], 250.0)

    def test_notice_reaches_only_active_enrolled(self):
        eid = ProgrammeEnrollment.objects.get(programme_id=self.pid, farm=self.f2).id
        _gql(self.pm, 'mutation($e: ID!) { updateEnrollment(enrollmentId: $e, status: "completed") { ok } }', {'e': str(eid)})
        r = _gql(self.pm, 'mutation($p: ID!) { sendProgrammeNotice(programmeId: $p, title: "Input collection", message: "Collect at Chongwe depot Friday.", priority: "warning") { farms recipients } }',
                 {'p': self.pid})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['sendProgrammeNotice']['farms'], 1)
        self.assertEqual(Notification.objects.filter(recipient=self.d1, title__contains='Input collection').count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.d2, title__contains='Input collection').count(), 0)

    def test_partner_overview(self):
        self._support(self.f1)
        d = _gql(self.pm, 'query { partnerOverview { programmes activeProgrammes farmsEnrolled totalBudget supportValue districtsReached } }').data['partnerOverview']
        self.assertEqual(d['programmes'], 1)
        self.assertEqual(d['farmsEnrolled'], 2)
        self.assertAlmostEqual(d['totalBudget'], 100000.0)
        self.assertEqual(d['districtsReached'], 2)

    def test_farmer_sees_own_programmes_and_support(self):
        self._support(self.f1)
        q = 'query { myProgrammes { name partnerName funder status support { description value } } }'
        r = _gql(self.d1, q)
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['myProgrammes'][0]['partnerName'], 'FAO Zambia')
        self.assertEqual(len(r.data['myProgrammes'][0]['support']), 1)
        self.assertEqual(len(_gql(self.d2, q).data['myProgrammes'][0]['support']), 0)
        self.assertEqual(_gql(self.d3, q).data['myProgrammes'], [])
        self.assertTrue(_gql(self.pm, q).errors)


class PartnerRegistrationTest(TestCase):
    REG = 'mutation($input: RegisterInput!) { register(input: $input) { user { role organization { orgType } } } }'

    def test_partner_manager_registers_into_donor_org(self):
        r = _gql(None, self.REG, {'input': {'fullName': 'FAO Rep', 'password': 'strongpass99', 'phone': '+260955444333',
                                            'organizationName': 'FAO Zambia', 'role': 'partner_manager', 'orgType': 'donor'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['register']['user']['role'], 'partner_manager')
        self.assertEqual(r.data['register']['user']['organization']['orgType'], 'donor')
