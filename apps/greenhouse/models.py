import uuid
from django.db import models
from django.conf import settings


class GreenhouseZone(models.Model):
    ZONE_TYPE_CHOICES = [
        ('greenhouse', 'Greenhouse'), ('polytunnel', 'Poly Tunnel'),
        ('shade_house', 'Shade House'), ('hydroponic', 'Hydroponic Unit'),
        ('mushroom', 'Mushroom House'), ('nursery', 'Nursery'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='greenhouse_zones')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='greenhouse_zones')
    name = models.CharField(max_length=255)
    zone_type = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='greenhouse')
    area_m2 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    crop_type = models.CharField(max_length=100, blank=True)
    crop_stage = models.CharField(max_length=100, blank=True)
    planting_date = models.DateField(null=True, blank=True)
    expected_harvest_date = models.DateField(null=True, blank=True)
    device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='greenhouse_zones')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'greenhouse_zones'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.zone_type})'


class ClimateTarget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone = models.OneToOneField(GreenhouseZone, on_delete=models.CASCADE, related_name='climate_target')
    temp_min_c = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    temp_max_c = models.DecimalField(max_digits=5, decimal_places=2, default=28)
    humidity_min_pct = models.PositiveSmallIntegerField(default=60)
    humidity_max_pct = models.PositiveSmallIntegerField(default=85)
    co2_min_ppm = models.PositiveIntegerField(default=400)
    co2_max_ppm = models.PositiveIntegerField(default=1200)
    light_min_lux = models.PositiveIntegerField(default=5000)
    light_max_lux = models.PositiveIntegerField(default=50000)
    vpd_min = models.DecimalField(max_digits=4, decimal_places=2, default=0.8)
    vpd_max = models.DecimalField(max_digits=4, decimal_places=2, default=1.6)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'climate_targets'


class ClimateReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='climate_readings')
    temperature_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    humidity_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    co2_ppm = models.PositiveIntegerField(null=True, blank=True)
    light_lux = models.PositiveIntegerField(null=True, blank=True)
    vpd = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True, help_text='Vapour Pressure Deficit kPa')
    is_alert = models.BooleanField(default=False)
    alert_details = models.JSONField(default=list, help_text='List of out-of-range parameters')
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = 'climate_readings'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        alerts = []
        try:
            target = self.zone.climate_target
            if self.temperature_c is not None:
                if float(self.temperature_c) < float(target.temp_min_c):
                    alerts.append('temperature_low')
                elif float(self.temperature_c) > float(target.temp_max_c):
                    alerts.append('temperature_high')
            if self.humidity_pct is not None:
                if self.humidity_pct < target.humidity_min_pct:
                    alerts.append('humidity_low')
                elif self.humidity_pct > target.humidity_max_pct:
                    alerts.append('humidity_high')
            if self.co2_ppm is not None:
                if self.co2_ppm < target.co2_min_ppm:
                    alerts.append('co2_low')
                elif self.co2_ppm > target.co2_max_ppm:
                    alerts.append('co2_high')
        except ClimateTarget.DoesNotExist:
            pass
        self.alert_details = alerts
        self.is_alert = bool(alerts)
        super().save(*args, **kwargs)


class ClimateActuatorEvent(models.Model):
    ACTUATOR_CHOICES = [
        ('fan', 'Extraction Fan'), ('vent', 'Roof Vent'),
        ('heater', 'Heater'), ('shade_net', 'Shade Net'),
        ('mister', 'Misting System'), ('co2_injector', 'CO₂ Injector'),
        ('grow_light', 'Grow Lights'), ('pump', 'Water/Nutrient Pump'),
    ]
    ACTION_CHOICES = [
        ('on', 'Turned On'), ('off', 'Turned Off'), ('set_pct', 'Set to %'),
    ]
    TRIGGER_CHOICES = [
        ('sensor', 'Sensor Triggered'), ('schedule', 'Scheduled'),
        ('manual', 'Manual Override'), ('forecast', 'Weather Forecast'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='actuator_events')
    actuator_type = models.CharField(max_length=20, choices=ACTUATOR_CHOICES)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='sensor')
    value_pct = models.PositiveSmallIntegerField(null=True, blank=True, help_text='For set_pct action — 0-100')
    duration_seconds = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=255, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'climate_actuator_events'
        ordering = ['-recorded_at']


class GrowLightSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='grow_light_schedules')
    name = models.CharField(max_length=255)
    crop_stage = models.CharField(max_length=100, blank=True)
    lights_on_time = models.TimeField()
    lights_off_time = models.TimeField()
    photoperiod_hours = models.DecimalField(max_digits=4, decimal_places=1, default=16)
    intensity_pct = models.PositiveSmallIntegerField(default=100)
    spectrum = models.CharField(max_length=100, blank=True, help_text='e.g. Full spectrum, Red/Blue only')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'grow_light_schedules'
        ordering = ['lights_on_time']


class FertigationSchedule(models.Model):
    TRIGGER_CHOICES = [
        ('scheduled', 'Time Schedule'), ('ec_sensor', 'EC Drop Trigger'),
        ('ph_sensor', 'pH Trigger'), ('manual', 'Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='fertigation_schedules')
    name = models.CharField(max_length=255)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='scheduled')
    ec_target_ms_cm = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)
    ph_target = models.DecimalField(max_digits=4, decimal_places=2, default=6.0)
    ph_tolerance = models.DecimalField(max_digits=3, decimal_places=2, default=0.3)
    volume_litres = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    duration_minutes = models.PositiveIntegerField(default=15)
    nutrients = models.JSONField(default=dict, help_text='e.g. {"N": 150, "P": 50, "K": 200} ppm')
    frequency = models.CharField(max_length=50, blank=True, help_text='e.g. Every 4 hours, 3x per day')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fertigation_schedules'


class FertigationEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='fertigation_events')
    schedule = models.ForeignKey(FertigationSchedule, on_delete=models.SET_NULL, null=True, blank=True)
    ec_before = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ec_after = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ph_before = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ph_after = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    water_temp_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    volume_litres = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    nutrients_used = models.JSONField(default=dict)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    triggered_at = models.DateTimeField(auto_now_add=True)
    is_alert = models.BooleanField(default=False)
    alert_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'fertigation_events'
        ordering = ['-triggered_at']


class HydroponicReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    zone = models.ForeignKey(GreenhouseZone, on_delete=models.CASCADE, related_name='hydroponic_readings')
    ec_ms_cm = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    water_temp_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    dissolved_oxygen_mg_l = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tank_level_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    is_alert = models.BooleanField(default=False)
    alert_details = models.JSONField(default=list)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hydroponic_readings'
        ordering = ['-recorded_at']
