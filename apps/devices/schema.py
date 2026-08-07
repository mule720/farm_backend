import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import Device, SensorReading, DroneFlight, CameraEvent, SecurityAlert
from apps.automation.engine import run_all_rules


class DeviceType(DjangoObjectType):
    class Meta:
        model = Device
        fields = ['id', 'name', 'device_type', 'model', 'firmware_version',
                  'location', 'status', 'battery_pct', 'signal_strength',
                  'last_seen_at', 'config', 'enterprise', 'paired_by',
                  'created_at', 'updated_at']


class SensorReadingType(DjangoObjectType):
    class Meta:
        model = SensorReading
        fields = ['id', 'device', 'enterprise', 'metric', 'value',
                  'unit', 'is_alert', 'recorded_at']


class DroneFlightType(DjangoObjectType):
    class Meta:
        model = DroneFlight
        fields = ['id', 'device', 'enterprise', 'flight_type', 'status',
                  'start_time', 'end_time', 'flight_path', 'area_covered_ha',
                  'altitude_m', 'findings', 'image_urls', 'notes',
                  'piloted_by', 'created_at']


class CameraEventType(DjangoObjectType):
    class Meta:
        model = CameraEvent
        fields = ['id', 'device', 'event_type', 'confidence', 'snapshot_url',
                  'video_clip_url', 'metadata', 'is_reviewed', 'reviewed_by',
                  'detected_at']


class SecurityAlertType(DjangoObjectType):
    class Meta:
        model = SecurityAlert
        fields = ['id', 'source', 'source_id', 'severity', 'title', 'detail',
                  'is_resolved', 'resolved_at', 'resolved_by', 'created_at']


class DeviceStatType(graphene.ObjectType):
    total = graphene.Int()
    online = graphene.Int()
    offline = graphene.Int()
    warning = graphene.Int()


# ─── Inputs ──────────────────────────────────────────────────────────────────

class PairDeviceInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    device_type = graphene.String(required=True)
    enterprise_id = graphene.ID()
    model = graphene.String()
    firmware_version = graphene.String()
    location = graphene.String()
    config = graphene.JSONString()


class SensorReadingInput(graphene.InputObjectType):
    device_id = graphene.ID(required=True)
    metric = graphene.String(required=True)
    value = graphene.Float(required=True)
    unit = graphene.String(required=True)
    enterprise_id = graphene.ID()


