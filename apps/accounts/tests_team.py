"""Team, permissions, branches and enforcement tests — all organisation types."""
import json

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts import rbac
from apps.accounts.models import Organization, Profile, Branch, AccessAuditLog
from apps.enterprises.models import Enterprise
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [900]


def _org(name, org_type, role, **kw):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f't-{_n[0]}', org_type=org_type, **kw)
    admin = Profile.objects.create_user(email=f'a{_n[0]}@t.test', full_name=f'{name} Admin', password='pw12345678',
                                        phone=f'095{_n[0]:08d}', organization=org, role=role, is_org_admin=True)
    return org, admin


def _member(org, role, **kw):
    _n[0] += 1
    return Profile.objects.create_user(email=f'm{_n[0]}@t.test', full_name=f'Member {_n[0]}', password='pw12345678',
                                       phone=f'096{_n[0]:08d}', organization=org, role=role, **kw)


INVITE = 'mutation($i: InviteUserInput!) { inviteUser(input: $i) { profile { id role isOrgAdmin branchName permissions } } }'
CATALOGUE = 'query { roleCatalogue { orgType roles { id label defaultPermissions } modules { id group } branchKinds } }'


class CatalogueTest(TestCase):
    def test_catalogue_follows_org_type(self):
        _, farm = _org('F', 'farm', 'director')
        _, gov = _org('G', 'government', 'gov_admin')
        _, ngo = _org('N', 'donor', 'partner_admin')
        f = _gql(farm, CATALOGUE).data['roleCatalogue']
        g = _gql(gov, CATALOGUE).data['roleCatalogue']
        n = _gql(ngo, CATALOGUE).data['roleCatalogue']
        self.assertIn('farmhand', [r['id'] for r in f['roles']])
        self.assertEqual([r['id'] for r in g['roles']], ['gov_admin', 'gov_viewer', 'extension_supervisor', 'extension_officer'])
        self.assertEqual([r['id'] for r in n['roles']], ['partner_admin', 'partner_manager', 'partner_me_officer', 'partner_observer'])
        self.assertIn('caseload', [m['id'] for m in g['modules']])
        self.assertIn('programmes', [m['id'] for m in n['modules']])
        self.assertIn(['camp', 'Agricultural camp'], g['branchKinds'])
        self.assertIn(['country', 'Country office'], n['branchKinds'])
        viewer = next(r for r in g['roles'] if r['id'] == 'gov_viewer')
        self.assertEqual(json.loads(viewer['defaultPermissions'])['gov-dashboards'], ['view'])

    def test_every_role_has_a_default_matrix(self):
        for t, roles in rbac.ORG_ROLES.items():
            for r, _, _ in roles:
                self.assertIn(r, rbac.DEFAULT_MATRIX, r)
                mods = {m for m, _, _ in rbac.modules_for(t)}
                self.assertTrue(set(rbac.DEFAULT_MATRIX[r]) <= mods, f'{r} references modules outside {t}')


