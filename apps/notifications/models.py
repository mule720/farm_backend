import uuid
from django.db import models
from django.conf import settings


class Notification(models.Model):

    CATEGORY_CHOICES = [
        ('alert',        'Alert'),
        ('automation',   'Automation'),
        ('weather',      'Weather'),
        ('kpi',          'KPI'),
        ('irrigation',   'Irrigation'),
        ('livestock',    'Livestock'),
        ('equipment',    'Equipment'),
        ('financial',    'Financial'),
        ('labor',        'Labour'),
        ('inventory',    'Inventory'),
        ('market',       'Market'),
        ('compliance',   'Compliance'),
        ('vision',       'AI Vision'),
        ('system',       'System'),
    ]

    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('warning',  'Warning'),
        ('info',     'Info'),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    title      = models.CharField(max_length=200)
    message    = models.TextField()
    category   = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='system')
    priority   = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='info')
    is_read    = models.BooleanField(default=False)
    read_at    = models.DateTimeField(null=True, blank=True)
    # Optional link — e.g. "/irrigation" so clicking takes user to the right page
    action_url = models.CharField(max_length=200, blank=True)
    # Optional reference to any related object (e.g. irrigation zone id)
    ref_id     = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.priority}] {self.title} → {self.recipient}'