class DroneFlightInput(graphene.InputObjectType):
    device_id = graphene.ID()
    enterprise_id = graphene.ID()
    flight_type = graphene.String()
    notes = graphene.String()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class DevicesQuery(graphene.ObjectType):
    devices = graphene.List(
        DeviceType,
        device_type=graphene.String(),
        status=graphene.String(),
        enterprise_id=graphene.ID(),
    )
    device = graphene.Field(DeviceType, id=graphene.ID(required=True))
    device_stats = graphene.Field(DeviceStatType)

    sensor_readings = graphene.List(
        SensorReadingType,
        device_id=graphene.ID(),
        metric=graphene.String(),
        enterprise_id=graphene.ID(),
        alerts_only=graphene.Boolean(),
        limit=graphene.Int(),
    )
    latest_readings = graphene.List(SensorReadingType, device_id=graphene.ID(required=True))

    drone_flights = graphene.List(
        DroneFlightType,
        enterprise_id=graphene.ID(),
        status=graphene.String(),
    )
    drone_flight = graphene.Field(DroneFlightType, id=graphene.ID(required=True))

    camera_events = graphene.List(
        CameraEventType,
        device_id=graphene.ID(),
        event_type=graphene.String(),
        is_reviewed=graphene.Boolean(),
        limit=graphene.Int(),
    )

    security_alerts = graphene.List(
        SecurityAlertType,
        severity=graphene.String(),
        is_resolved=graphene.Boolean(),
        limit=graphene.Int(),
    )

    def resolve_devices(self, info, device_type=None, status=None, enterprise_id=None):
        org = _org(info)
        qs = Device.objects.filter(organization=org)
        if device_type:
            qs = qs.filter(device_type=device_type)
        if status:
            qs = qs.filter(status=status)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_device(self, info, id):
        org = _org(info)
        return Device.objects.get(id=id, organization=org)

    def resolve_device_stats(self, info):
        org = _org(info)
        qs = Device.objects.filter(organization=org)
        return DeviceStatType(
            total=qs.count(),
            online=qs.filter(status='online').count(),
            offline=qs.filter(status='offline').count(),
            warning=qs.filter(status='warning').count(),
        )

    def resolve_sensor_readings(self, info, device_id=None, metric=None,
                                enterprise_id=None, alerts_only=None, limit=100):
        org = _org(info)
        qs = SensorReading.objects.filter(organization=org)
        if device_id:
            qs = qs.filter(device_id=device_id)
        if metric:
            qs = qs.filter(metric=metric)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if alerts_only:
            qs = qs.filter(is_alert=True)
        return qs[:limit]

    def resolve_latest_readings(self, info, device_id):
        org = _org(info)
        device = Device.objects.get(id=device_id, organization=org)
        # One reading per metric
        seen = set()
        results = []
        for r in device.readings.order_by('-recorded_at'):
            if r.metric not in seen:
                seen.add(r.metric)
                results.append(r)
        return results

    def resolve_drone_flights(self, info, enterprise_id=None, status=None):
        org = _org(info)
        qs = DroneFlight.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_drone_flight(self, info, id):
        org = _org(info)
        return DroneFlight.objects.get(id=id, organization=org)

    def resolve_camera_events(self, info, device_id=None, event_type=None,
                               is_reviewed=None, limit=50):
        org = _org(info)
        qs = CameraEvent.objects.filter(organization=org)
        if device_id:
            qs = qs.filter(device_id=device_id)
        if event_type:
            qs = qs.filter(event_type=event_type)
        if is_reviewed is not None:
            qs = qs.filter(is_reviewed=is_reviewed)
        return qs[:limit]

    def resolve_security_alerts(self, info, severity=None, is_resolved=None, limit=50):
        org = _org(info)
        qs = SecurityAlert.objects.filter(organization=org)
        if severity:
            qs = qs.filter(severity=severity)
        if is_resolved is not None:
            qs = qs.filter(is_resolved=is_resolved)
        return qs[:limit]


# ─── Mutations ────────────────────────────────────────────────────────────────