class InviteAndRolesTest(TestCase):
    def setUp(self):
        self.gov, self.admin = _org('MoA', 'government', 'gov_admin', province='Lusaka')
        self.farm, self.director = _org('Farm', 'farm', 'director')

    def test_creator_is_admin_and_can_invite_catalogue_roles(self):
        r = _gql(None, 'mutation($i: RegisterInput!) { register(input: $i) { user { isOrgAdmin role } } }',
                 {'i': {'fullName': 'X', 'password': 'strongpass99', 'phone': '+260955000001', 'organizationName': 'New Ministry', 'role': 'gov_viewer'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(r.data['register']['user']['isOrgAdmin'])
        r = _gql(self.admin, INVITE, {'i': {'fullName': 'Officer', 'phone': '0977001122', 'role': 'extension_officer'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['inviteUser']['profile']['role'], 'extension_officer')
        self.assertFalse(r.data['inviteUser']['profile']['isOrgAdmin'])
        self.assertEqual(json.loads(r.data['inviteUser']['profile']['permissions'])['caseload'], ['view', 'create', 'edit'])
        self.assertTrue(AccessAuditLog.objects.filter(organization=self.gov, action='member_invited').exists())

    def test_farm_role_rejected_in_government_org_and_vice_versa(self):
        r = _gql(self.admin, INVITE, {'i': {'fullName': 'X', 'phone': '0977001123', 'role': 'farmhand'}})
        self.assertTrue(r.errors and 'Invalid role for a government' in str(r.errors[0]))
        r = _gql(self.director, INVITE, {'i': {'fullName': 'X', 'phone': '0977001124', 'role': 'gov_viewer'}})
        self.assertTrue(r.errors and 'Invalid role for a farm' in str(r.errors[0]))

    def test_non_admin_cannot_invite_or_change_roles(self):
        viewer = _member(self.gov, 'gov_viewer')
        self.assertTrue(_gql(viewer, INVITE, {'i': {'fullName': 'X', 'phone': '0977001125', 'role': 'gov_viewer'}}).errors)
        officer = _member(self.gov, 'extension_officer')
        r = _gql(viewer, 'mutation($id: ID!) { updateMemberRole(userId: $id, role: "gov_admin") { profile { role } } }', {'id': str(officer.id)})
        self.assertTrue(r.errors)
        r = _gql(self.admin, 'mutation($id: ID!) { updateMemberRole(userId: $id, role: "extension_supervisor") { profile { role } } }', {'id': str(officer.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['updateMemberRole']['profile']['role'], 'extension_supervisor')

    def test_admin_flag_lifecycle(self):
        viewer = _member(self.gov, 'gov_viewer')
        m = 'mutation($id: ID!, $a: Boolean!) { setOrgAdmin(userId: $id, isAdmin: $a) { member { isOrgAdmin permissions } } }'
        r = _gql(self.admin, m, {'id': str(viewer.id), 'a': True})
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(r.data['setOrgAdmin']['member']['isOrgAdmin'])
        self.assertEqual(json.loads(r.data['setOrgAdmin']['member']['permissions'])['team'], ['view', 'create', 'edit', 'delete'])
        # cannot remove own admin; cannot leave org without admin
        self.assertTrue(_gql(self.admin, m, {'id': str(self.admin.id), 'a': False}).errors)
        r = _gql(self.admin, m, {'id': str(viewer.id), 'a': False})
        self.assertIsNone(r.errors, r.errors)
        viewer.refresh_from_db()
        self.assertFalse(viewer.is_org_admin)

    def test_cannot_deactivate_self(self):
        r = _gql(self.admin, 'mutation($id: ID!) { deactivateUser(userId: $id) { success } }', {'id': str(self.admin.id)})
        self.assertTrue(r.errors)


class PermissionMatrixTest(TestCase):
    def setUp(self):
        self.farm, self.director = _org('Farm', 'farm', 'director')
        self.hand = _member(self.farm, 'farmhand')
        self.fin = _member(self.farm, 'finance_manager')

    def test_defaults_and_override(self):
        self.assertFalse(rbac.can(self.hand, 'finance', 'view'))
        self.assertTrue(rbac.can(self.hand, 'poultry', 'create'))
        self.assertFalse(rbac.can(self.hand, 'poultry', 'delete'))
        self.assertTrue(rbac.can(self.fin, 'credit', 'create'))
        m = 'mutation($id: ID!, $p: JSONString!) { setMemberPermissions(userId: $id, permissions: $p) { profile { permissions } } }'
        r = _gql(self.director, m, {'id': str(self.hand.id), 'p': json.dumps({'finance': ['view'], 'poultry': ['view', 'create', 'edit'], 'bogus': ['view'], 'sales': ['fly']})})
        self.assertIsNone(r.errors, r.errors)
        eff = json.loads(r.data['setMemberPermissions']['profile']['permissions'])
        self.assertEqual(eff, {'finance': ['view'], 'poultry': ['view', 'create', 'edit'], 'sales': []})
        self.hand.refresh_from_db()
        self.assertTrue(rbac.can(self.hand, 'finance', 'view'))
        self.assertTrue(rbac.can(self.hand, 'poultry', 'edit'))
        self.assertFalse(rbac.can(self.hand, 'dashboard', 'view'))  # override replaces the default
        r = _gql(self.director, 'mutation($id: ID!) { resetMemberPermissions(userId: $id) { member { hasOverride permissions } } }', {'id': str(self.hand.id)})
        self.assertFalse(r.data['resetMemberPermissions']['member']['hasOverride'])
        self.assertIn('dashboard', json.loads(r.data['resetMemberPermissions']['member']['permissions']))

    def test_cannot_restrict_an_admin(self):
        m = 'mutation($id: ID!, $p: JSONString!) { setMemberPermissions(userId: $id, permissions: $p) { profile { id } } }'
        self.assertTrue(_gql(self.director, m, {'id': str(self.director.id), 'p': json.dumps({'finance': []})}).errors)

    def test_server_side_enforcement(self):
        # farmhand cannot create a buyer / contract / share credit; finance manager can share credit
        self.assertTrue(_gql(self.hand, 'mutation { createBuyerProfile(name: "B") { buyer { id } } }').errors)
        self.assertTrue(_gql(self.hand, 'mutation { createCreditShareGrant(lenderName: "Z") { grant { id } } }').errors)
        self.assertTrue(_gql(self.hand, 'query { myCreditSummary { score } }').errors)
        r = _gql(self.fin, 'mutation { createCreditShareGrant(lenderName: "Z") { grant { id } } }')
        self.assertIsNone(r.errors, r.errors)
        # and the me-query exposes the effective matrix
        r = _gql(self.hand, 'query { me { permissions isOrgAdmin orgType } }')
        self.assertEqual(r.data['me']['orgType'], 'farm')
        self.assertFalse(r.data['me']['isOrgAdmin'])
        self.assertNotIn('finance', json.loads(r.data['me']['permissions']))


class PartnerRolesEnforcementTest(TestCase):
    def setUp(self):
        self.org, self.admin = _org('FAO', 'donor', 'partner_admin')
        self.manager = _member(self.org, 'partner_manager')
        self.me = _member(self.org, 'partner_me_officer')
        self.observer = _member(self.org, 'partner_observer')
        r = _gql(self.manager, 'mutation { createProgramme(input: {name: "P", startDate: "2026-01-01", status: "active", indicators: [{key: "k", label: "K", target: 10}]}) { programme { id } } }')
        self.assertIsNone(r.errors, r.errors)
        self.pid = r.data['createProgramme']['programme']['id']

    def test_observer_and_me_officer_limits(self):
        create = 'mutation { createProgramme(input: {name: "Q", startDate: "2026-01-01"}) { programme { id } } }'
        self.assertTrue(_gql(self.observer, create).errors)
        self.assertTrue(_gql(self.me, create).errors)
        self.assertIsNone(_gql(self.observer, 'query { partnerProgrammes { id } }').errors)
        reading = 'mutation($p: ID!) { recordIndicatorReading(programmeId: $p, indicatorKey: "k", period: "2026-06-30", value: 4) { reading { id } } }'
        self.assertTrue(_gql(self.observer, reading, {'p': self.pid}).errors)
        self.assertIsNone(_gql(self.me, reading, {'p': self.pid}).errors)
        notice = 'mutation($p: ID!) { sendProgrammeNotice(programmeId: $p, title: "t", message: "m") { farms } }'
        self.assertTrue(_gql(self.me, notice, {'p': self.pid}).errors)
        self.assertIsNone(_gql(self.manager, notice, {'p': self.pid}).errors)
        # all partner roles may see gov aggregates
        for u in (self.observer, self.me):
            self.assertIsNone(_gql(u, 'query { govOverview { farmsReporting } }').errors)


class BranchesTest(TestCase):
    def setUp(self):
        self.gov, self.admin = _org('MoA', 'government', 'gov_admin', province='')
        self.chongwe, _ = _org('Chongwe Farm', 'farm', 'director', province='Lusaka', district='Chongwe', data_sharing_consent=True)
        self.kafue, _ = _org('Kafue Farm', 'farm', 'director', province='Lusaka', district='Kafue', data_sharing_consent=True)
        self.kitwe, _ = _org('Kitwe Farm', 'farm', 'director', province='Copperbelt', district='Kitwe', data_sharing_consent=True)
        for o in (self.chongwe, self.kafue, self.kitwe):
            Enterprise.objects.create(organization=o, name='E', category='crop', production_type='maize')

    def _branch(self, **kw):
        r = _gql(self.admin, 'mutation($i: BranchInput!) { createBranch(input: $i) { branch { id name kind kindDisplay isHeadquarters } } }', {'i': kw})
        self.assertIsNone(r.errors, r.errors)
        return r.data['createBranch']['branch']

    def test_branch_crud_and_kinds(self):
        hq = self._branch(name='HQ Lusaka', kind='hq', isHeadquarters=True)
        d = self._branch(name='Chongwe DACO', kind='district', province='Lusaka', district='Chongwe')
        self.assertEqual(d['kindDisplay'], 'District office (DACO)')
        self.assertTrue(_gql(self.admin, 'mutation($i: BranchInput!) { createBranch(input: $i) { branch { id } } }', {'i': {'name': 'X', 'kind': 'site'}}).errors)  # farm kind in gov org
        # a second HQ demotes the first
        self._branch(name='HQ New', kind='hq', isHeadquarters=True)
        self.assertFalse(Branch.objects.get(pk=hq['id']).is_headquarters)
        viewer = _member(self.gov, 'gov_viewer')
        self.assertTrue(_gql(viewer, 'mutation($i: BranchInput!) { createBranch(input: $i) { branch { id } } }', {'i': {'name': 'Y', 'kind': 'camp'}}).errors)
        # cannot delete a branch with members
        _gql(self.admin, 'mutation($u: ID!, $b: UUID!) { setMemberBranch(userId: $u, branchId: $b) { member { branch { name } } } }', {'u': str(viewer.id), 'b': d['id']})
        self.assertTrue(_gql(self.admin, 'mutation($id: UUID!) { deleteBranch(id: $id) { ok } }', {'id': d['id']}).errors)
        self.assertEqual(len(_gql(self.admin, 'query { branches { id } }').data['branches']), 3)

    def test_branch_scopes_officer_and_viewer(self):
        d = self._branch(name='Chongwe DACO', kind='district', province='Lusaka', district='Chongwe')
        p = self._branch(name='Lusaka Provincial', kind='provincial', province='Lusaka')
        officer = _member(self.gov, 'extension_officer', branch=Branch.objects.get(pk=d['id']))
        names = {f['name'] for f in _gql(officer, 'query { extensionAvailableFarms { name } }').data['extensionAvailableFarms']}
        self.assertEqual(names, {'Chongwe Farm'})
        self.assertTrue(_gql(officer, 'mutation($id: ID!) { assignCaseloadFarm(farmId: $id) { farm { name } } }', {'id': str(self.kafue.id)}).errors)
        # provincial viewer: whole province, not other provinces, filter cannot escape
        pv = _member(self.gov, 'gov_viewer', branch=Branch.objects.get(pk=p['id']))
        r = _gql(pv, 'query { govOverview { farmsReporting } }')
        self.assertEqual(r.data['govOverview']['farmsReporting'], 2)
        r = _gql(pv, 'query { govOverview(province: "Copperbelt") { farmsReporting } }')
        self.assertEqual(r.data['govOverview']['farmsReporting'], 2)
        # district viewer confined; HQ admin national
        dv = _member(self.gov, 'gov_viewer', branch=Branch.objects.get(pk=d['id']))
        self.assertEqual(_gql(dv, 'query { govOverview(district: "Kafue") { farmsReporting } }').data['govOverview']['farmsReporting'], 1)
        self.assertEqual(_gql(self.admin, 'query { govOverview { farmsReporting } }').data['govOverview']['farmsReporting'], 3)
        # branch advisory forced into branch scope
        r = _gql(dv, 'mutation { issueAdvisory(input: {title: "t", message: "m", district: "Kafue"}) { advisory { district farmsReached } } }')
        self.assertTrue(r.errors)  # viewer has no advisories create
        sup = _member(self.gov, 'extension_supervisor', branch=Branch.objects.get(pk=d['id']))
        r = _gql(sup, 'mutation { issueAdvisory(input: {title: "t", message: "m", district: "Kafue"}) { advisory { district farmsReached } } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['issueAdvisory']['advisory']['district'], 'Chongwe')

    def test_farm_branches_too(self):
        farm, director = _org('Big Farm', 'farm', 'director')
        r = _gql(director, 'mutation($i: BranchInput!) { createBranch(input: $i) { branch { kindDisplay } } }', {'i': {'name': 'Block B site', 'kind': 'site', 'district': 'Mkushi'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['createBranch']['branch']['kindDisplay'], 'Farm site')
        log = _gql(director, 'query { accessAuditLog { action actorName } }').data['accessAuditLog']
        self.assertEqual(log[0]['action'], 'branch_created')
