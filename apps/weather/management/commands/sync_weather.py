"""Pull live forecasts (Open-Meteo) and satellite NDVI (NASA MODIS) for every
organisation — the cron-friendly equivalent of the Celery tasks."""
from django.core.management.base import BaseCommand

from apps.accounts.models import Organization
from apps.weather.services import sync_organization


class Command(BaseCommand):
    help = 'Sync weather forecasts and NDVI for all organisations (or one, with --org-slug)'

    def add_arguments(self, parser):
        parser.add_argument('--org-slug', help='Only this organisation')
        parser.add_argument('--skip-ndvi', action='store_true')
        parser.add_argument('--skip-weather', action='store_true')

    def handle(self, *args, **opts):
        qs = Organization.objects.filter(is_active=True)
        if opts['org_slug']:
            qs = qs.filter(slug=opts['org_slug'])
        kwargs = {}
        if opts['skip_ndvi']:
            kwargs['fetch_ndvi'] = lambda *a, **k: []
        if opts['skip_weather']:
            kwargs['fetch_weather'] = lambda *a, **k: {'current': {}, 'daily': []}
        for org in qs:
            s = sync_organization(org, **kwargs)
            self.stdout.write(f'{org.name}: {s["stations"]} stations / {s["forecast_days"]} forecast days, '
                              f'{s["fields"]} fields / {s["ndvi_records"]} new NDVI'
                              + (f', errors: {s["errors"]}' if s['errors'] else ''))
