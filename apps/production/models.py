import uuid
from django.db import models
from django.conf import settings


class ProductionRecord(models.Model):
    RECORD_TYPE_CHOICES = [
        ('daily', 'Daily'), ('mortality', 'Mortality'), ('weight', 'Weight Check'),
        ('feed', 'Feed Record'), ('health', 'Health Check'), ('harvest', 'Harvest'),
        ('breeding', 'Breeding'), ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='production_records'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE, related_name='production_records'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='production_records'
    )
    stage = models.ForeignKey(
        'enterprises.EnterpriseStage', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='production_records'
    )
    record_date = models.DateField()
    record_type = models.CharField(max_length=30, choices=RECORD_TYPE_CHOICES, default='daily')
    data = models.JSONField(default=dict)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='production_records'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'production_records'
        ordering = ['-record_date', '-created_at']

    def __str__(self):
        return f'{self.enterprise.name} — {self.record_type} — {self.record_date}'
