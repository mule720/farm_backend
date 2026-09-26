"""
Live weather / NDVI pipeline tests. Providers are mocked; one optional test
hits the real APIs when AGRINUXES_LIVE_TESTS=1.
"""
import json
import os
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from apps.weather.models import WeatherStation, WeatherReading, WeatherForecast, FarmField, NDVIRecord
from apps.weather import services
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


TODAY = date.today()


def _fake_weather(lat, lon, days=7):
    daily = []
    specs = [(0, 31, 17, 0, 5, 12), (63, 24, 15, 25, 90, 18), (95, 22, 14, 12, 70, 48),
             (1, 36, 19, 0, 0, 10), (2, 20, 1, 0, 10, 8), (3, 26, 14, 1, 30, 15), (1, 28, 15, 0, 10, 9)]
    for i, (code, tmax, tmin, rain, prob, wind) in enumerate(specs[:days]):
        daily.append({'date': TODAY + timedelta(days=i), 'code': code, 'condition': services._WMO[code],
                      'temp_max': tmax, 'temp_min': tmin, 'rain_mm': rain, 'rain_prob': prob,
                      'wind_max': wind, 'et0': 6.5 if i == 0 else 3.0, 'uv_max': 8})
    current = {'time': f'{TODAY.isoformat()}T10:00', 'temperature_2m': 27.4, 'relative_humidity_2m': 55,
               'wind_speed_10m': 9.2, 'wind_direction_10m': 120, 'precipitation': 0.0, 'surface_pressure': 896.0}
    return {'current': current, 'daily': daily}


def _fake_ndvi(lat, lon, since=None, composites=6):
    return [(TODAY - timedelta(days=48), 0.31), (TODAY - timedelta(days=32), 0.52), (TODAY - timedelta(days=16), 0.71)]


class _Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Sky Farm', slug='sky-farm', org_type='farm')
        self.user = Profile.objects.create_user(email='d@sky.test', full_name='D', password='pw12345678',
                                                phone='0977123123', organization=self.org, role='director')
        self.station = WeatherStation.objects.create(organization=self.org, name='HQ', latitude=Decimal('-15.33'),
                                                     longitude=Decimal('28.52'))
        self.field = FarmField.objects.create(organization=self.org, name='Block A', crop_type='Maize',
                                              crop_stage='vegetative', area_ha=2, latitude=Decimal('-15.33'),
                                              longitude=Decimal('28.52'), nearest_station=self.station)


class AdvisoryRulesTest(TestCase):
    def test_conditions_and_advisories(self):
        d = _fake_weather(0, 0)['daily']
        self.assertEqual(services.classify_condition(d[0]), 'sunny')
        self.assertEqual(services.classify_condition(d[3]), 'heat_wave')
        self.assertEqual(services.classify_condition(d[4]), 'frost')
        self.assertIn('Dry day', services.farming_advisory(d[0]))
        self.assertIn('evapotranspiration', services.farming_advisory(d[0]))
        self.assertIn('Heavy rain', services.farming_advisory(d[1]))
        self.assertIn('Thunderstorms', services.farming_advisory(d[2]))
        self.assertIn('Strong wind', services.farming_advisory(d[2]))
        self.assertIn('Heat', services.farming_advisory(d[3]))
        self.assertIn('Frost risk', services.farming_advisory(d[4]))
        self.assertIn('flowering', services.farming_advisory(d[1], crop_stage='flowering'))

    def test_reading_alerts(self):
        self.assertEqual(services.reading_alert({'temperature_2m': 36}), (True, 'heat'))
        self.assertEqual(services.reading_alert({'temperature_2m': 1}), (True, 'frost'))
        self.assertEqual(services.reading_alert({'temperature_2m': 25, 'wind_speed_10m': 45}), (True, 'strong_wind'))
        self.assertEqual(services.reading_alert({'temperature_2m': 25, 'precipitation': 8}), (True, 'heavy_rain'))
        self.assertEqual(services.reading_alert({'temperature_2m': 25}, {'rain_mm': 25, 'condition': 'heavy_rain'}), (True, 'heavy_rain_expected'))
        self.assertEqual(services.reading_alert({'temperature_2m': 25}, {'rain_mm': 0, 'condition': 'sunny'}), (False, ''))

    def test_ndvi_assessment(self):
        self.assertTrue(services.ndvi_assessment(0.72)[0].startswith('Excellent'))
        self.assertTrue(services.ndvi_assessment(0.5)[0].startswith('Good'))
        self.assertTrue(services.ndvi_assessment(0.35)[0].startswith('Fair'))
        self.assertTrue(services.ndvi_assessment(0.2)[0].startswith('Poor'))
        self.assertIn('crop stage', services.ndvi_assessment(0.1, 'fallow')[0])


