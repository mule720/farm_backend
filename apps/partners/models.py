import uuid
from django.conf import settings
from django.db import models


class Programme(models.Model):
    """A development programme run by a supporting partner (FAO, donor, NGO).
    Farms are enrolled from those that opted in to data sharing; the partner
    sees enrolled farms by name, and de-identified aggregates elsewhere."""

    STATUS_CHOICES = [
        ('planning', 'Planning'), ('active', 'Active'),
        ('closed', 'Closed'), ('suspended', 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='programmes',
        help_text='The partner organisation running the programme',
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, help_text='Internal / donor reference, e.g. GCP/ZAM/123')
    description = models.TextField(blank=True)
    funder = models.CharField(max_length=255, blank=True, help_text='e.g. FAO, EU, USAID')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    # Targeting — empty list means "any"
    target_provinces = models.JSONField(default=list)
    target_districts = models.JSONField(default=list)
    target_enterprise_categories = models.JSONField(default=list)
    # Participant types (Organization.business_type values) — empty = any consenting organisation
    target_participant_types = models.JSONField(default=list)
    target_farms = models.PositiveIntegerField(default=0, help_text='Enrolment target (participants)')
    # Results framework: [{key, label, unit, target}] — readings recorded separately
    indicators = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'partner_programmes'
        ordering = ['-start_date', 'name']

    def __str__(self):
        return f'{self.name} ({self.organization.name})'


class ProgrammeEnrollment(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('completed', 'Completed'), ('withdrawn', 'Withdrawn')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='enrollments')
    farm = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='programme_enrollments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    cohort = models.CharField(max_length=100, blank=True, help_text='e.g. 2026 Season A, Camp 3')
    notes = models.TextField(blank=True)
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'partner_enrollments'
        unique_together = [('programme', 'farm')]
        ordering = ['-enrolled_at']


class ProgrammeSupport(models.Model):
    """Something delivered to an enrolled farm: inputs, a grant, training…
    The ledger behind 'what did the programme actually deliver'."""

    TYPE_CHOICES = [
        ('input_voucher', 'Input Voucher'), ('seed', 'Seed / Seedlings'), ('fertiliser', 'Fertiliser'),
        ('livestock', 'Livestock / Fingerlings / Chicks'), ('equipment', 'Equipment / Tools'),
        ('cash_grant', 'Cash Grant'), ('training', 'Training'), ('extension', 'Extension Service'),
        ('market_link', 'Market Linkage'), ('working_capital', 'Working Capital / Grant'), ('certification', 'Certification Support'),
        ('digital_tools', 'Digital Tools / Devices'), ('cold_chain', 'Cold Chain / Storage'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='support')
    farm = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='programme_support')
    support_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit = models.CharField(max_length=30, blank=True)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text='Monetary value')
    currency = models.CharField(max_length=10, default='ZMW')
    delivered_on = models.DateField()
    reference = models.CharField(max_length=100, blank=True, help_text='Voucher / GRN / receipt number')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_support'
        ordering = ['-delivered_on', '-created_at']


class ResultChain(models.Model):
    """One node of the logical framework: goal → outcomes → outputs → activities."""

    LEVELS = [('goal', 'Goal / Impact'), ('outcome', 'Outcome'), ('output', 'Output'), ('activity', 'Activity')]
    LEVEL_ORDER = {'goal': 0, 'outcome': 1, 'output': 2, 'activity': 3}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='results_chain')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    level = models.CharField(max_length=10, choices=LEVELS)
    code = models.CharField(max_length=20, blank=True, help_text='e.g. 1.2 or Output 3')
    statement = models.CharField(max_length=500)
    assumptions = models.TextField(blank=True, help_text='Assumptions / risks for this level')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_results_chain'
        ordering = ['order', 'created_at']


class Indicator(models.Model):
    """A results-framework indicator with baseline, target, means of verification
    and the disaggregation dimensions donors require (sex, age, participant type, district).
    ``auto_source`` lets the platform compute the value from its own records."""

    AUTO_SOURCES = [
        ('', 'Manual readings'),
        ('participants_enrolled', 'Participants enrolled (active)'),
        ('participants_women', 'Women-headed participants'),
        ('participants_youth', 'Youth-headed participants (≤ 35)'),
        ('households_reached', 'Household members reached'),
        ('participants_supported', 'Participants who received support'),
        ('support_events', 'Support events delivered'),
        ('training_events', 'Training events delivered'),
        ('support_value', 'Value of support delivered'),
        ('harvest_quantity', 'Harvest quantity logged since start'),
        ('market_listings', 'Active market listings'),
        ('contracts_fulfilled', 'Contracts fulfilled since start'),
    ]
    DISAGGREGATIONS = ['sex', 'age', 'participant_type', 'district']

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='indicator_defs')
    result = models.ForeignKey(ResultChain, on_delete=models.SET_NULL, null=True, blank=True, related_name='indicators')
    key = models.CharField(max_length=60)
    label = models.CharField(max_length=255)
    unit = models.CharField(max_length=40, blank=True)
    baseline = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    baseline_date = models.DateField(null=True, blank=True)
    target = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    means_of_verification = models.CharField(max_length=255, blank=True)
    data_source = models.CharField(max_length=255, blank=True)
    disaggregations = models.JSONField(default=list, help_text='subset of sex / age / participant_type / district')
    auto_source = models.CharField(max_length=30, blank=True, choices=AUTO_SOURCES)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_indicators'
        unique_together = [('programme', 'key')]
        ordering = ['order', 'created_at']

    def as_legacy(self):
        return {'key': self.key, 'label': self.label, 'unit': self.unit, 'target': float(self.target) if self.target is not None else None}


class IndicatorReading(models.Model):
    """A periodic value for one results-framework indicator of a programme.
    ``disaggregation`` holds the breakdown, e.g. {"sex": {"F": 120, "M": 80}, "age": {"youth": 60, "adult": 140}}."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='readings')
    indicator = models.ForeignKey(Indicator, on_delete=models.CASCADE, null=True, blank=True, related_name='readings')
    indicator_key = models.CharField(max_length=60)
    period = models.DateField(help_text='Reporting period end date')
    value = models.DecimalField(max_digits=16, decimal_places=2)
    disaggregation = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_indicator_readings'
        ordering = ['indicator_key', '-period']
