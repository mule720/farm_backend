from django.conf import settings
import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from .managers import ProfileManager


class Organization(models.Model):
    PLAN_CHOICES = [('free', 'Free'), ('pro', 'Pro'), ('enterprise', 'Enterprise')]
    # Participant type for private-sector organisations (org_type='farm'). Persisted here so the
    # backend can tell a vet from a farm — programmes and government statistics need it.
    BUSINESS_TYPE_CHOICES = [
        ('farmer', 'Farm'), ('cooperative', 'Cooperative / Farmer Group'), ('agro_dealer', 'Agro Dealer / Input Shop'),
        ('vet_provider', 'Veterinary Services'), ('equipment_hire', 'Equipment Hire'), ('agrifood_seller', 'AgriFood Seller'),
        ('agrisupply_provider', 'AgriSupply Provider'), ('agriservices_provider', 'AgriServices Provider'),
        ('processor', 'Agro Processor'), ('transport', 'Transport & Logistics'),
    ]
    ORG_TYPE_CHOICES = [
        ('farm', 'Farm / Agribusiness'),
        ('government', 'Government Ministry / District Office'),
        ('ngo', 'NGO / Development Partner'),
        ('donor', 'Donor Programme'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    org_type = models.CharField(max_length=20, choices=ORG_TYPE_CHOICES, default='farm')
    business_type = models.CharField(max_length=30, choices=BUSINESS_TYPE_CHOICES, default='farmer')
    country = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    # Farmer opt-in: only consenting farms appear in government / partner aggregates.
    # Aggregates are always de-identified; consent controls inclusion, not identity.
    data_sharing_consent = models.BooleanField(default=False)
    data_sharing_consented_at = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=10, default='ZMW')
    logo_url = models.URLField(blank=True)
    settings = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name


class Profile(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('director', 'Director / Admin'),
        ('production_manager', 'Production Manager'),
        ('finance_manager', 'Finance Manager'),
        ('sales_manager', 'Sales Manager'),
        ('supervisor', 'Supervisor'),
        ('farmhand', 'Farmhand'),
        ('vet_officer', 'Veterinary Officer'),
        ('driver', 'Driver'),
        ('saas_admin', 'SaaS Platform Admin'),
        ('gov_viewer', 'Government / Partner Viewer'),
        ('extension_officer', 'Extension Officer'),
        ('partner_manager', 'Supporting Partner Programme Manager'),
        ('gov_admin', 'Government Administrator'),
        ('extension_supervisor', 'Extension Supervisor'),
        ('partner_admin', 'Supporting Partner Administrator'),
        ('partner_me_officer', 'Supporting Partner M&E Officer'),
        ('partner_observer', 'Supporting Partner Observer'),
    ]
    # Roles that live in a government / partner organisation, not a farm
    PARTNER_ROLES = ('gov_viewer', 'gov_admin', 'extension_officer', 'extension_supervisor',
                     'partner_manager', 'partner_admin', 'partner_me_officer', 'partner_observer')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='members'
    )
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='farmhand')
    # Organisation administrator (team, branches, permissions) — independent of the functional role
    is_org_admin = models.BooleanField(default=False)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    avatar_url = models.URLField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = ProfileManager()

    class Meta:
        db_table = 'profiles'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} ({self.email})'

    @property
    def is_platform_admin(self):
        return self.role == 'saas_admin'

    def has_role(self, *roles):
        return self.role in roles or self.role == 'saas_admin'


class Branch(models.Model):
    """A site / office of an organisation: farm site, district office, camp,
    country or field office. Members assigned to a non-HQ branch are scoped to
    its province / district where the feature is geographic (extension
    caseloads, government dashboards)."""

    KINDS = {
        'farm': [('site', 'Farm site'), ('warehouse', 'Warehouse / pack-house'), ('outlet', 'Sales outlet'), ('office', 'Office')],
        'government': [('hq', 'Headquarters'), ('provincial', 'Provincial office'), ('district', 'District office (DACO)'), ('camp', 'Agricultural camp'), ('research', 'Research station')],
        'ngo': [('country', 'Country office'), ('field', 'Field office'), ('project', 'Project site')],
    }
    KINDS['donor'] = KINDS['ngo']
    ALL_KINDS = sorted({k for v in KINDS.values() for k, _ in v})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=30, blank=True)
    kind = models.CharField(max_length=20, default='site')
    province = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_headquarters = models.BooleanField(default=False, help_text='HQ members are organisation-wide, not branch-scoped')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'org_branches'
        ordering = ['-is_headquarters', 'name']
        unique_together = [('organization', 'name')]

    def __str__(self):
        return f'{self.name} ({self.organization.name})'

    @classmethod
    def kinds_for(cls, org_type):
        return cls.KINDS.get(org_type, cls.KINDS['farm'])

    def get_kind_display(self):
        return dict((k, l) for v in self.KINDS.values() for k, l in v).get(self.kind, self.kind)


class AccessAuditLog(models.Model):
    """Who changed whose access — invites, roles, permissions, branches, activation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='access_audit')
    actor = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    target = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    action = models.CharField(max_length=40)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField()

    class Meta:
        db_table = 'access_audit_log'
        ordering = ['-created_at']


class ParticipantProfile(models.Model):
    """Household / demographic profile behind a private-sector organisation, so
    programmes can report people the way donors require (sex, age, youth,
    disability, household size). No names beyond what the organisation already
    holds; the national ID is stored only as a salted hash for de-duplication."""

    SEX_CHOICES = [('F', 'Female'), ('M', 'Male'), ('X', 'Other / prefer not to say')]

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, primary_key=True, related_name='participant_profile')
    head_sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    head_birth_year = models.PositiveIntegerField(null=True, blank=True)
    household_size = models.PositiveIntegerField(null=True, blank=True)
    female_members = models.PositiveIntegerField(null=True, blank=True)
    male_members = models.PositiveIntegerField(null=True, blank=True)
    youth_led = models.BooleanField(null=True, blank=True, help_text='Led by someone 35 or younger')
    disability = models.BooleanField(default=False, help_text='Household includes a person with a disability')
    land_ha = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    national_id_hash = models.CharField(max_length=64, blank=True, db_index=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_participant_profile'

    YOUTH_MAX_AGE = 35

    def head_age(self, year=None):
        if not self.head_birth_year:
            return None
        from django.utils import timezone
        return (year or timezone.localdate().year) - self.head_birth_year

    @property
    def is_youth(self):
        if self.youth_led is not None:
            return self.youth_led
        a = self.head_age()
        return a is not None and a <= self.YOUTH_MAX_AGE


class OrgWorkspace(models.Model):
    """
    The farm shell's workspace (org profile, enterprises, production cycles,
    edit-approval queue) as the web app models it, stored per organisation so
    every member of the company shares one copy across devices. Replaces the
    per-browser localStorage + Supabase sync.
    """
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='workspace', primary_key=True)
    org_data = models.JSONField(default=dict, blank=True)
    cycles = models.JSONField(default=list, blank=True)
    edit_requests = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_org_workspace'
