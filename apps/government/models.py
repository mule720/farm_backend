import uuid
from django.conf import settings
from django.db import models


class Advisory(models.Model):
    """A broadcast from a government / partner organisation to farmers in a
    geographic scope. Delivery fans out into per-user Notification rows for
    every consenting farm in scope; this row is the audit record."""

    CATEGORY_CHOICES = [
        ('weather', 'Weather Warning'),
        ('disease', 'Disease / Pest Alert'),
        ('market', 'Market / Price Notice'),
        ('programme', 'Programme / Subsidy'),
        ('general', 'General Advisory'),
    ]
    PRIORITY_CHOICES = [
        ('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='advisories',
        help_text='Issuing government / partner organisation',
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='info')
    # Scope — blank means "all". District implies its province.
    province = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    enterprise_category = models.CharField(max_length=30, blank=True, help_text='e.g. crop, livestock — blank = all')
    farms_reached = models.PositiveIntegerField(default=0)
    recipients_reached = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gov_advisories'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.district or self.province or "national"})'
