"""
The one place any future integration client (a payvault client, a
notif_client copy, a gateway client) should call to get its config —
checks the admin-editable IntegrationCredential table first, falls back
to Django settings for any field not set in the database. Same contract
as the equivalent resolver in E-commerce, ERP, Shipping, Bus, and Tourism.
"""
from django.conf import settings as dj_settings


def get_service_config(
    service: str,
    *,
    url_setting: str = '',
    app_id_setting: str = '',
    api_key_setting: str = '',
    secret_setting: str = '',
    defaults: dict = None,
) -> dict:
    """
    Returns {'base_url', 'app_id', 'api_key', 'secret'} — each field
    individually comes from the active IntegrationCredential row for
    `service` if set there, otherwise from the named Django setting (or
    the matching key in `defaults`).
    """
    defaults = defaults or {}
    cfg = {
        'base_url': (getattr(dj_settings, url_setting, '') if url_setting else '') or defaults.get('base_url', ''),
        'app_id': (getattr(dj_settings, app_id_setting, '') if app_id_setting else '') or defaults.get('app_id', ''),
        'api_key': (getattr(dj_settings, api_key_setting, '') if api_key_setting else '') or defaults.get('api_key', ''),
        'secret': (getattr(dj_settings, secret_setting, '') if secret_setting else '') or defaults.get('secret', ''),
    }

    try:
        from .models import IntegrationCredential
        row = IntegrationCredential.objects.get(service=service, is_active=True)
    except Exception:
        return cfg

    if row.base_url:
        cfg['base_url'] = row.base_url
    if row.app_id:
        cfg['app_id'] = row.app_id
    api_key = row.get_api_key()
    if api_key:
        cfg['api_key'] = api_key
    secret = row.get_secret()
    if secret:
        cfg['secret'] = secret
    return cfg
