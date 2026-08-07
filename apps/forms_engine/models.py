import uuid
from django.db import models
from django.conf import settings


class CustomField(models.Model):
    FIELD_TYPE_CHOICES = [
        ('text', 'Text'), ('number', 'Number'), ('date', 'Date'),
        ('dropdown', 'Dropdown'), ('boolean', 'Yes/No'), ('image', 'Image'),
        ('gps', 'GPS Location'), ('sensor', 'Sensor'), ('formula', 'Formula'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='custom_fields'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='custom_fields'
    )
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES)
    is_required = models.BooleanField(default=False)
    options = models.JSONField(default=list)
    formula = models.TextField(blank=True)
    unit = models.CharField(max_length=50, blank=True)
    min_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    default_value = models.TextField(blank=True)
    sensor_id = models.CharField(max_length=100, blank=True)
    field_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'custom_fields'
        ordering = ['field_order', 'label']

    def __str__(self):
        return self.label


class Form(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'), ('per_batch', 'Per Batch'), ('weekly', 'Weekly'),
        ('per_harvest', 'Per Harvest'), ('ad_hoc', 'Ad Hoc'),
        ('per_inspection', 'Per Inspection'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='forms'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='forms'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    frequency = models.CharField(max_length=30, choices=FREQUENCY_CHOICES, default='daily')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'forms'
        ordering = ['name']

    def __str__(self):
        return self.name


class FormField(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name='fields')
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='+'
    )
    custom_field = models.ForeignKey(
        CustomField, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='form_usages'
    )
    label = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20)
    is_required = models.BooleanField(default=False)
    options = models.JSONField(default=list)
    formula = models.TextField(blank=True)
    unit = models.CharField(max_length=50, blank=True)
    field_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'form_fields'
        ordering = ['field_order']

    def __str__(self):
        return f'{self.form.name} / {self.label}'


class FormSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='submissions'
    )
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name='submissions')
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='submissions'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='submissions'
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='submissions'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=dict)
    gps_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'form_submissions'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.form.name} — {self.submitted_at.date()}'
