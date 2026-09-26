import uuid
from django.conf import settings
from django.db import models


class ExtensionCaseload(models.Model):
    """An extension officer's assignment to a farm. The farm must have opted
    in to data sharing; the officer must belong to a government / partner org."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='caseload',
    )
    farm = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='extension_assignments',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'extension_caseloads'
        unique_together = [('officer', 'farm')]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.officer.full_name} → {self.farm.name}'


class ExtensionVisit(models.Model):
    """A field visit (or remote consultation) logged by an extension officer.
    Replaces the paper visit log; visible to the farm as well."""

    VISIT_TYPE_CHOICES = [
        ('field_visit', 'Field Visit'),
        ('phone', 'Phone Consultation'),
        ('video', 'Video Consultation'),
        ('training', 'Training / Field Day'),
        ('follow_up', 'Follow-up'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='extension_visits',
    )
    farm = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='extension_visits',
    )
    visit_date = models.DateField()
    visit_type = models.CharField(max_length=20, choices=VISIT_TYPE_CHOICES, default='field_visit')
    purpose = models.CharField(max_length=255)
    findings = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    # Optional link back to what triggered the visit
    farmer_report = models.ForeignKey(
        'vision.FarmerReport', on_delete=models.SET_NULL, null=True, blank=True, related_name='extension_visits',
    )
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'extension_visits'
        ordering = ['-visit_date', '-created_at']

    def __str__(self):
        return f'{self.visit_date} {self.farm.name}: {self.purpose}'