class StationSyncTest(_Base):
    def test_sync_writes_forecast_and_reading(self):
        n = services.sync_station_forecast(self.station, fetch=_fake_weather)
        self.assertEqual(n, 7)
        fc = list(WeatherForecast.objects.filter(station=self.station).order_by('forecast_date'))
        self.assertEqual(len(fc), 7)
        self.assertEqual(fc[0].forecast_date, TODAY)
        self.assertEqual(fc[1].condition, 'heavy_rain')
        self.assertEqual(fc[1].rain_probability_pct, 90)
        self.assertEqual(fc[3].condition, 'heat_wave')
        self.assertEqual(fc[4].condition, 'frost')
        self.assertIn('Heavy rain', fc[1].farming_advisory)
        r = WeatherReading.objects.get(station=self.station)
        self.assertEqual(r.temperature_c, Decimal('27.40'))
        self.assertEqual(r.humidity_pct, 55)
        self.assertFalse(r.is_alert)
        self.assertIsNotNone(r.dew_point_c)
        self.station.refresh_from_db()
        self.assertEqual(self.station.provider, 'Open-Meteo')

    def test_sync_is_idempotent_upsert(self):
        services.sync_station_forecast(self.station, fetch=_fake_weather)
        services.sync_station_forecast(self.station, fetch=_fake_weather)
        self.assertEqual(WeatherForecast.objects.filter(station=self.station).count(), 7)
        self.assertEqual(WeatherReading.objects.filter(station=self.station).count(), 2)  # readings are a time series

    def test_stale_forecasts_pruned(self):
        WeatherForecast.objects.create(organization=self.org, station=self.station, forecast_date=TODAY - timedelta(days=3))
        services.sync_station_forecast(self.station, fetch=_fake_weather)
        self.assertFalse(WeatherForecast.objects.filter(station=self.station, forecast_date__lt=TODAY).exists())

    def test_station_without_coords_skipped(self):
        st = WeatherStation.objects.create(organization=self.org, name='No GPS')
        self.assertEqual(services.sync_station_forecast(st, fetch=_fake_weather), 0)

    def test_alert_reading(self):
        def hot(lat, lon, days=7):
            d = _fake_weather(lat, lon, days)
            d['current']['temperature_2m'] = 37.0
            return d
        services.sync_station_forecast(self.station, fetch=hot)
        r = WeatherReading.objects.get(station=self.station)
        self.assertTrue(r.is_alert)
        self.assertEqual(r.alert_type, 'heat')


class NdviSyncTest(_Base):
    def test_sync_creates_records_and_updates_field(self):
        n = services.sync_field_ndvi(self.field, fetch=_fake_ndvi)
        self.assertEqual(n, 3)
        self.field.refresh_from_db()
        self.assertEqual(self.field.latest_ndvi, Decimal('0.7100'))
        self.assertEqual(self.field.latest_ndvi_date, TODAY - timedelta(days=16))
        rec = NDVIRecord.objects.filter(field=self.field).order_by('-recorded_at').first()
        self.assertEqual(rec.source, 'satellite')
        self.assertTrue(rec.health_assessment.startswith('Excellent'))
        self.assertTrue(rec.recommendations)

    def test_only_new_composites_added(self):
        services.sync_field_ndvi(self.field, fetch=_fake_ndvi)
        self.assertEqual(services.sync_field_ndvi(self.field, fetch=_fake_ndvi), 0)
        self.assertEqual(NDVIRecord.objects.filter(field=self.field).count(), 3)

    def test_coords_fallback_polygon_then_station(self):
        f = FarmField.objects.create(organization=self.org, name='Poly', gps_boundary=[[-15.3, 28.5], [-15.4, 28.6]])
        lat, lon = services.field_coords(f)
        self.assertAlmostEqual(lat, -15.35)
        self.assertAlmostEqual(lon, 28.55)
        f2 = FarmField.objects.create(organization=self.org, name='Near', nearest_station=self.station)
        self.assertEqual(services.field_coords(f2), (-15.33, 28.52))
        f3 = FarmField.objects.create(organization=self.org, name='Nowhere')
        self.assertIsNone(services.field_coords(f3))
        self.assertEqual(services.sync_field_ndvi(f3, fetch=_fake_ndvi), 0)

    def test_fill_values_ignored(self):
        # Provider returns fill (-3000) for cloudy composites — fetch_modis_ndvi filters them; simulate empty
        self.assertEqual(services.sync_field_ndvi(self.field, fetch=lambda *a, **k: []), 0)


