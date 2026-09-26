"""
Role catalogue, module permission matrix and server-side enforcement.

One source of truth for "who can do what": the frontend fetches this
catalogue (roleCatalogue query) and the effective matrix per user
(ProfileType.permissions), so sidebars and buttons follow exactly what the
API enforces via require_module().

Structure
  ORG_ROLES[org_type]      → [(role, label, description)]
  ORG_MODULES[org_type]    → [(module_id, label, group)]
  DEFAULT_MATRIX[role]     → {module_id: [actions]}
  Per-user overrides live in Profile.preferences['permissions'] (same shape)
  and replace the role default entirely (the Team page always writes the
  full matrix, so a partial override never hides modules by accident).
"""
from django.utils import timezone

ACTIONS = ('view', 'create', 'edit', 'delete')
ALL = list(ACTIONS)
RW = ['view', 'create', 'edit']
RO = ['view']
RC = ['view', 'create']

FARM_MODULES = [
    ('dashboard', 'Dashboard', 'Overview'), ('smart-engine', 'Smart AI Engine', 'Overview'), ('planner', 'Daily Planner', 'Overview'),
    ('poultry', 'Broiler Poultry', 'Production'), ('village-chicken', 'Village Chicken', 'Production'), ('piggery', 'Piggery', 'Production'),
    ('fish', 'Fish Farming', 'Production'), ('duck', 'Duck Management', 'Production'), ('goat-sheep', 'Goats & Sheep', 'Production'),
    ('horticulture', 'Horticulture', 'Production'), ('production', 'Production Records', 'Production'),
    ('inventory', 'Feed & Inventory', 'Operations'), ('sales', 'Sales & Customers', 'Operations'), ('finance', 'Financial Management', 'Operations'),
    ('credit', 'Credit Profile', 'Operations'), ('hr', 'Human Resources', 'Operations'), ('procurement', 'Procurement', 'Operations'),
    ('biosecurity', 'Biosecurity & Vet', 'Operations'), ('weather', 'Weather & Fields', 'Operations'), ('devices', 'Smart Devices & IoT', 'Operations'),
    ('reports', 'Reports & BI', 'Strategy'), ('export', 'Trade & Export', 'Strategy'), ('marketplace', 'Marketplace', 'Strategy'),
    ('assets', 'Assets & Infra', 'Strategy'), ('mobile', 'Mobile App', 'Strategy'), ('settings', 'Settings', 'Strategy'), ('team', 'Team & Permissions', 'Strategy'),
]
GOV_MODULES = [
    ('gov-dashboards', 'District & national dashboards', 'Data'), ('registry', 'District registry', 'Data'),
    ('advisories', 'Advisories', 'Outreach'), ('caseload', 'Extension caseload', 'Extension'), ('visits', 'Visits & follow-ups', 'Extension'),
    ('programmes', 'Programmes', 'Programmes'), ('enrolment', 'Participant enrolment', 'Programmes'), ('support', 'Support ledger', 'Programmes'),
    ('me', 'M&E indicators', 'Programmes'), ('notices', 'Programme notices', 'Programmes'),
    ('team', 'Team & Permissions', 'Admin'), ('settings', 'Organisation settings', 'Admin'),
]
PARTNER_MODULES = [
    ('programmes', 'Programmes', 'Programmes'), ('enrolment', 'Farm enrolment', 'Programmes'), ('support', 'Support ledger', 'Programmes'),
    ('me', 'M&E indicators', 'Programmes'), ('notices', 'Programme notices', 'Programmes'),
    ('gov-dashboards', 'District & national dashboards', 'Data'), ('registry', 'District registry', 'Data'), ('advisories', 'Advisories', 'Outreach'),
    ('team', 'Team & Permissions', 'Admin'), ('settings', 'Organisation settings', 'Admin'),
]
ORG_MODULES = {'farm': FARM_MODULES, 'government': GOV_MODULES, 'ngo': PARTNER_MODULES, 'donor': PARTNER_MODULES}

