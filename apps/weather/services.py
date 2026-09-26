"""
Live weather + satellite NDVI providers.

  * Open-Meteo (https://open-meteo.com) — free, no API key. 7-day daily
    forecast + current conditions for any lat/lon.
  * NASA ORNL DAAC MODIS subset service (https://modis.ornl.gov/rst/) — free,
    no API key. MOD13Q1 250 m NDVI, 16-day composites, for a lat/lon.

Both are pure functions of (lat, lon) so they are easy to mock in tests;
the `sync_*` helpers write into the existing weather models and are what
the Celery tasks and the on-demand GraphQL mutations call.
"""
import logging
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import requests
from django.db import transaction
from django.utils import timezone

from .models import WeatherStation, WeatherReading, WeatherForecast, FarmField, NDVIRecord

log = logging.getLogger(__name__)

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
MODIS_URL = 'https://modis.ornl.gov/rst/api/v1/MOD13Q1'
TIMEOUT = 30

# WMO weather interpretation codes (Open-Meteo) → WeatherForecast.condition
_WMO = {
    0: 'sunny', 1: 'sunny', 2: 'partly_cloudy', 3: 'cloudy',
    45: 'cloudy', 48: 'cloudy',
    51: 'light_rain', 53: 'light_rain', 55: 'light_rain', 56: 'light_rain', 57: 'light_rain',
    61: 'light_rain', 63: 'heavy_rain', 65: 'heavy_rain', 66: 'light_rain', 67: 'heavy_rain',
    71: 'frost', 73: 'frost', 75: 'frost', 77: 'frost',
    80: 'light_rain', 81: 'heavy_rain', 82: 'heavy_rain', 85: 'frost', 86: 'frost',
    95: 'thunderstorm', 96: 'thunderstorm', 99: 'thunderstorm',
}

# Alert thresholds (Zambian smallholder context)
HEAVY_RAIN_MM = 20
STRONG_WIND_KMH = 40
HEAT_C = 35
FROST_C = 2


def _d(v, places=2):
    return None if v is None else Decimal(str(round(float(v), places)))


# ─── Open-Meteo ───────────────────────────────────────────────────────────────

