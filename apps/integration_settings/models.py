"""
Admin-editable, database-backed credentials for calling out to other
ecosystem services (Payment System, notification_service, the shared
gateway) — the same pattern already shipped in E-commerce, ERP,
Shipping, Bus, and Tourism.

Unlike those five, this app (AgroNexus / farm_backend) currently has NO
existing connection to the ecosystem at all — no payvault client, no
notif_client copy, no shared_gateway reference anywhere in the codebase.
This model exists so that connection has somewhere to live the moment
it's needed (e.g. HireBooking/marketplace payments, order/harvest
notifications) — an admin generates the actual credential on the OTHER
app's own dashboard, then pastes it in here.
"""
import uuid

from django.db import models

from apps.integration_settings.crypto import aes_encrypt, aes_decrypt


class IntegrationCredential(models.Model):
    class Service(models.TextChoices):
        PAYMENT = 'payment', 'Payment System'
        NOTIFICATION = 'notification', 'Notification Service'
        GATEWAY = 'gateway', 'Shared Gateway'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.CharField(max_length=20, choices=Service.choices, unique=True)

    base_url = models.URLField(blank=True, help_text='e.g. https://payments.afriswip.com')
    app_id = models.CharField(
        max_length=200, blank=True,
        help_text="Non-secret identifier for this app on the other side, e.g. Payment's app_id / NOTIF_APPLICATION_CODE",
    )

    # Encrypted at rest (AES-256-GCM, apps/integration_settings/crypto.py).
    # Never returned to the frontend in plaintext once saved — only a
    # masked preview (see IntegrationCredential.masked below).
    encrypted_api_key = models.TextField(blank=True)
    encrypted_secret = models.TextField(blank=True, help_text='For services needing a second value, e.g. a webhook secret')

    is_active = models.BooleanField(default=True)
    updated_by = models.CharField(max_length=200, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_credentials'
        verbose_name = 'Integration Credential'
        verbose_name_plural = 'Integration Credentials'

    def __str__(self):
        return f"{self.get_service_display()} ({'active' if self.is_active else 'inactive'})"

    # ── Encrypted field accessors ────────────────────────────────────────────

    def set_api_key(self, plaintext: str) -> None:
        self.encrypted_api_key = aes_encrypt(plaintext) if plaintext else ''

    def get_api_key(self) -> str:
        return aes_decrypt(self.encrypted_api_key) if self.encrypted_api_key else ''

    def set_secret(self, plaintext: str) -> None:
        self.encrypted_secret = aes_encrypt(plaintext) if plaintext else ''

    def get_secret(self) -> str:
        return aes_decrypt(self.encrypted_secret) if self.encrypted_secret else ''

    @staticmethod
    def masked(value: str) -> str:
        if not value:
            return ''
        if len(value) <= 4:
            return '••••'
        return '••••' + value[-4:]