ORG_ROLES = {
    'farm': [
        ('director', 'Director / Owner', 'Full access, manages the team'),
        ('production_manager', 'Production Manager', 'Runs production, inventory and procurement'),
        ('finance_manager', 'Finance Manager', 'Finance, sales, credit profile, reports'),
        ('sales_manager', 'Sales Manager', 'Sales, marketplace, trade documents'),
        ('supervisor', 'Supervisor', 'Day-to-day production records'),
        ('farmhand', 'Farmhand', 'Logs daily records'),
        ('vet_officer', 'Veterinary Officer', 'Animal health and biosecurity'),
        ('driver', 'Driver', 'Mobile app, deliveries'),
    ],
    'government': [
        ('gov_admin', 'Administrator', 'Manages the team, branches and advisories; sees everything'),
        ('gov_viewer', 'Dashboard viewer', 'Read-only district & national dashboards'),
        ('extension_supervisor', 'Extension supervisor', 'Oversees officers in the branch, issues advisories'),
        ('extension_officer', 'Extension officer', 'Caseload of farms, visits, direct advice'),
    ],
    'ngo': [
        ('partner_admin', 'Administrator', 'Manages team, branches and programmes'),
        ('partner_manager', 'Programme manager', 'Runs programmes: enrolment, support, notices'),
        ('partner_me_officer', 'M&E officer', 'Records indicator readings and views results'),
        ('partner_observer', 'Observer (donor / auditor)', 'Read-only access to programmes and dashboards'),
    ],
}
ORG_ROLES['donor'] = ORG_ROLES['ngo']

# Roles that live in a partner organisation (not a farm)
PARTNER_ROLE_IDS = {r for t in ('government', 'ngo') for r, _, _ in ORG_ROLES[t]}
# Roles that may see the de-identified government aggregates
GOV_DATA_ROLES = PARTNER_ROLE_IDS
# Roles that use the extension shell
EXTENSION_ROLES = {'extension_officer', 'extension_supervisor'}
# Roles that may run programmes (any government / partner role; module matrix decides read vs write)
PROGRAMME_ROLES = PARTNER_ROLE_IDS
# Roles that use the partner shell
PARTNER_SHELL_ROLES = {'partner_admin', 'partner_manager', 'partner_me_officer', 'partner_observer'}
GOV_SHELL_ROLES = {'gov_admin', 'gov_viewer'}
# Roles that administer their organisation by definition
ADMIN_ROLES = {'director', 'gov_admin', 'partner_admin', 'saas_admin'}


def _m(ids, actions):
    return {i: list(actions) for i in ids}


def _full(org_type):
    return _m([m for m, _, _ in ORG_MODULES[org_type]], ALL)


LIVESTOCK = ['poultry', 'village-chicken', 'piggery', 'fish', 'duck', 'goat-sheep', 'horticulture', 'production']

