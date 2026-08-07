import uuid
from django.db import models
from django.conf import settings


class CarbonEntry(models.Model):
    CATEGORY_CHOICES = [
        ('fuel', 'Fuel Combustion'), ('electricity', 'Electricity Use'),
        ('enteric', 'Enteric Fermentation (Livestock)'), ('manure', 'Manure Management'),
        ('fertilizer', 'Synthetic Fertilizer'), ('transport', 'Transport & Logistics'),
        ('packaging', 'Packaging'), ('deforestation', 'Land Use Change'), ('other', 'Other'),
    ]
    ENTRY_TYPE_CHOICES = [('emission', 'Emission'), ('offset', 'Carbon Offset / Sequestration')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='carbon_entries')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='carbon_entries')
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPE_CHOICES, default='emission')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=4, help_text='Source quantity, e.g. litres of diesel')
    unit = models.CharField(max_length=30, help_text='e.g. litres, kWh, head, tonnes')
    co2e_kg = models.DecimalField(max_digits=14, decimal_places=4, help_text='CO2 equivalent in kg')
    emission_factor = models.DecimalField(max_digits=10, decimal_places=6, default=0, help_text='kg CO2e per unit')
    credit_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Value of carbon credits if offset')
    entry_date = models.DateField()
    source_reference = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'carbon_entries'
        ordering = ['-entry_date']

    def save(self, *args, **kwargs):
        if self.emission_factor and self.quantity:
            self.co2e_kg = float(self.quantity) * float(self.emission_factor)
        super().save(*args, **kwargs)


class WaterUsageEntry(models.Model):
    SOURCE_CHOICES = [
        ('borehole', 'Borehole'), ('river', 'River Abstraction'), ('dam', 'Dam / Reservoir'),
        ('rainwater', 'Rainwater Harvesting'), ('municipal', 'Municipal Supply'), ('recycled', 'Recycled / Treated'),
    ]
    USE_CHOICES = [
        ('irrigation', 'Crop Irrigation'), ('livestock', 'Livestock Watering'), ('cleaning', 'Facility Cleaning'),
        ('processing', 'Product Processing'), ('domestic', 'Domestic / Staff'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='water_entries')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='water_entries')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    use_type = models.CharField(max_length=20, choices=USE_CHOICES)
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=3)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    entry_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'water_usage_entries'
        ordering = ['-entry_date']


class CertificationRecord(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'), ('in_progress', 'In Progress'),
        ('certified', 'Certified'), ('expired', 'Expired'), ('suspended', 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='certifications')
    certification_name = models.CharField(max_length=255, help_text='e.g. GlobalG.A.P., Organic, Rainforest Alliance')
    certifying_body = models.CharField(max_length=255)
    certificate_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    scope = models.TextField(blank=True, help_text='What products/activities are covered')
    document_url = models.CharField(max_length=500, blank=True)
    renewal_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'certification_records'
        ordering = ['expiry_date']


class ComplianceTask(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'), ('in_progress', 'In Progress'), ('done', 'Completed'), ('overdue', 'Overdue'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='compliance_tasks')
    certification = models.ForeignKey(CertificationRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    due_date = models.DateField()
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='compliance_tasks')
    completed_at = models.DateTimeField(null=True, blank=True)
    evidence_url = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'compliance_tasks'
        ordering = ['due_date']


class AuditRecord(models.Model):
    RESULT_CHOICES = [
        ('pass', 'Pass'), ('minor_nc', 'Minor Non-Conformance'),
        ('major_nc', 'Major Non-Conformance'), ('critical_nc', 'Critical Non-Conformance'),
        ('pending', 'Pending Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='audit_records')
    certification = models.ForeignKey(CertificationRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='audits')
    auditor_name = models.CharField(max_length=255)
    auditor_company = models.CharField(max_length=255, blank=True)
    audit_date = models.DateField()
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default='pending')
    score_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    findings = models.JSONField(default=list)
    corrective_actions = models.JSONField(default=list)
    follow_up_date = models.DateField(null=True, blank=True)
    report_url = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_records'
        ordering = ['-audit_date']


class ManureBiogasRecord(models.Model):
    RECORD_TYPE_CHOICES = [
        ('manure_collected', 'Manure Collected'), ('biogas_output', 'Biogas Output'),
        ('compost_turned', 'Compost Turned'), ('compost_ready', 'Compost Ready'),
        ('effluent_treated', 'Effluent Treated'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='manure_biogas_records')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='manure_biogas_records')
    record_type = models.CharField(max_length=20, choices=RECORD_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=30, help_text='e.g. kg, m³, litres, bags')
    biogas_m3 = models.DecimalField(max_digits=10, decimal_places=3, default=0, help_text='Biogas volume if applicable')
    energy_kwh_equivalent = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    compost_batch_id = models.CharField(max_length=100, blank=True)
    compost_maturity_days = models.PositiveSmallIntegerField(default=0)
    record_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'manure_biogas_records'
        ordering = ['-record_date']
