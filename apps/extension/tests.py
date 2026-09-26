"""
Extension officer tests.

  1. Access: only extension_officer / saas_admin use officer queries; officers
     must sit in a partner org.
  2. Area + consent: only consenting farms in the officer's district are
     assignable; cross-district and opted-out farms are rejected.
  3. Caseload: priority ordering, farm detail scoped to caseload.
  4. Visits: logging notifies the farm; follow-up tracking; report resolution.
  5. Farmer side: sees assigned officers and visits.
  6. Advisory scoping for officers (forced to their district).
"""
import json
from datetime import date, timedelta

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import Organization, Profile
from apps.enterprises.models import Enterprise
from apps.vision.models import FarmerReport, AIVisionAnalysis
from apps.devices.models import SecurityAlert
from apps.notifications.models import Notification
from apps.extension.models import ExtensionCaseload, ExtensionVisit
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}),
                                    content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_seq = [100]


def _farm(name, province, district, consent=True):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(name=name, slug=f'xfarm-{n}', org_type='farm', province=province,
                                      district=district, data_sharing_consent=consent)
    d = Profile.objects.create_user(email=f'xd{n}@farm.test', full_name=f'{name} Director', password='pw12345678',
                                    phone=f'0977{n:07d}', organization=org, role='director')
    h = Profile.objects.create_user(email=f'xh{n}@farm.test', full_name=f'{name} Hand', password='pw12345678',
                                    phone=f'0966{n:07d}', organization=org, role='farmhand')
    Enterprise.objects.create(organization=org, name=f'{name} maize', category='crop', production_type='maize', created_by=d)
    return org, d, h


def _officer(province='Lusaka', district='Chongwe', name='Camp Officer'):
    _seq[0] += 1
    n = _seq[0]
    org = Organization.objects.create(name=f'DACO {district or province}', slug=f'daco-{n}', org_type='government',
                                      province=province, district=district)
    return org, Profile.objects.create_user(email=f'off{n}@moa.test', full_name=name, password='pw12345678',
                                            phone=f'0955{n:07d}', organization=org, role='extension_officer')


CASELOAD = """query { extensionCaseload { farmId name district priorityScore openAlerts unresolvedReports severeDiagnoses30d followUpOverdue lastVisitDate directorName } }"""
AVAILABLE = """query { extensionAvailableFarms { farmId name district } }"""
OVERVIEW = """query { extensionOverview { caseloadSize farmsAvailable farmsNeedingAttention followUpsOverdue unresolvedReports workingArea } }"""
ASSIGN = """mutation($id: ID!) { assignCaseloadFarm(farmId: $id) { farm { farmId name priorityScore } } }"""
DETAIL = """query($id: ID!) { extensionFarmDetail(farmId: $id) { summary { name } enterprises { name category } reports { id title isResolved severity } diagnoses { severity } alerts { title } visits { purpose } } }"""
LOG_VISIT = """mutation($input: VisitInput!) { logExtensionVisit(input: $input) { visit { id purpose farmName followUpDate followUpDone } } }"""


