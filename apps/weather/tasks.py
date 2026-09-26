"""Scheduled weather / NDVI sync.

Register with django-celery-beat (DatabaseScheduler is configured), e.g.:
  sync_all_weather   — every 6 hours   (Open-Meteo updates hourly; 6 h is plenty)
  sync_all_ndvi      — daily            (MODIS composites arrive every 16 days)
`python manage.py sync_weather` runs the same logic without Celery.
"""
from config.celery import app as celery_app


@celery_app.task(bind=True, max_retries=2)
def sync_all_weather(self):
    from apps.accounts.models import Organization
    from .services import sync_organization, fetch_modis_ndvi
    totals = {'orgs': 0, 'stations': 0, 'forecast_days': 0, 'errors': 0}
    for org in Organization.objects.filter(is_active=True):
        s = sync_organization(org, fetch_ndvi=lambda *a, **k: [])  # weather only
        totals['orgs'] += 1
        totals['stations'] += s['stations']
        totals['forecast_days'] += s['forecast_days']
        totals['errors'] += len(s['errors'])
    return totals


@celery_app.task(bind=True, max_retries=2)
def sync_all_ndvi(self):
    from apps.accounts.models import Organization
    from .services import sync_organization
    totals = {'orgs': 0, 'fields': 0, 'ndvi_records': 0, 'errors': 0}
    for org in Organization.objects.filter(is_active=True):
        s = sync_organization(org, fetch_weather=lambda *a, **k: {'current': {}, 'daily': []})  # ndvi only
        totals['orgs'] += 1
        totals['fields'] += s['fields']
        totals['ndvi_records'] += s['ndvi_records']
        totals['errors'] += len(s['errors'])
    return totals
