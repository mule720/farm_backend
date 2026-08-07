import uuid
from django.db import models
from django.conf import settings


class WeatherStation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='weather_stations')
    name = models.CharField(max_length=255)
    station_id = models.CharField(max_length=100, blank=True, help_text='External provider ID')
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    altitude_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    device = models.OneToOneField('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='weather_station')
    is_active = models.BooleanField(default=True)
    provider = models.CharField(max_length=100, blank=True, help_text='e.g. OpenWeather, Davis, in-house')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'weather_stations'
        ordering = ['name']

    def __str__(self):
        return self.name


class WeatherReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    station = models.ForeignKey(WeatherStation, on_delete=models.CASCADE, related_name='readings')
    temperature_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    humidity_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    wind_speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    wind_direction_deg = models.PositiveSmallIntegerField(null=True, blank=True)
    rainfall_mm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    pressure_hpa = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    uv_index = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    solar_radiation_wm2 = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dew_point_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_alert = models.BooleanField(default=False)
    alert_type = models.CharField(max_length=100, blank=True)
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = 'weather_readings'
        ordering = ['-recorded_at']


class WeatherForecast(models.Model):
    CONDITION_CHOICES = [
        ('sunny', 'Sunny'), ('partly_cloudy', 'Partly Cloudy'), ('cloudy', 'Cloudy'),
        ('light_rain', 'Light Rain'), ('heavy_rain', 'Heavy Rain'), ('thunderstorm', 'Thunderstorm'),
        ('frost', 'Frost Risk'), ('heat_wave', 'Heat Wave'), ('drought', 'Drought Warning'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    station = models.ForeignKey(WeatherStation, on_delete=models.CASCADE, related_name='forecasts')
    forecast_date = models.DateField()
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='sunny')
    temp_min_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    temp_max_c = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    rain_probability_pct = models.PositiveSmallIntegerField(default=0)
    expected_rainfall_mm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    wind_speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    farming_advisory = models.TextField(blank=True, help_text='AI-generated farming tip for this forecast')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'weather_forecasts'
        ordering = ['forecast_date']
        unique_together = [('station', 'forecast_date')]


class FarmField(models.Model):
    CROP_STAGE_CHOICES = [
        ('fallow', 'Fallow'), ('land_prep', 'Land Preparation'), ('planting', 'Planted'),
        ('vegetative', 'Vegetative Growth'), ('flowering', 'Flowering / Pollination'),
        ('fruiting', 'Fruiting'), ('harvest_ready', 'Ready to Harvest'), ('harvested', 'Harvested'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='farm_fields')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='farm_fields')
    name = models.CharField(max_length=255)
    area_ha = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    crop_type = models.CharField(max_length=100, blank=True)
    crop_stage = models.CharField(max_length=20, choices=CROP_STAGE_CHOICES, default='fallow')
    planting_date = models.DateField(null=True, blank=True)
    expected_harvest_date = models.DateField(null=True, blank=True)
    soil_type = models.CharField(max_length=100, blank=True)
    gps_boundary = models.JSONField(default=list, help_text='Polygon as list of [lat,lng] points')
    nearest_station = models.ForeignKey(WeatherStation, on_delete=models.SET_NULL, null=True, blank=True, related_name='fields')
    # Latest NDVI
    latest_ndvi = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    latest_ndvi_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'farm_fields'
        ordering = ['name']


class NDVIRecord(models.Model):
    SOURCE_CHOICES = [
        ('drone', 'Drone'), ('satellite', 'Satellite'), ('manual', 'Manual Estimate'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    field = models.ForeignKey(FarmField, on_delete=models.CASCADE, related_name='ndvi_records')
    ndvi_value = models.DecimalField(max_digits=5, decimal_places=4, help_text='-1.0 to 1.0')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='satellite')
    image_url = models.CharField(max_length=500, blank=True)
    health_assessment = models.CharField(max_length=255, blank=True)
    # Zones: list of {zone_name, ndvi, health_status}
    zones = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    recorded_at = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ndvi_records'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        FarmField.objects.filter(pk=self.field_id).update(
            latest_ndvi=self.ndvi_value, latest_ndvi_date=self.recorded_at
        )
