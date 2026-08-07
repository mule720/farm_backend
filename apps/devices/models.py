import uuid
from django.db import models
from django.conf import settings


class Device(models.Model):
    TYPE_CHOICES = [
        ('sensor', 'Sensor'), ('camera', 'Camera'), ('drone', 'Drone'),
        ('gateway', 'Gateway'), ('controller', 'Controller'),
        ('weighscale', 'Weigh Scale'),
    ]
    STATUS_CHOICES = [
        ('online', 'Online'), ('offline', 'Offline'),
        ('warning', 'Warning'), ('pairing', 'Pairing'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='devices'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='devices'
    )
    name = models.CharField(max_length=255)
    device_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    model = models.CharField(max_length=100, blank=True)
    firmware_version = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
    battery_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    signal_strength = models.PositiveSmallIntegerField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    config = models.JSONField(default=dict)
    paired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='paired_devices'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'devices'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.device_type})'


class SensorReading(models.Model):
    METRIC_CHOICES = [
        ('dissolved_oxygen', 'Dissolved Oxygen'), ('ph', 'pH'),
        ('temperature', 'Temperature'), ('humidity', 'Humidity'),
        ('ammonia', 'Ammonia'), ('co2', 'CO2'), ('weight', 'Weight'),
        ('light', 'Light'), ('pressure', 'Pressure'), ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='sensor_readings'
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name='readings'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sensor_readings'
    )
    metric = models.CharField(max_length=50, choices=METRIC_CHOICES)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=30)
    is_alert = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sensor_readings'
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.device.name} — {self.metric}: {self.value}{self.unit}'


class DroneFlight(models.Model):
    FLIGHT_TYPE_CHOICES = [
        ('survey', 'Survey'), ('spray', 'Spray'),
        ('inspection', 'Inspection'), ('count', 'Livestock Count'),
    ]
    STATUS_CHOICES = [
        ('planned', 'Planned'), ('in_flight', 'In Flight'),
        ('completed', 'Completed'), ('aborted', 'Aborted'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='drone_flights'
    )
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name='flights'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='drone_flights'
    )
    flight_type = models.CharField(max_length=20, choices=FLIGHT_TYPE_CHOICES, default='survey')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    flight_path = models.JSONField(null=True, blank=True)
    area_covered_ha = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    altitude_m = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    findings = models.JSONField(default=dict)
    image_urls = models.JSONField(default=list)
    notes = models.TextField(blank=True)
    piloted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='drone_flights'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'drone_flights'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.flight_type} flight — {self.created_at.date()}'


class CameraEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ('motion', 'Motion'), ('intruder', 'Intruder'),
        ('livestock_count', 'Livestock Count'), ('disease_flag', 'Disease Flag'),
        ('face', 'Face Detected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='camera_events'
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name='camera_events'
    )
    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    snapshot_url = models.URLField(blank=True)
    video_clip_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict)
    is_reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_events'
    )
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'camera_events'
        ordering = ['-detected_at']

    def __str__(self):
        return f'{self.event_type} @ {self.device.name}'


class SecurityAlert(models.Model):
    SEVERITY_CHOICES = [
        ('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical'),
    ]
    SOURCE_CHOICES = [
        ('camera', 'Camera'), ('sensor', 'Sensor'),
        ('automation', 'Automation'), ('manual', 'Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='security_alerts'
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_id = models.UUIDField(null=True, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='resolved_alerts'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'security_alerts'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title}'