class PairDevice(graphene.Mutation):
    class Arguments:
        input = PairDeviceInput(required=True)

    device = graphene.Field(DeviceType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        device = Device.objects.create(
            organization=user.organization,
            paired_by=user,
            name=input.name,
            device_type=input.device_type,
            enterprise_id=input.get('enterprise_id'),
            model=input.get('model', ''),
            firmware_version=input.get('firmware_version', ''),
            location=input.get('location', ''),
            config=input.get('config') or {},
            status='pairing',
        )
        return PairDevice(device=device)


class UpdateDevice(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        name = graphene.String()
        location = graphene.String()
        status = graphene.String()
        battery_pct = graphene.Int()
        signal_strength = graphene.Int()
        config = graphene.JSONString()

    device = graphene.Field(DeviceType)

    def mutate(self, info, id, name=None, location=None, status=None,
               battery_pct=None, signal_strength=None, config=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        device = Device.objects.get(id=id, organization=user.organization)
        if name is not None:
            device.name = name
        if location is not None:
            device.location = location
        if status is not None:
            device.status = status
        if battery_pct is not None:
            device.battery_pct = battery_pct
        if signal_strength is not None:
            device.signal_strength = signal_strength
        if config is not None:
            device.config = config
        device.last_seen_at = timezone.now()
        device.save()
        return UpdateDevice(device=device)


class UnpairDevice(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'supervisor', 'saas_admin'):
            raise Exception('Permission denied')
        Device.objects.get(id=id, organization=user.organization).delete()
        return UnpairDevice(success=True)


class IngestSensorReading(graphene.Mutation):
    """Ingest a sensor reading; auto-runs automation rules on the metric."""
    class Arguments:
        input = SensorReadingInput(required=True)

    reading = graphene.Field(SensorReadingType)
    alerts_triggered = graphene.Int()

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        device = Device.objects.get(id=input.device_id, organization=user.organization)

        # Determine if value is an alert (device threshold logic)
        alert_thresholds = {
            'dissolved_oxygen': (4.0, None),   # (min_ok, max_ok)
            'ph': (6.0, 9.0),
            'ammonia': (None, 25.0),
            'co2': (None, 2000.0),
        }
        is_alert = False
        thresholds = alert_thresholds.get(input.metric)
        if thresholds:
            min_ok, max_ok = thresholds
            if min_ok is not None and input.value < min_ok:
                is_alert = True
            if max_ok is not None and input.value > max_ok:
                is_alert = True

        reading = SensorReading.objects.create(
            organization=user.organization,
            device=device,
            enterprise_id=input.get('enterprise_id') or device.enterprise_id,
            metric=input.metric,
            value=input.value,
            unit=input.unit,
            is_alert=is_alert,
        )

        # Update device status and last seen
        device.status = 'warning' if is_alert else 'online'
        device.last_seen_at = timezone.now()
        device.save(update_fields=['status', 'last_seen_at'])

        # Run automation rules
        triggered = run_all_rules(user.organization, input.metric, input.value, user)

        # Create security alert if sensor is in alert state
        if is_alert:
            SecurityAlert.objects.create(
                organization=user.organization,
                source='sensor',
                source_id=device.id,
                severity='critical',
                title=f'Sensor Alert: {input.metric.replace("_", " ").title()} — {device.name}',
                detail=f'Value {input.value} {input.unit} is outside safe range.',
            )

        return IngestSensorReading(reading=reading, alerts_triggered=len(triggered))


class CreateDroneFlight(graphene.Mutation):
    class Arguments:
        input = DroneFlightInput(required=True)

    flight = graphene.Field(DroneFlightType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        flight = DroneFlight.objects.create(
            organization=user.organization,
            piloted_by=user,
            device_id=input.get('device_id'),
            enterprise_id=input.get('enterprise_id'),
            flight_type=input.get('flight_type', 'survey'),
            notes=input.get('notes', ''),
        )
        return CreateDroneFlight(flight=flight)


class UpdateDroneFlight(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        status = graphene.String()
        area_covered_ha = graphene.Float()
        altitude_m = graphene.Float()
        findings = graphene.JSONString()
        notes = graphene.String()

    flight = graphene.Field(DroneFlightType)

    def mutate(self, info, id, status=None, area_covered_ha=None,
               altitude_m=None, findings=None, notes=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        flight = DroneFlight.objects.get(id=id, organization=user.organization)
        if status:
            flight.status = status
            if status == 'in_flight' and not flight.start_time:
                flight.start_time = timezone.now()
            elif status in ('completed', 'aborted') and not flight.end_time:
                flight.end_time = timezone.now()
        if area_covered_ha is not None:
            flight.area_covered_ha = area_covered_ha
        if altitude_m is not None:
            flight.altitude_m = altitude_m
        if findings is not None:
            flight.findings = findings
        if notes is not None:
            flight.notes = notes
        flight.save()
        return UpdateDroneFlight(flight=flight)


class ReviewCameraEvent(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    event = graphene.Field(CameraEventType)

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        event = CameraEvent.objects.get(id=id, organization=user.organization)
        event.is_reviewed = True
        event.reviewed_by = user
        event.save()
        return ReviewCameraEvent(event=event)


class ResolveSecurityAlert(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    alert = graphene.Field(SecurityAlertType)

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        alert = SecurityAlert.objects.get(id=id, organization=user.organization)
        alert.is_resolved = True
        alert.resolved_at = timezone.now()
        alert.resolved_by = user
        alert.save()
        return ResolveSecurityAlert(alert=alert)


class DevicesMutation(graphene.ObjectType):
    pair_device = PairDevice.Field()
    update_device = UpdateDevice.Field()
    unpair_device = UnpairDevice.Field()
    ingest_sensor_reading = IngestSensorReading.Field()
    create_drone_flight = CreateDroneFlight.Field()
    update_drone_flight = UpdateDroneFlight.Field()
    review_camera_event = ReviewCameraEvent.Field()
    resolve_security_alert = ResolveSecurityAlert.Field()
