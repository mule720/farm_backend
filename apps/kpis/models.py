import uuid
from django.db import models
from django.conf import settings


class KPIDefinition(models.Model):
    AGGREGATION_CHOICES = [
        ('average', 'Average'), ('sum', 'Sum'), ('latest', 'Latest'),
        ('min', 'Minimum'), ('max', 'Maximum'),
    ]
    CATEGORY_CHOICES = [
        ('production', 'Production'), ('financial', 'Financial'),
        ('health', 'Health'), ('quality', 'Quality'),
        ('efficiency', 'Efficiency'), ('environmental', 'Environmental'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='kpis'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='kpis'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50, blank=True)
    aggregation = models.CharField(max_length=20, choices=AGGREGATION_CHOICES, default='average')
    target = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    warning_threshold = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    critical_threshold = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    higher_is_better = models.BooleanField(default=True)
    icon = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=20, blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='production')
    formula = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'kpi_definitions'
        ordering = ['name']

    def __str__(self):
        return self.name


class KPIValue(models.Model):
    SOURCE_CHOICES = [
        ('manual', 'Manual'), ('formula', 'Formula'),
        ('sensor', 'Sensor'), ('import', 'Import'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='+'
    )
    kpi = models.ForeignKey(KPIDefinition, on_delete=models.CASCADE, related_name='values')
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='kpi_values'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='kpi_values'
    )
    value = models.DecimalField(max_digits=14, decimal_places=4)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'kpi_values'
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.kpi.name}: {self.value} ({self.recorded_at.date()})'