def fetch_open_meteo(lat, lon, days=7):
    """Return {'current': {...}, 'daily': [{...}, ...]} or raise."""
    r = requests.get(OPEN_METEO_URL, params={
        'latitude': float(lat), 'longitude': float(lon),
        'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,'
                   'precipitation,surface_pressure,apparent_temperature',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,'
                 'precipitation_probability_max,wind_speed_10m_max,et0_fao_evapotranspiration,uv_index_max',
        'timezone': 'Africa/Lusaka', 'forecast_days': days,
    }, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    daily = data.get('daily') or {}
    days_out = []
    for i, day in enumerate(daily.get('time') or []):
        code = (daily.get('weather_code') or [None])[i]
        days_out.append({
            'date': date.fromisoformat(day),
            'code': code,
            'condition': _WMO.get(code, 'partly_cloudy'),
            'temp_max': (daily.get('temperature_2m_max') or [None])[i],
            'temp_min': (daily.get('temperature_2m_min') or [None])[i],
            'rain_mm': (daily.get('precipitation_sum') or [0])[i] or 0,
            'rain_prob': (daily.get('precipitation_probability_max') or [0])[i] or 0,
            'wind_max': (daily.get('wind_speed_10m_max') or [0])[i] or 0,
            'et0': (daily.get('et0_fao_evapotranspiration') or [None])[i],
            'uv_max': (daily.get('uv_index_max') or [None])[i],
        })
    return {'current': data.get('current') or {}, 'daily': days_out}


def classify_condition(day):
    """Refine the WMO-based condition with temperature extremes."""
    cond = day['condition']
    if day.get('temp_max') is not None and day['temp_max'] >= HEAT_C and cond in ('sunny', 'partly_cloudy'):
        return 'heat_wave'
    if day.get('temp_min') is not None and day['temp_min'] <= FROST_C:
        return 'frost'
    return cond


def farming_advisory(day, crop_stage=None):
    """Plain-language, rule-based advisory for one forecast day."""
    tips = []
    rain, prob, wind = day['rain_mm'] or 0, day['rain_prob'] or 0, day['wind_max'] or 0
    tmax, tmin, et0 = day.get('temp_max'), day.get('temp_min'), day.get('et0')
    cond = classify_condition(day)

    if cond == 'thunderstorm':
        tips.append('Thunderstorms likely: keep workers and livestock under cover, secure loose structures and unplug sensitive equipment.')
    if rain >= HEAVY_RAIN_MM or cond == 'heavy_rain':
        tips.append(f'Heavy rain (~{rain:.0f} mm): clear drains and contour furrows; delay fertiliser top-dressing to avoid leaching; check fish pond overflow.')
    elif prob >= 50 or cond == 'light_rain':
        tips.append(f'{prob:.0f}% chance of rain: do not spray pesticides or foliar feed today; good day for transplanting and basal dressing.')
    elif prob <= 20 and rain < 1:
        tips.append('Dry day: good for spraying (early morning, before wind picks up), weeding, drying grain and harvesting.')
    if wind >= STRONG_WIND_KMH:
        tips.append(f'Strong wind ({wind:.0f} km/h): no spraying; stake young plants; check greenhouse and poultry house covers.')
    if tmax is not None and tmax >= HEAT_C:
        tips.append(f'Heat ({tmax:.0f}°C): irrigate early morning or evening; provide shade and extra water for poultry and livestock; watch for heat stress in broilers.')
    if tmin is not None and tmin <= FROST_C:
        tips.append(f'Frost risk ({tmin:.0f}°C overnight): cover seedlings and vegetables; irrigate lightly in the evening; keep chicks warm.')
    if et0 is not None and et0 >= 6 and rain < 2:
        tips.append(f'High evapotranspiration ({et0:.1f} mm): crops will need ~{et0:.0f} mm of water today if not rain-fed.')
    if crop_stage == 'flowering' and (prob >= 50 or wind >= 30):
        tips.append('Crops in flowering: rain/wind can reduce pollination — avoid disturbing plants.')
    if not tips:
        tips.append('Mild conditions: suitable for most field operations.')
    return ' '.join(tips)


def reading_alert(current, today=None):
    """(is_alert, alert_type) from current conditions + today's forecast."""
    temp = current.get('temperature_2m')
    wind = current.get('wind_speed_10m') or 0
    rain_now = current.get('precipitation') or 0
    if temp is not None and temp >= HEAT_C:
        return True, 'heat'
    if temp is not None and temp <= FROST_C:
        return True, 'frost'
    if wind >= STRONG_WIND_KMH:
        return True, 'strong_wind'
    if rain_now >= 5:
        return True, 'heavy_rain'
    if today and (today['rain_mm'] or 0) >= HEAVY_RAIN_MM:
        return True, 'heavy_rain_expected'
    if today and today['condition'] == 'thunderstorm':
        return True, 'thunderstorm'
    return False, ''


def sync_station_forecast(station, fetch=fetch_open_meteo):
    """Pull Open-Meteo for a station and upsert 7 forecast rows + 1 current reading.
    Returns the number of forecast days written, or 0 if the station has no coordinates."""
    if station.latitude is None or station.longitude is None:
        return 0
    data = fetch(station.latitude, station.longitude)
    days = data['daily']
    # Crop stage hint from the station's most advanced field (for the advisory)
    stage = FarmField.objects.filter(nearest_station=station).exclude(crop_stage='fallow') \
        .values_list('crop_stage', flat=True).first()
    with transaction.atomic():
        for day in days:
            WeatherForecast.objects.update_or_create(
                station=station, forecast_date=day['date'],
                defaults=dict(
                    organization=station.organization,
                    condition=classify_condition(day),
                    temp_min_c=_d(day['temp_min']), temp_max_c=_d(day['temp_max']),
                    rain_probability_pct=int(round(day['rain_prob'] or 0)),
                    expected_rainfall_mm=_d(day['rain_mm']) or Decimal('0'),
                    wind_speed_kmh=_d(day['wind_max']) or Decimal('0'),
                    farming_advisory=farming_advisory(day, stage),
                ),
            )
        # Drop stale forecast rows outside the fetched window
        if days:
            WeatherForecast.objects.filter(station=station).exclude(
                forecast_date__in=[d['date'] for d in days]).filter(forecast_date__lt=days[0]['date']).delete()
        cur = data['current']
        if cur:
            today = days[0] if days else None
            is_alert, alert_type = reading_alert(cur, today)
            recorded = cur.get('time')
            try:
                recorded_at = timezone.make_aware(datetime.fromisoformat(recorded)) if recorded else timezone.now()
            except (TypeError, ValueError):
                recorded_at = timezone.now()
            WeatherReading.objects.create(
                organization=station.organization, station=station,
                temperature_c=_d(cur.get('temperature_2m')),
                humidity_pct=int(cur['relative_humidity_2m']) if cur.get('relative_humidity_2m') is not None else None,
                wind_speed_kmh=_d(cur.get('wind_speed_10m')),
                wind_direction_deg=int(cur['wind_direction_10m']) if cur.get('wind_direction_10m') is not None else None,
                rainfall_mm=_d(cur.get('precipitation')) or Decimal('0'),
                pressure_hpa=_d(cur.get('surface_pressure')),
                uv_index=_d(today['uv_max']) if today and today.get('uv_max') is not None else None,
                dew_point_c=_d(_dew_point(cur.get('temperature_2m'), cur.get('relative_humidity_2m'))),
                is_alert=is_alert, alert_type=alert_type, recorded_at=recorded_at,
            )
        if not station.provider:
            station.provider = 'Open-Meteo'
            station.save(update_fields=['provider'])
    return len(days)


def _dew_point(t, rh):
    if t is None or rh is None or rh <= 0:
        return None
    a, b = 17.27, 237.7
    g = (a * t) / (b + t) + math.log(rh / 100.0)
    return (b * g) / (a - g)


# ─── NASA MODIS NDVI ──────────────────────────────────────────────────────────

def _modis_date(d):
    return f'A{d.year}{d.timetuple().tm_yday:03d}'


def fetch_modis_ndvi(lat, lon, since=None, composites=6):
    """Return [(date, ndvi_float), ...] for recent 16-day composites (oldest first)."""
    since = since or (date.today() - timedelta(days=16 * composites + 8))
    r = requests.get(f'{MODIS_URL}/subset', params={
        'latitude': float(lat), 'longitude': float(lon), 'band': '250m_16_days_NDVI',
        'startDate': _modis_date(since), 'endDate': _modis_date(date.today()),
        'kmAboveBelow': 0, 'kmLeftRight': 0,
    }, headers={'Accept': 'application/json'}, timeout=60)
    r.raise_for_status()
    data = r.json()
    scale = float(data.get('scale') or 0.0001)
    out = []
    for s in data.get('subset') or []:
        vals = [v for v in (s.get('data') or []) if v is not None and v > -3000]  # -3000 = fill value
        if not vals:
            continue
        out.append((date.fromisoformat(s['calendar_date']), round(sum(vals) / len(vals) * scale, 4)))
    return out


def ndvi_assessment(ndvi, crop_stage=None):
    """(health_assessment, [recommendations]) for an NDVI value."""
    if ndvi >= 0.65:
        health = 'Excellent — dense, vigorous canopy'
        recs = ['Maintain current irrigation and nutrition programme', 'Scout weekly for pests hiding in dense canopy']
    elif ndvi >= 0.45:
        health = 'Good — healthy vegetation'
        recs = ['Continue routine management', 'Consider a light top-dressing if crop is in vegetative stage']
    elif ndvi >= 0.30:
        health = 'Fair — sparse or stressed vegetation'
        recs = ['Walk the field: check for water stress, nutrient deficiency or pest damage',
                'Compare with neighbouring fields; consider soil test']
    elif ndvi >= 0.15:
        health = 'Poor — very little green cover'
        recs = ['Investigate urgently: drought, disease, waterlogging or crop failure likely',
                'Report the issue in the app for extension officer follow-up']
    else:
        health = 'Bare soil / no crop'
        recs = ['Expected if fallow, freshly planted or just harvested']
    if crop_stage in ('fallow', 'land_prep', 'harvested', 'planting') and ndvi < 0.3:
        health += ' (consistent with current crop stage)'
        recs = ['No action needed at this crop stage']
    return health, recs


def field_coords(field):
    """(lat, lon) for a field: explicit coords → polygon centroid → nearest station."""
    if field.latitude is not None and field.longitude is not None:
        return float(field.latitude), float(field.longitude)
    pts = [p for p in (field.gps_boundary or []) if isinstance(p, (list, tuple)) and len(p) == 2]
    if pts:
        return sum(float(p[0]) for p in pts) / len(pts), sum(float(p[1]) for p in pts) / len(pts)
    st = field.nearest_station
    if st and st.latitude is not None and st.longitude is not None:
        return float(st.latitude), float(st.longitude)
    return None


def sync_field_ndvi(field, fetch=fetch_modis_ndvi):
    """Pull MODIS NDVI for a field and create NDVIRecord rows for new composite dates.
    Returns the number of new records written (0 if the field has no coordinates)."""
    coords = field_coords(field)
    if not coords:
        return 0
    lat, lon = coords
    latest = NDVIRecord.objects.filter(field=field, source='satellite').order_by('-recorded_at') \
        .values_list('recorded_at', flat=True).first()
    rows = fetch(lat, lon)
    written = 0
    for d, ndvi in rows:
        if latest and d <= latest:
            continue
        health, recs = ndvi_assessment(ndvi, field.crop_stage)
        NDVIRecord.objects.create(
            organization=field.organization, field=field, ndvi_value=Decimal(str(ndvi)),
            source='satellite', health_assessment=health, recommendations=recs, recorded_at=d,
            zones=[{'zone_name': 'MODIS 250 m pixel', 'ndvi': ndvi, 'health_status': health.split(' — ')[0]}],
        )
        written += 1
    return written


# ─── Org-wide sync ────────────────────────────────────────────────────────────

def sync_organization(org, fetch_weather=fetch_open_meteo, fetch_ndvi=fetch_modis_ndvi):
    """Sync every located station and field of one organisation. Never raises —
    returns a summary dict so a UI button / task can report partial failures."""
    summary = {'stations': 0, 'forecast_days': 0, 'fields': 0, 'ndvi_records': 0, 'errors': []}
    for st in WeatherStation.objects.filter(organization=org, is_active=True):
        try:
            n = sync_station_forecast(st, fetch=fetch_weather)
            if n:
                summary['stations'] += 1
                summary['forecast_days'] += n
        except Exception as e:  # noqa: BLE001 — provider failure must not stop the loop
            log.warning('weather sync failed for station %s: %s', st.id, e)
            summary['errors'].append(f'{st.name}: {e}')
    for f in FarmField.objects.filter(organization=org).select_related('nearest_station'):
        try:
            n = sync_field_ndvi(f, fetch=fetch_ndvi)
            if field_coords(f):
                summary['fields'] += 1
            summary['ndvi_records'] += n
        except Exception as e:  # noqa: BLE001
            log.warning('ndvi sync failed for field %s: %s', f.id, e)
            summary['errors'].append(f'{f.name}: {e}')
    return summary
