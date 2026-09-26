"""Step 1 of the Partner Programme Operations Suite — results framework + disaggregation."""
import json
from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import Organization, Profile, ParticipantProfile
from apps.partners.models import Programme, ProgrammeEnrollment, ProgrammeSupport, Indicator, ResultChain, IndicatorReading
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [950]


def _org(name, bt='farmer', district='Chongwe'):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f'lf-{_n[0]}', org_type='farm', business_type=bt, province='Lusaka', district=district, data_sharing_consent=True)
    d = Profile.objects.create_user(email=f'lf{_n[0]}@t.test', full_name='D', password='pw12345678', phone=f'095{_n[0]:08d}', organization=org, role='director', is_org_admin=True)
    return org, d


class LogframeTest(TestCase):
    def setUp(self):
        fao = Organization.objects.create(name='FAO', slug='fao-lf', org_type='donor')
        self.pm = Profile.objects.create_user(email='pm@lf.test', full_name='PM', password='pw12345678', phone='0955950001', organization=fao, role='partner_manager')
        self.obs = Profile.objects.create_user(email='obs@lf.test', full_name='O', password='pw12345678', phone='0955950002', organization=fao, role='partner_observer')
        other = Organization.objects.create(name='Other', slug='oth-lf', org_type='ngo')
        self.other = Profile.objects.create_user(email='o@lf.test', full_name='X', password='pw12345678', phone='0955950003', organization=other, role='partner_manager')
        self.a, self.a_dir = _org('Farm A')
        self.b, self.b_dir = _org('Farm B')
        self.c, self.c_dir = _org('Vet C', 'vet_provider', 'Kafue')
        self.out, self.out_dir = _org('Not enrolled')
        self.p = Programme.objects.create(organization=fao, name='HiH', start_date=date(2026, 1, 1), status='active', created_by=self.pm,
                                          indicators=[{'key': 'farmers_trained', 'label': 'Farmers trained', 'unit': 'farmers', 'target': 100}])
        for o in (self.a, self.b, self.c):
            ProgrammeEnrollment.objects.create(programme=self.p, farm=o, enrolled_by=self.pm)
        year = timezone.localdate().year
        ParticipantProfile.objects.create(organization=self.a, head_sex='F', head_birth_year=year - 28, household_size=6)
        ParticipantProfile.objects.create(organization=self.b, head_sex='M', head_birth_year=year - 50, household_size=4, disability=True)
        ProgrammeSupport.objects.create(programme=self.p, farm=self.a, support_type='training', description='GAP', value=100, delivered_on=date.today(), created_by=self.pm)
        ProgrammeSupport.objects.create(programme=self.p, farm=self.b, support_type='seed', description='Maize', value=500, delivered_on=date.today(), created_by=self.pm)

    # ── structure ────────────────────────────────────────────────────────────
    def test_legacy_json_indicators_are_mirrored_into_rows_on_update(self):
        # programme created directly (no rows yet) → the form's quick list syncs rows on update
        r = _gql(self.pm, 'mutation($id: ID!) { updateProgramme(id: $id, input: { indicators: [{ key: "farmers_trained", label: "Farmers trained", unit: "farmers", target: 120 }, { key: "yield", label: "Maize yield", unit: "t/ha", target: 3 }] }) { programme { id indicators { key target } } } }', {'id': str(self.p.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual({i.key: float(i.target) for i in Indicator.objects.filter(programme=self.p)}, {'farmers_trained': 120.0, 'yield': 3.0})

    def test_results_chain_rules(self):
        q = 'mutation($p: ID!, $in: ResultInput!, $id: ID) { upsertResult(programmeId: $p, id: $id, input: $in) { result { id level parentId code } } }'
        g = _gql(self.pm, q, {'p': str(self.p.id), 'in': {'level': 'goal', 'statement': 'Resilient smallholders'}})
        self.assertIsNone(g.errors, g.errors)
        gid = g.data['upsertResult']['result']['id']
        oc = _gql(self.pm, q, {'p': str(self.p.id), 'in': {'level': 'outcome', 'parentId': gid, 'code': '1', 'statement': 'Higher incomes'}})
        self.assertIsNone(oc.errors, oc.errors)
        ocid = oc.data['upsertResult']['result']['id']
        # an output cannot sit under an output's own level or above
        bad = _gql(self.pm, q, {'p': str(self.p.id), 'in': {'level': 'goal', 'parentId': ocid, 'statement': 'wrong'}})
        self.assertTrue(bad.errors)
        # observers cannot edit
        self.assertTrue(_gql(self.obs, q, {'p': str(self.p.id), 'in': {'level': 'output', 'parentId': ocid, 'statement': 'x'}}).errors)
        # other partner cannot touch this programme
        self.assertTrue(_gql(self.other, q, {'p': str(self.p.id), 'in': {'level': 'output', 'statement': 'x'}}).errors)
        op = _gql(self.pm, q, {'p': str(self.p.id), 'in': {'level': 'output', 'parentId': ocid, 'code': '1.1', 'statement': 'Farmers trained in GAP'}})
        self.assertIsNone(op.errors, op.errors)
        self.assertEqual(ResultChain.objects.filter(programme=self.p).count(), 3)
        # deleting the outcome cascades to the output
        d = _gql(self.pm, 'mutation($id: ID!) { deleteResult(id: $id) { ok } }', {'id': ocid})
        self.assertIsNone(d.errors, d.errors)
        self.assertEqual(ResultChain.objects.filter(programme=self.p).count(), 1)

    # ── indicators ───────────────────────────────────────────────────────────
    def test_auto_sourced_indicator_with_disaggregation(self):
        out = ResultChain.objects.create(programme=self.p, level='output', code='1.1', statement='Participants reached')
        r = _gql(self.pm, '''mutation($p: ID!, $in: LogframeIndicatorInput!) { upsertIndicator(programmeId: $p, input: $in) {
            indicator { id key label value progressPct breakdown autoSource baseline target resultId } } }''',
                 {'p': str(self.p.id), 'in': {'label': 'Participants enrolled', 'unit': 'organisations', 'resultId': str(out.id), 'baseline': 0, 'target': 6,
                                             'autoSource': 'participants_enrolled', 'disaggregations': ['sex', 'age', 'participant_type', 'district'], 'meansOfVerification': 'Platform enrolment register'}})
        self.assertIsNone(r.errors, r.errors)
        ind = r.data['upsertIndicator']['indicator']
        self.assertEqual(ind['key'], 'participants_enrolled')
        self.assertEqual(ind['value'], 3.0)
        self.assertEqual(ind['progressPct'], 50.0)
        bd = json.loads(ind['breakdown'])
        self.assertEqual(bd['sex'], {'F': 1, 'M': 1, 'unknown': 1})
        self.assertEqual(bd['age'], {'adult': 1, 'unknown': 1, 'youth': 1})
        self.assertEqual(bd['participant_type'], {'farmer': 2, 'vet_provider': 1})
        self.assertEqual(bd['district'], {'Chongwe': 2, 'Kafue': 1})
        # a computed indicator refuses manual readings
        bad = _gql(self.pm, 'mutation($p: ID!) { recordIndicatorReading(programmeId: $p, indicatorKey: "participants_enrolled", period: "2026-06-30", value: 99) { reading { id } } }', {'p': str(self.p.id)})
        self.assertTrue(bad.errors)
        # women / youth / households / support value sources
        for src, expected, dim, cat, catval in (('participants_women', 1.0, 'sex', 'F', 1), ('participants_youth', 1.0, 'age', 'youth', 1),
                                                ('households_reached', 11.0, 'sex', 'F', 6), ('support_value', 600.0, 'sex', 'M', 500), ('training_events', 1.0, 'sex', 'F', 1)):
            r = _gql(self.pm, 'mutation($p: ID!, $in: LogframeIndicatorInput!) { upsertIndicator(programmeId: $p, input: $in) { indicator { value breakdown } } }',
                     {'p': str(self.p.id), 'in': {'label': src, 'autoSource': src, 'disaggregations': ['sex', 'age']}})
            self.assertIsNone(r.errors, (src, r.errors))
            self.assertEqual(r.data['upsertIndicator']['indicator']['value'], expected, src)
            self.assertEqual(json.loads(r.data['upsertIndicator']['indicator']['breakdown'])[dim].get(cat), catval, src)

    def test_manual_reading_with_disaggregation_and_progress_from_baseline(self):
        r = _gql(self.pm, 'mutation($p: ID!, $in: LogframeIndicatorInput!) { upsertIndicator(programmeId: $p, input: $in) { indicator { id key } } }',
                 {'p': str(self.p.id), 'in': {'key': 'yield', 'label': 'Maize yield', 'unit': 't/ha', 'baseline': 1.5, 'baselineDate': '2026-01-01', 'target': 3.5, 'targetDate': '2028-06-30', 'disaggregations': ['sex']}})
        self.assertIsNone(r.errors, r.errors)
        # breakdown must add up for sex / age
        bad = _gql(self.pm, 'mutation($p: ID!, $d: JSONString) { recordIndicatorReading(programmeId: $p, indicatorKey: "yield", period: "2026-06-30", value: 2.5, disaggregation: $d) { reading { id } } }',
                   {'p': str(self.p.id), 'd': json.dumps({'sex': {'F': 2.0, 'M': 1.5}})})
        self.assertTrue(bad.errors)
        ok = _gql(self.pm, 'mutation($p: ID!, $d: JSONString) { recordIndicatorReading(programmeId: $p, indicatorKey: "yield", period: "2026-06-30", value: 2.5, disaggregation: $d) { reading { id disaggregation } } }',
                  {'p': str(self.p.id), 'd': json.dumps({'sex': {'F': 1.0, 'M': 1.5}})})
        self.assertIsNone(ok.errors, ok.errors)
        lf = _gql(self.pm, 'query($p: ID!) { programmeLogframe(programmeId: $p) { indicators { key value baseline target progressPct breakdown } autoSources } }', {'p': str(self.p.id)})
        self.assertIsNone(lf.errors, lf.errors)
        y = next(i for i in lf.data['programmeLogframe']['indicators'] if i['key'] == 'yield')
        self.assertEqual(y['value'], 2.5)
        self.assertEqual(y['progressPct'], 50.0)  # (2.5-1.5)/(3.5-1.5)
        self.assertEqual(json.loads(y['breakdown'])['sex'], {'F': 1.0, 'M': 1.5})
        self.assertTrue(len(json.loads(lf.data['programmeLogframe']['autoSources'])) >= 10)
        # legacy status field still works and shows the breakdown
        st = _gql(self.pm, 'query($p: ID!) { partnerProgramme(id: $p) { indicatorStatus { key latestValue baseline progressPct } } }', {'p': str(self.p.id)})
        self.assertEqual(next(i for i in st.data['partnerProgramme']['indicatorStatus'] if i['key'] == 'yield')['progressPct'], 50.0)

    def test_results_demographics(self):
        r = _gql(self.pm, 'query($p: ID!) { partnerProgramme(id: $p) { results { farmsActive participantsWomen participantsMen participantsYouth participantsDisability participantsWithProfile householdsReached participantsBySex participantsByAge } } }', {'p': str(self.p.id)})
        self.assertIsNone(r.errors, r.errors)
        res = r.data['partnerProgramme']['results']
        self.assertEqual((res['participantsWomen'], res['participantsMen'], res['participantsYouth'], res['participantsDisability'], res['participantsWithProfile']), (1, 1, 1, 1, 2))
        self.assertEqual(res['householdsReached'], 11)  # 6 + 4 + 1 (no profile counts as one)
        self.assertEqual(json.loads(res['participantsBySex']), {'F': 1, 'M': 1, 'unknown': 1})
        e = _gql(self.pm, 'query($p: ID!) { programmeEnrolledFarms(programmeId: $p) { name headSex isYouth householdSize hasProfile } }', {'p': str(self.p.id)})
        rows = {x['name']: x for x in e.data['programmeEnrolledFarms']}
        self.assertEqual((rows['Farm A']['headSex'], rows['Farm A']['isYouth'], rows['Farm A']['householdSize']), ('F', True, 6))
        self.assertFalse(rows['Vet C']['hasProfile'])

    # ── participant profile permissions ──────────────────────────────────────
    def test_profile_permissions(self):
        q = 'mutation($o: ID, $in: ParticipantProfileInput!) { setParticipantProfile(organizationId: $o, input: $in) { profile { headSex headAge isYouth householdSize hasNationalId } } }'
        # director sets own
        r = _gql(self.c_dir, q, {'in': {'headSex': 'F', 'headBirthYear': timezone.localdate().year - 30, 'householdSize': 5, 'nationalId': '123456/78/1'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual((r.data['setParticipantProfile']['profile']['headSex'], r.data['setParticipantProfile']['profile']['isYouth'], r.data['setParticipantProfile']['profile']['hasNationalId']), ('F', True, True))
        self.assertNotIn('123456', ParticipantProfile.objects.get(organization=self.c).national_id_hash)
        # partner sets for an enrolled organisation
        r = _gql(self.pm, q, {'o': str(self.a.id), 'in': {'householdSize': 7}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(ParticipantProfile.objects.get(organization=self.a).household_size, 7)
        # ... but not for one it has not enrolled, and observers cannot edit
        self.assertTrue(_gql(self.pm, q, {'o': str(self.out.id), 'in': {'householdSize': 7}}).errors)
        self.assertTrue(_gql(self.obs, q, {'o': str(self.a.id), 'in': {'householdSize': 7}}).errors)
        # another farm's director cannot touch farm A
        self.assertTrue(_gql(self.b_dir, q, {'o': str(self.a.id), 'in': {'householdSize': 7}}).errors)
        # validation
        self.assertTrue(_gql(self.a_dir, q, {'in': {'headSex': 'Q'}}).errors)
        self.assertTrue(_gql(self.a_dir, q, {'in': {'headBirthYear': 1800}}).errors)
        me = _gql(self.a_dir, 'query { myParticipantProfile { headSex householdSize } }')
        self.assertEqual(me.data['myParticipantProfile']['householdSize'], 7)

    def test_report_includes_logframe(self):
        from apps.partners.reports import collect_report_data
        ResultChain.objects.create(programme=self.p, level='output', code='1.1', statement='Reached')
        Indicator.objects.create(programme=self.p, key='participants_enrolled', label='Participants', auto_source='participants_enrolled', disaggregations=['sex'], target=6,
                                 result=ResultChain.objects.get(programme=self.p))
        d = collect_report_data(self.p)
        row = next(i for i in d['indicators'] if i['key'] == 'participants_enrolled')
        self.assertEqual(row['latest'], 3.0)
        self.assertIn('Women 1', row['breakdown'])
        self.assertIn('1.1 Reached', row['result'])
        self.assertEqual(d['results'].participants_women, 1)
