import uuid
from django.db import models
from django.conf import settings


class IrrigationZone(models.Model):
    WATER_SOURCE_CHOICES = [
        ('borehole', 'Borehole'), ('river', 'River'), ('dam', 'Dam'),
        ('municipal', 'Municipal'), ('rainwater', 'Rainwater Harvesting'), ('other', 'Other'),
    ]
    ZONE_TYPE_CHOICES = [
        ('drip', 'Drip Irrigation'), ('sprinkler', 'Sprinkler'),
        ('flood', 'Flood / Furrow'), ('centre_pivot', 'Centre Pivot'), ('manual', 'Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='irrigation_zones')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='irrigation_zones')
    name = models.CharField(max_length=255)
    zone_type = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='drip')
    water_source = models.CharField(max_length=20, choices=WATER_SOURCE_CHOICES, default='borehole')
    area_ha = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    flow_rate_lph = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Litres per hour')
    is_active = models.BooleanField(default=True)
    is_watering = models.BooleanField(default=False)
    # Soil moisture thresholds: start watering below min, stop above max
    moisture_min_pct = models.PositiveSmallIntegerField(default=30)
    moisture_max_pct = models.PositiveSmallIntegerField(default=70)
    current_moisture_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    crop_type = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    location_coords = models.CharField(max_length=100, blank=True, help_text='lat,lng')
    device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='irrigation_zones')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'irrigation_zones'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.zone_type})'


class IrrigationSchedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Every Day'), ('every_other', 'Every Other Day'),
        ('weekly', 'Weekly'), ('custom', 'Custom Days'), ('sensor', 'Sensor Triggered'),
    ]
    DAY_CHOICES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone = models.ForeignKey(IrrigationZone, on_delete=models.CASCADE, related_name='schedules')
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='daily')
    days_of_week = models.JSONField(default=list, help_text='e.g. ["Mon","Wed","Fri"]')
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    # For sensor-triggered: activate when moisture < threshold
    sensor_trigger = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'irrigation_schedules'
        ordering = ['start_time']

    def __str__(self):
        return f'{self.zone.name} — {self.name}'


class IrrigationEvent(models.Model):
    TRIGGER_CHOICES = [
        ('scheduled', 'Scheduled'), ('manual', 'Manual Override'),
        ('sensor', 'Sensor Triggered'), ('emergency', 'Emergency Stop'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='irrigation_events')
    zone = models.ForeignKey(IrrigationZone, on_delete=models.CASCADE, related_name='events')
    schedule = models.ForeignKey(IrrigationSchedule, on_delete=models.SET_NULL, null=True, blank=True)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='scheduled')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    volume_litres = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    moisture_before = models.PositiveSmallIntegerField(null=True, blank=True)
    moisture_after = models.PositiveSmallIntegerField(null=True, blank=True)
    cost_estimate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'irrigation_events'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.zone.name} — {self.started_at.date()}'


class SoilMoistureReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    zone = models.ForeignKey(IrrigationZone, on_delete=models.CASCADE, related_name='moisture_readings')
    moisture_pct = models.PositiveSmallIntegerField()
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_alert = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'soil_moisture_readings'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        self.is_alert = self.moisture_pct < self.zone.moisture_min_pct
        super().save(*args, **kwargs)
        # Update zone current moisture
        IrrigationZone.objects.filter(pk=self.zone_id).update(current_moisture_pct=self.moisture_pct)


class BoreholeMonitor(models.Model):
    PUMP_STATUS_CHOICES = [
        ('running', 'Running'), ('idle', 'Idle'), ('fault', 'Fault'), ('off', 'Off'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='borehole_monitors')
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='borehole_monitors')
    borehole_depth_m = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    tank_capacity_litres = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_level_pct = models.PositiveSmallIntegerField(default=100)
    low_level_threshold_pct = models.PositiveSmallIntegerField(default=20)
    pump_status = models.CharField(max_length=20, choices=PUMP_STATUS_CHOICES, default='idle')
    pump_runtime_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    daily_output_litres = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    last_reading_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'borehole_monitors'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_low(self):
        return self.current_level_pct <= self.low_level_threshold_pct


class TankLevelReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    borehole = models.ForeignKey(BoreholeMonitor, on_delete=models.CASCADE, related_name='level_readings')
    level_pct = models.PositiveSmallIntegerField()
    volume_litres = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pump_running = models.BooleanField(default=False)
    is_alert = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tank_level_readings'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        self.is_alert = self.level_pct <= self.borehole.low_level_threshold_pct
        super().save(*args, **kwargs)
        BoreholeMonitor.objects.filter(pk=self.borehole_id).update(
            current_level_pct=self.level_pct,
            last_reading_at=self.recorded_at,
        )
