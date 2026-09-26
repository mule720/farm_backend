import uuid
from django.db import models
from django.conf import settings


class VideoCall(models.Model):
    """
    Tracks a Jitsi video consultation between a farmer (initiator) and a
    provider (or any two users).  The room_name is a random UUID so each call
    gets its own isolated Jitsi room; callers receive a short-lived JWT they
    exchange for Jitsi access.
    """

    STATUS_CHOICES = [
        ('pending',  'Pending'),   # created, counterpart not yet joined
        ('active',   'Active'),    # both parties joined
        ('ended',    'Ended'),     # one party hung up
        ('missed',   'Missed'),    # counterpart never joined within timeout
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_name       = models.CharField(max_length=100, unique=True)
    initiator       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='initiated_video_calls',
    )
    counterpart     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_video_calls',
        null=True, blank=True,
    )
    # Optional FK to the marketplace provider being called
    provider_id     = models.UUIDField(null=True, blank=True)
    provider_name   = models.CharField(max_length=200, blank=True)
    subject         = models.CharField(max_length=200, blank=True)  # e.g. "Vet consult – poultry"
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    started_at      = models.DateTimeField(auto_now_add=True)
    joined_at       = models.DateTimeField(null=True, blank=True)
    ended_at        = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'video_calls'
        ordering = ['-started_at']

    def __str__(self):
        return f'VideoCall {self.room_name} [{self.status}]'
