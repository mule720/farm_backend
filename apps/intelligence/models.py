import uuid
from django.db import models
from django.conf import settings


class AIRecommendation(models.Model):
    TYPE_CHOICES = [
        ('feeding', 'Feeding'), ('health', 'Health'), ('financial', 'Financial'),
        ('operational', 'Operational'), ('alert', 'Alert'), ('forecast', 'Forecast'),
    ]
    URGENCY_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='ai_recommendations'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ai_recommendations'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ai_recommendations'
    )
    title = models.CharField(max_length=255)
    detail = models.TextField()
    recommendation_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default='medium')
    impact = models.TextField(blank=True)
    data_sources = models.JSONField(default=list)
    is_actioned = models.BooleanField(default=False)
    actioned_at = models.DateTimeField(null=True, blank=True)
    actioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='actioned_recommendations'
    )
    model_version = models.CharField(max_length=50, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ai_recommendations'
        ordering = ['-urgency', '-generated_at']

    def __str__(self):
        return self.title