class OrgSyncAndGraphQLTest(_Base):
    def test_org_sync_summary_tolerates_provider_failure(self):
        def boom(*a, **k):
            raise RuntimeError('provider down')
        s = services.sync_organization(self.org, fetch_weather=boom, fetch_ndvi=_fake_ndvi)
        self.assertEqual(s['stations'], 0)
        self.assertEqual(s['ndvi_records'], 3)
        self.assertEqual(len(s['errors']), 1)
        self.assertIn('provider down', s['errors'][0])

    def test_sync_mutations_require_auth_and_scope(self):
        other = Organization.objects.create(name='Other', slug='other-w', org_type='farm')
        other_user = Profile.objects.create_user(email='o@w.test', full_name='O', password='pw12345678',
                                                 phone='0977999999', organization=other, role='director')
        m = 'mutation($id: UUID!) { syncStationForecast(stationId: $id) { forecastDays } }'
        self.assertTrue(_gql(None, m, {'id': str(self.station.id)}).errors)
        self.assertTrue(_gql(other_user, m, {'id': str(self.station.id)}).errors)

    def test_weather_overview_query(self):
        services.sync_station_forecast(self.station, fetch=_fake_weather)
        services.sync_field_ndvi(self.field, fetch=_fake_ndvi)
        q = """query { weatherOverview {
            stations { id name latitude longitude provider lastSyncedAt current { temperatureC humidityPct windSpeedKmh isAlert alertType }
                       forecast { forecastDate condition tempMinC tempMaxC rainProbabilityPct expectedRainfallMm windSpeedKmh farmingAdvisory } }
            fields { id name cropType cropStage areaHa latestNdvi latestNdviDate health ndviHistory { recordedAt ndviValue } }
            rainDays7 expectedRainfallMm7 avgMaxTempC7 alerts { stationName alertType recordedAt } } }"""
        r = _gql(self.user, q)
        self.assertIsNone(r.errors, r.errors)
        o = r.data['weatherOverview']
        self.assertEqual(len(o['stations']), 1)
        st = o['stations'][0]
        self.assertEqual(len(st['forecast']), 7)
        self.assertEqual(st['current']['humidityPct'], 55)
        self.assertEqual(o['rainDays7'], 2)
        self.assertAlmostEqual(o['expectedRainfallMm7'], 38.0)
        f = o['fields'][0]
        self.assertAlmostEqual(f['latestNdvi'], 0.71)
        self.assertTrue(f['health'].startswith('Excellent'))
        self.assertEqual(len(f['ndviHistory']), 3)

    def test_create_field_with_coords_and_sync_ndvi_mutation(self):
        m = 'mutation { createFarmField(name: "Block B", cropType: "Soya", latitude: -15.4, longitude: 28.3) { field { id latitude longitude } } }'
        r = _gql(self.user, m)
        self.assertIsNone(r.errors, r.errors)
        fid = r.data['createFarmField']['field']['id']
        self.assertAlmostEqual(float(r.data['createFarmField']['field']['latitude']), -15.4)
        # sync mutation hits the real provider unless patched — patch via services module attr
        orig = services.fetch_modis_ndvi
        services.fetch_modis_ndvi = _fake_ndvi
        try:
            r = _gql(self.user, 'mutation($id: UUID!) { syncFieldNdvi(fieldId: $id) { newRecords field { latestNdvi } } }', {'id': fid})
        finally:
            services.fetch_modis_ndvi = orig
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['syncFieldNdvi']['newRecords'], 3)

    def test_sync_all_mutation(self):
        origw, orign = services.fetch_open_meteo, services.fetch_modis_ndvi
        services.fetch_open_meteo, services.fetch_modis_ndvi = _fake_weather, _fake_ndvi
        try:
            r = _gql(self.user, 'mutation { syncWeatherNow { stations forecastDays fields ndviRecords errors } }')
        finally:
            services.fetch_open_meteo, services.fetch_modis_ndvi = origw, orign
        self.assertIsNone(r.errors, r.errors)
        d = r.data['syncWeatherNow']
        self.assertEqual((d['stations'], d['forecastDays'], d['fields'], d['ndviRecords']), (1, 7, 1, 3))
        self.assertEqual(d['errors'], [])


class LiveProviderTest(TestCase):
    """Hits the real APIs. Skipped unless AGRINUXES_LIVE_TESTS=1."""

    def test_live_open_meteo_and_modis(self):
        if os.environ.get('AGRINUXES_LIVE_TESTS') != '1':
            self.skipTest('set AGRINUXES_LIVE_TESTS=1 to run')
        w = services.fetch_open_meteo(-15.33, 28.52)
        self.assertEqual(len(w['daily']), 7)
        self.assertIn('temperature_2m', w['current'])
        n = services.fetch_modis_ndvi(-15.33, 28.52)
        self.assertTrue(n)
        self.assertTrue(all(-1 <= v <= 1 for _, v in n))