DEFAULT_MATRIX = {
    'saas_admin': {**_full('farm'), **_full('government'), **_full('ngo')},
    'director': _full('farm'),
    'production_manager': {**_m(['dashboard', 'smart-engine', 'reports', 'settings', 'weather', 'devices', 'marketplace'], RO),
                           **_m(['planner', *LIVESTOCK, 'inventory', 'procurement', 'biosecurity'], RW)},
    'finance_manager': {**_m(['dashboard', 'planner', 'reports', 'export', 'settings', 'marketplace'], RO),
                        **_m(['finance', 'sales', 'inventory', 'procurement', 'credit'], RW)},
    'sales_manager': {**_m(['dashboard', 'planner', 'inventory', 'reports', 'settings', 'weather'], RO),
                      **_m(['sales', 'export', 'marketplace'], RW)},
    'supervisor': {**_m(['dashboard', 'planner', 'procurement', 'settings', 'weather', 'devices'], RO),
                   **_m([*LIVESTOCK, 'inventory', 'biosecurity'], RW)},
    'farmhand': {**_m(['dashboard', 'planner', 'mobile', 'weather'], RO), **_m(LIVESTOCK, RC)},
    'vet_officer': {**_m(['dashboard', 'planner', 'mobile'], RO), **_m(LIVESTOCK, RC), **_m(['biosecurity'], RW)},
    'driver': _m(['dashboard', 'planner', 'mobile'], RO),

    'gov_admin': _full('government'),
    'gov_viewer': _m(['gov-dashboards', 'registry', 'programmes', 'enrolment', 'support', 'me'], RO),
    'extension_supervisor': {**_m(['gov-dashboards', 'registry', 'settings'], RO), **_m(['caseload', 'visits'], ALL), **_m(['advisories'], RC),
                             **_m(['programmes', 'enrolment', 'support', 'me', 'notices'], RW)},
    'extension_officer': {**_m(['gov-dashboards', 'registry', 'programmes', 'enrolment', 'support'], RO), **_m(['caseload', 'visits'], RW), **_m(['advisories'], RC)},

    'partner_admin': _full('ngo'),
    'partner_manager': {**_m(['programmes', 'enrolment', 'support', 'me', 'notices'], ALL), **_m(['gov-dashboards', 'registry', 'settings'], RO), **_m(['advisories'], RC)},
    'partner_me_officer': {**_m(['programmes', 'enrolment', 'support', 'gov-dashboards', 'registry', 'settings'], RO), **_m(['me'], RW)},
    'partner_observer': _m(['programmes', 'enrolment', 'support', 'me', 'notices', 'gov-dashboards', 'registry'], RO),
}


def org_type_of(user):
    org = getattr(user, 'organization', None)
    return org.org_type if org else 'farm'


def roles_for(org_type):
    return ORG_ROLES.get(org_type, ORG_ROLES['farm'])


def role_ids_for(org_type):
    return [r for r, _, _ in roles_for(org_type)]


def modules_for(org_type):
    return ORG_MODULES.get(org_type, FARM_MODULES)


def default_matrix(role, org_type='farm'):
    m = DEFAULT_MATRIX.get(role)
    if m is None:
        return _m(['dashboard'] if org_type == 'farm' else ['gov-dashboards'], RO)
    return {k: list(v) for k, v in m.items()}


def is_org_admin(user):
    return bool(user and user.is_authenticated and (user.role in ADMIN_ROLES or getattr(user, 'is_org_admin', False)))


def effective_matrix(user):
    """Role default, replaced by a per-user override when one is stored."""
    if not user or not user.is_authenticated:
        return {}
    if user.role == 'saas_admin':
        return {k: list(v) for k, v in DEFAULT_MATRIX['saas_admin'].items()}
    org_type = org_type_of(user)
    if is_org_admin(user):
        return {**_full(org_type), **({'team': ALL} if org_type != 'farm' else {})}
    override = (user.preferences or {}).get('permissions') if isinstance(user.preferences, dict) else None
    if isinstance(override, dict) and override:
        return {k: [a for a in v if a in ACTIONS] for k, v in override.items() if isinstance(v, list)}
    if isinstance(override, list) and override:  # legacy flat list of visible modules
        return _m(override, RO)
    return default_matrix(user.role, org_type)


def can(user, module, action='view'):
    return action in effective_matrix(user).get(module, [])


def require_module(user, module, action='view'):
    """Raise unless the user's effective matrix grants module/action."""
    if not user or user.is_anonymous:
        raise Exception('Not authenticated')
    if not can(user, module, action):
        raise Exception(f'Permission denied: you need {action} access to {module}')
    return user


def assert_org_admin(user, what='manage the team'):
    if not user or user.is_anonymous:
        raise Exception('Not authenticated')
    if not is_org_admin(user):
        raise Exception(f'Permission denied: only an organisation administrator can {what}')
    return user


def branch_geo(user):
    """(province, district) the user is confined to by their branch, or (None, None) for org-wide."""
    b = getattr(user, 'branch', None)
    if b is None or not b.is_active or b.is_headquarters:
        return None, None
    return (b.province or None), (b.district or None)


def audit(org, actor, action, target=None, detail=None):
    from .models import AccessAuditLog
    return AccessAuditLog.objects.create(
        organization=org, actor=actor, target=target, action=action, detail=detail or {}, created_at=timezone.now())