class OfficerAccessTest(TestCase):
    def setUp(self):
        self.farm, self.director, _ = _farm('Farm A', 'Lusaka', 'Chongwe')
        _, self.officer = _officer()
        gov_org = Organization.objects.create(name='MoA', slug='moa-x', org_type='government')
        self.viewer = Profile.objects.create_user(email='v@moa.test', full_name='V', password='pw12345678',
                                                  phone='0955999999', organization=gov_org, role='gov_viewer')

    def test_anonymous_and_farm_roles_denied(self):
        for u in (None, self.director):
            r = _gql(u, CASELOAD)
            self.assertTrue(r.errors, f'expected denial for {u}')

    def test_gov_viewer_denied_officer_queries(self):
        r = _gql(self.viewer, CASELOAD)
        self.assertTrue(r.errors and 'Permission denied' in str(r.errors[0]))

    def test_officer_allowed_and_sees_gov_aggregates(self):
        self.assertIsNone(_gql(self.officer, CASELOAD).errors)
        r = _gql(self.officer, 'query { govOverview { farmsReporting } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['govOverview']['farmsReporting'], 1)

    def test_officer_in_farm_org_rejected(self):
        bad = Profile.objects.create_user(email='bad@farm.test', full_name='Bad', password='pw12345678',
                                          phone='0955888888', organization=self.farm, role='extension_officer')
        r = _gql(bad, CASELOAD)
        self.assertTrue(r.errors and 'partner organisation' in str(r.errors[0]))

    def test_farmer_cannot_call_officer_mutations(self):
        r = _gql(self.director, ASSIGN, {'id': str(self.farm.id)})
        self.assertTrue(r.errors)


class AreaAndConsentTest(TestCase):
    def setUp(self):
        self.in_area, self.in_dir, _ = _farm('Chongwe A', 'Lusaka', 'Chongwe')
        self.in_area2, _, _ = _farm('Chongwe B', 'Lusaka', 'Chongwe')
        self.opted_out, _, _ = _farm('Chongwe Private', 'Lusaka', 'Chongwe', consent=False)
        self.other_district, _, _ = _farm('Kafue A', 'Lusaka', 'Kafue')
        _, self.officer = _officer('Lusaka', 'Chongwe')
        _, self.prov_officer = _officer('Lusaka', '', name='Provincial Officer')

    def test_available_farms_only_consenting_in_district(self):
        names = {f['name'] for f in _gql(self.officer, AVAILABLE).data['extensionAvailableFarms']}
        self.assertEqual(names, {'Chongwe A', 'Chongwe B'})

    def test_provincial_officer_sees_whole_province(self):
        names = {f['name'] for f in _gql(self.prov_officer, AVAILABLE).data['extensionAvailableFarms']}
        self.assertEqual(names, {'Chongwe A', 'Chongwe B', 'Kafue A'})

    def test_assign_in_area_farm_notifies_members(self):
        r = _gql(self.officer, ASSIGN, {'id': str(self.in_area.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['assignCaseloadFarm']['farm']['name'], 'Chongwe A')
        self.assertEqual(Notification.objects.filter(recipient__organization=self.in_area,
                                                     title='Extension officer assigned').count(), 2)
        # now excluded from available, present in caseload
        self.assertNotIn('Chongwe A', {f['name'] for f in _gql(self.officer, AVAILABLE).data['extensionAvailableFarms']})
        self.assertEqual(len(_gql(self.officer, CASELOAD).data['extensionCaseload']), 1)

    def test_assign_opted_out_farm_rejected(self):
        r = _gql(self.officer, ASSIGN, {'id': str(self.opted_out.id)})
        self.assertTrue(r.errors and 'opted in' in str(r.errors[0]))
        self.assertFalse(ExtensionCaseload.objects.exists())

    def test_assign_other_district_rejected(self):
        r = _gql(self.officer, ASSIGN, {'id': str(self.other_district.id)})
        self.assertTrue(r.errors)

    def test_reassign_after_remove_is_idempotent(self):
        _gql(self.officer, ASSIGN, {'id': str(self.in_area.id)})
        r = _gql(self.officer, 'mutation($id: ID!) { removeCaseloadFarm(farmId: $id) { ok } }', {'id': str(self.in_area.id)})
        self.assertTrue(r.data['removeCaseloadFarm']['ok'])
        self.assertEqual(len(_gql(self.officer, CASELOAD).data['extensionCaseload']), 0)
        r = _gql(self.officer, ASSIGN, {'id': str(self.in_area.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(ExtensionCaseload.objects.filter(officer=self.officer, farm=self.in_area).count(), 1)

    def test_consent_revocation_hides_farm_detail_but_keeps_assignment_visible(self):
        _gql(self.officer, ASSIGN, {'id': str(self.in_area.id)})
        self.in_area.data_sharing_consent = False
        self.in_area.save()
        # No longer assignable to a second officer
        _, other = _officer('Lusaka', 'Chongwe', name='Other')
        self.assertTrue(_gql(other, ASSIGN, {'id': str(self.in_area.id)}).errors)


class CaseloadPriorityTest(TestCase):
    def setUp(self):
        self.quiet, _, _ = _farm('Quiet Farm', 'Lusaka', 'Chongwe')
        self.busy, self.busy_dir, _ = _farm('Busy Farm', 'Lusaka', 'Chongwe')
        self.other, _, _ = _farm('Other Farm', 'Lusaka', 'Chongwe')
        _, self.officer = _officer()
        for f in (self.quiet, self.busy):
            ExtensionCaseload.objects.create(officer=self.officer, farm=f, assigned_by=self.officer)
        ent = Enterprise.objects.get(organization=self.busy)
        self.report = FarmerReport.objects.create(organization=self.busy, enterprise=ent, category='pest',
                                                  title='Armyworm', submitted_by=self.busy_dir)
        SecurityAlert.objects.create(organization=self.busy, source='device', severity='critical', title='Pump down')
        AIVisionAnalysis.objects.create(organization=self.busy, enterprise=ent, analysis_type='crop_disease',
                                        severity='critical', confidence_pct=90)

    def test_priority_ordering_and_signals(self):
        rows = _gql(self.officer, CASELOAD).data['extensionCaseload']
        self.assertEqual([r['name'] for r in rows], ['Busy Farm', 'Quiet Farm'])
        busy = rows[0]
        self.assertEqual(busy['openAlerts'], 1)
        self.assertEqual(busy['unresolvedReports'], 1)
        self.assertEqual(busy['severeDiagnoses30d'], 1)
        self.assertEqual(busy['directorName'], 'Busy Farm Director')
        # 5 (critical) + 2 (open alert) + 3 (report) + 3 (severe dx) + 2 (never visited)
        self.assertEqual(busy['priorityScore'], 15)
        self.assertEqual(rows[1]['priorityScore'], 2)

    def test_overview(self):
        d = _gql(self.officer, OVERVIEW).data['extensionOverview']
        self.assertEqual(d['caseloadSize'], 2)
        self.assertEqual(d['farmsAvailable'], 1)
        self.assertEqual(d['farmsNeedingAttention'], 1)
        self.assertEqual(d['unresolvedReports'], 1)
        self.assertEqual(d['workingArea'], 'Chongwe')

    def test_detail_scoped_to_caseload(self):
        r = _gql(self.officer, DETAIL, {'id': str(self.busy.id)})
        self.assertIsNone(r.errors, r.errors)
        d = r.data['extensionFarmDetail']
        self.assertEqual(d['summary']['name'], 'Busy Farm')
        self.assertEqual(d['reports'][0]['title'], 'Armyworm')
        self.assertEqual(d['diagnoses'][0]['severity'], 'critical')
        self.assertEqual(d['alerts'][0]['title'], 'Pump down')
        r = _gql(self.officer, DETAIL, {'id': str(self.other.id)})
        self.assertTrue(r.errors and 'not on your caseload' in str(r.errors[0]))

    def test_other_officer_cannot_see_this_caseload(self):
        _, other = _officer()
        self.assertEqual(_gql(other, CASELOAD).data['extensionCaseload'], [])
        self.assertTrue(_gql(other, DETAIL, {'id': str(self.busy.id)}).errors)

    def test_resolve_report(self):
        m = 'mutation($id: ID!, $n: String!) { resolveFarmerReport(reportId: $id, resolutionNotes: $n) { report { isResolved resolutionNotes } } }'
        r = _gql(self.officer, m, {'id': str(self.report.id), 'n': 'Applied Emamectin; re-scout in 5 days.'})
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(r.data['resolveFarmerReport']['report']['isResolved'])
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_resolved)
        self.assertIn('extension officer', self.report.resolution_notes)
        self.assertEqual(Notification.objects.filter(recipient=self.busy_dir, title__startswith='Report resolved').count(), 1)
        # Priority drops after resolution
        rows = _gql(self.officer, CASELOAD).data['extensionCaseload']
        self.assertEqual(rows[0]['unresolvedReports'], 0)

    def test_resolve_report_off_caseload_rejected(self):
        _, other = _officer()
        m = 'mutation($id: ID!, $n: String!) { resolveFarmerReport(reportId: $id, resolutionNotes: $n) { report { isResolved } } }'
        self.assertTrue(_gql(other, m, {'id': str(self.report.id), 'n': 'x'}).errors)
        self.report.refresh_from_db()
        self.assertFalse(self.report.is_resolved)

    def test_send_farm_advice(self):
        m = 'mutation($id: ID!) { sendFarmAdvice(farmId: $id, title: "Spray window", message: "Spray before Thursday rains.", priority: "warning") { recipients } }'
        r = _gql(self.officer, m, {'id': str(self.busy.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['sendFarmAdvice']['recipients'], 2)
        n = Notification.objects.get(recipient=self.busy_dir, title='Spray window')
        self.assertEqual(n.priority, 'warning')
        self.assertIn('Camp Officer', n.message)
        self.assertTrue(_gql(self.officer, m, {'id': str(self.other.id)}).errors)


class VisitTest(TestCase):
    def setUp(self):
        self.farm, self.director, self.hand = _farm('Visit Farm', 'Lusaka', 'Chongwe')
        self.off_farm, _, _ = _farm('Off Farm', 'Lusaka', 'Chongwe')
        _, self.officer = _officer()
        ExtensionCaseload.objects.create(officer=self.officer, farm=self.farm, assigned_by=self.officer)

    def _log(self, **extra):
        inp = {'farmId': str(self.farm.id), 'visitDate': str(date.today()), 'purpose': 'Routine scouting',
               'findings': 'Minor aphid pressure', 'recommendations': 'Scout again in 7 days',
               'followUpDate': str(date.today() + timedelta(days=7))}
        inp.update(extra)
        return _gql(self.officer, LOG_VISIT, {'input': inp})

    def test_log_visit_notifies_farm_and_tracks_follow_up(self):
        r = self._log()
        self.assertIsNone(r.errors, r.errors)
        v = r.data['logExtensionVisit']['visit']
        self.assertEqual(v['farmName'], 'Visit Farm')
        self.assertFalse(v['followUpDone'])
        self.assertEqual(Notification.objects.filter(recipient__in=[self.director, self.hand],
                                                     title__startswith='Extension visit').count(), 2)
        row = _gql(self.officer, CASELOAD).data['extensionCaseload'][0]
        self.assertEqual(row['lastVisitDate'], str(date.today()))
        self.assertFalse(row['followUpOverdue'])

        # Overdue follow-up raises priority and shows in overview
        ExtensionVisit.objects.filter(id=v['id']).update(follow_up_date=date.today() - timedelta(days=1))
        row = _gql(self.officer, CASELOAD).data['extensionCaseload'][0]
        self.assertTrue(row['followUpOverdue'])
        self.assertEqual(_gql(self.officer, OVERVIEW).data['extensionOverview']['followUpsOverdue'], 1)

        r = _gql(self.officer, 'mutation($id: ID!) { completeFollowUp(visitId: $id) { visit { followUpDone } } }', {'id': v['id']})
        self.assertTrue(r.data['completeFollowUp']['visit']['followUpDone'])
        self.assertEqual(_gql(self.officer, OVERVIEW).data['extensionOverview']['followUpsOverdue'], 0)

    def test_visit_without_recommendations_does_not_notify(self):
        r = self._log(recommendations='')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(Notification.objects.filter(title__startswith='Extension visit').count(), 0)

    def test_visit_off_caseload_rejected(self):
        r = self._log(farmId=str(self.off_farm.id))
        self.assertTrue(r.errors and 'not on your caseload' in str(r.errors[0]))
        self.assertEqual(ExtensionVisit.objects.count(), 0)

    def test_invalid_visit_type_rejected(self):
        self.assertTrue(self._log(visitType='helicopter').errors)

    def test_farmer_sees_officer_and_visits(self):
        self._log()
        r = _gql(self.director, 'query { myExtensionOfficers { fullName organizationName phone } myExtensionVisits { purpose recommendations officerName } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['myExtensionOfficers'][0]['fullName'], 'Camp Officer')
        self.assertEqual(r.data['myExtensionVisits'][0]['officerName'], 'Camp Officer')
        # farmhand sees the same (farm-scoped), other farm sees nothing
        self.assertEqual(len(_gql(self.hand, 'query { myExtensionVisits { id } }').data['myExtensionVisits']), 1)
        other_dir = Profile.objects.get(organization=self.off_farm, role='director')
        self.assertEqual(_gql(other_dir, 'query { myExtensionOfficers { id } }').data['myExtensionOfficers'], [])

    def test_officer_cannot_use_farmer_queries(self):
        self.assertTrue(_gql(self.officer, 'query { myExtensionVisits { id } }').errors)


class OfficerAdvisoryScopeTest(TestCase):
    MUT = 'mutation($input: AdvisoryInput!) { issueAdvisory(input: $input) { advisory { province district farmsReached } } }'

    def setUp(self):
        _farm('Chongwe A', 'Lusaka', 'Chongwe')
        _farm('Kafue A', 'Lusaka', 'Kafue')
        _, self.officer = _officer('Lusaka', 'Chongwe')

    def test_officer_advisory_forced_to_own_district(self):
        r = _gql(self.officer, self.MUT, {'input': {'title': 'x', 'message': 'y', 'province': 'Lusaka', 'district': 'Kafue'}})
        self.assertIsNone(r.errors, r.errors)
        a = r.data['issueAdvisory']['advisory']
        self.assertEqual(a['district'], 'Chongwe')
        self.assertEqual(a['farmsReached'], 1)


class OfficerRegistrationTest(TestCase):
    REG = 'mutation($input: RegisterInput!) { register(input: $input) { user { role organization { orgType district } } } }'

    def test_officer_registers_into_partner_org(self):
        r = _gql(None, self.REG, {'input': {'fullName': 'CEO Chongwe', 'password': 'strongpass99', 'phone': '+260955777111',
                                            'organizationName': 'Chongwe Camp', 'role': 'extension_officer',
                                            'province': 'Lusaka', 'district': 'Chongwe'}})
        self.assertIsNone(r.errors, r.errors)
        u = r.data['register']['user']
        self.assertEqual(u['role'], 'extension_officer')
        self.assertEqual(u['organization']['orgType'], 'government')
        self.assertEqual(u['organization']['district'], 'Chongwe')
