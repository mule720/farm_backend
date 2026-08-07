import uuid
from django.db import models
from django.conf import settings as django_settings


class EnterpriseTemplate(models.Model):
    CATEGORY_CHOICES = [
        ('livestock', 'Livestock'), ('aquaculture', 'Aquaculture'),
        ('crop', 'Crop'), ('horticulture', 'Horticulture'),
        ('dairy', 'Dairy'), ('apiculture', 'Apiculture'),
        ('mushroom', 'Mushroom'), ('hydroponics', 'Hydroponics'),
        ('greenhouse', 'Greenhouse'), ('processing', 'Processing'),
        ('mixed', 'Mixed'), ('custom', 'Custom'),
    ]

    id = models.CharField(max_length=100, primary_key=True)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        null=True, blank=True, related_name='custom_templates'
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    production_type = models.CharField(max_length=100)
    icon = models.CharField(max_length=100, default='leaf')
    color = models.CharField(max_length=20, default='#2D5016')
    description = models.TextField(blank=True)
    is_built_in = models.BooleanField(default=False)
    stages = models.JSONField(default=list)
    kpis = models.JSONField(default=list)
    forms = models.JSONField(default=list)
    inventory_rules = models.JSONField(default=list)
    financial_categories = models.JSONField(default=list)
    automation_rules = models.JSONField(default=list)
    dashboard_widgets = models.JSONField(default=list)
    tags = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enterprise_templates'
        ordering = ['name']

    def __str__(self):
        return self.name


class Enterprise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='enterprises'
    )
    template = models.ForeignKey(
        EnterpriseTemplate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='instances'
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=30)
    production_type = models.CharField(max_length=100)
    icon = models.CharField(max_length=100, default='leaf')
    color = models.CharField(max_length=20, default='#2D5016')
    description = models.TextField(blank=True)
    batch_unit = models.CharField(max_length=50, default='batch')
    settings = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enterprises'
        ordering = ['name']

    def __str__(self):
        return self.name


class EnterpriseStage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enterprise = models.ForeignKey(
        Enterprise, on_delete=models.CASCADE, related_name='stages'
    )
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='+'
    )
    name = models.CharField(max_length=255)
    stage_order = models.PositiveIntegerField(default=0)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    color = models.CharField(max_length=20, default='#2D5016')
    description = models.TextField(blank=True)
    feeding_rules = models.JSONField(default=list)
    health_checks = models.JSONField(default=list)
    kpi_targets = models.JSONField(default=list)
    alerts = models.JSONField(default=list)
    required_records = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enterprise_stages'
        ordering = ['stage_order']

    def __str__(self):
        return f'{self.enterprise.name} — {self.name}'


class EnterpriseBatch(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'), ('completed', 'Completed'), ('cancelled', 'Cancelled')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='+'
    )
    enterprise = models.ForeignKey(
        Enterprise, on_delete=models.CASCADE, related_name='batches'
    )
    name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=100, blank=True)
    current_stage = models.ForeignKey(
        EnterpriseStage, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='active_batches'
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=50, default='units')
    start_date = models.DateField()
    expected_end_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enterprise_batches'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.enterprise.name} — {self.name}'
