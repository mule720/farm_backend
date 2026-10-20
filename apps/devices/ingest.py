"""Recording a sensor reading: the one place that does it, used by the HTTP endpoint for real devices and the GraphQL mutation."""
import hashlib
import re
import secrets
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.automation.engine import run_all_rules
from .models import Device, DeviceKey, SecurityAlert, SensorReading

ALERT_THRESHOLDS = {            # metric: (lowest ok, highest ok)
    'dissolved_oxygen': (4.0, None),
    'ph': (6.0, 9.0),
    'ammonia': (None, 25.0),
    'co2': (None, 2000.0),
}
DEFAULT_UNITS = {
    'temperature': 'C', 'humidity': '%', 'ph': 'pH', 'dissolved_oxygen': 'mg/L', 'ammonia': 'ppm', 'co2': 'ppm',
    'weight': 'kg', 'light': 'lux', 'pressure': 'hPa', 'soil_moisture': '%', 'water_level': '%', 'battery': '%',
}
MAX_DEVICES_PER_ORG = 500
METRIC_RE = re.compile(r'^[a-z0-9_]{1,50}$')


class IngestError(Exception):
    pass


def new_key():
    """-> (plaintext, prefix, sha256 hex). The plaintext is shown once and never stored."""
    plain = 'agk_' + secrets.token_urlsafe(32)
    return plain, plain[:8], hash_key(plain)


def hash_key(plain):
    return hashlib.sha256(plain.encode()).hexdigest()


def find_key(plain):
    if not plain or not plain.startswith('agk_'):
        return None
    return DeviceKey.objects.select_related('organization').filter(key_hash=hash_key(plain), is_active=True).first()


def resolve_device(org, ref, allow_new, name='', device_type='sensor'):
    ref = str(ref or '').strip()[:100]
    if not ref:
        raise IngestError('"device" is missing')
    dev = None
    try:
        import uuid
        dev = Device.objects.filter(organization=org, id=uuid.UUID(ref)).first()
    except ValueError:
        pass
    if dev is None:
        dev = Device.objects.filter(organization=org, identifier=ref).first()
    if dev is None:
        if not allow_new:
            raise IngestError(f'unknown device "{ref}" (create it in the app first, or use a key that allows new devices)')
        if Device.objects.filter(organization=org).count() >= MAX_DEVICES_PER_ORG:
            raise IngestError('device limit reached')
        dev = Device.objects.create(organization=org, name=(name or ref)[:255], identifier=ref,
                                    device_type=device_type if device_type in dict(Device.TYPE_CHOICES) else 'sensor', status='online')
    return dev


def record_reading(org, device, metric, value, unit='', user=None, enterprise_id=None, battery=None, signal=None):
    """Save one reading, update the device, raise an alert when it is outside the safe range and run the automation rules."""
    metric = str(metric or '').strip().lower().replace(' ', '_').replace('-', '_')
    if not METRIC_RE.match(metric):
        raise IngestError('"metric" must be letters, numbers and underscores, e.g. soil_moisture')
    try:
        val = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise IngestError('"value" must be a number')
    if val.is_nan() or val.is_infinite() or abs(val) > Decimal('99999999'):
        raise IngestError('"value" is out of range')
    unit = (str(unit or '') or DEFAULT_UNITS.get(metric, ''))[:30]

    is_alert = False
    th = ALERT_THRESHOLDS.get(metric)
    if th:
        lo, hi = th
        is_alert = (lo is not None and float(val) < lo) or (hi is not None and float(val) > hi)

    reading = SensorReading.objects.create(
        organization=org, device=device, enterprise_id=enterprise_id or device.enterprise_id,
        metric=metric, value=val, unit=unit, is_alert=is_alert,
    )
    device.status = 'warning' if is_alert else 'online'
    device.last_seen_at = timezone.now()
    fields = ['status', 'last_seen_at']
    if battery is not None:
        try:
            device.battery_pct = max(0, min(100, int(float(battery))))
            fields.append('battery_pct')
        except (TypeError, ValueError):
            pass
    if signal is not None:
        try:
            device.signal_strength = max(0, min(100, int(float(signal))))
            fields.append('signal_strength')
        except (TypeError, ValueError):
            pass
    device.save(update_fields=fields)

    triggered = run_all_rules(org, metric, float(val), user)
    if is_alert:
        SecurityAlert.objects.create(
            organization=org, source='sensor', source_id=device.id, severity='critical',
            title=f'Sensor Alert: {metric.replace("_", " ").title()} - {device.name}',
            detail=f'Value {val} {unit} is outside the safe range.',
        )
    return reading, len(triggered), is_alert
