import uuid
from django.db import models
from django.conf import settings


class DashboardWidget(models.Model):
    SIZE_CHOICES = [
        ('small', 'Small'), ('medium', 'Medium'),
        ('large', 'Large'), ('full', 'Full Width'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='dashboard_widgets'
    )
    profile = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='dashboard_widgets'
    )
    widget_type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    data_source = models.CharField(max_length=100)
    widget_size = models.CharField(max_length=20, choices=SIZE_CHOICES, default='medium')
    widget_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    color = models.CharField(max_length=20, blank=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dashboard_widgets'
        ordering = ['widget_order']

    def __str__(self):
        return self.title


class Report(models.Model):
    TYPE_CHOICES = [
        ('production', 'Production'), ('financial', 'Financial'),
        ('health', 'Health'), ('inventory', 'Inventory'), ('custom', 'Custom'),
    ]
    FORMAT_CHOICES = [('pdf', 'PDF'), ('excel', 'Excel'), ('csv', 'CSV')]
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('processing', 'Processing'),
        ('ready', 'Ready'), ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='reports'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reports'
    )
    name = models.CharField(max_length=255)
    report_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    parameters = models.JSONField(default=dict)
    output_format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='pdf')
    file_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reports'
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reports'
        ordering = ['-generated_at']

    def __str__(self):
        return self.name
