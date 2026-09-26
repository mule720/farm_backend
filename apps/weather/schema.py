import graphene
from graphene_django import DjangoObjectType
from .models import WeatherStation, WeatherReading, WeatherForecast, FarmField, NDVIRecord
from apps.accounts import rbac
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class WeatherStationType(DjangoObjectType):
    # Coordinates as floats: mutations receive Float args and store them in
    # DecimalFields; graphene's Decimal scalar rejects float instances.
    latitude = graphene.Float()
    longitude = graphene.Float()

    class Meta:
        model = WeatherStation
        fields = '__all__'

    def resolve_latitude(self, info):
        return None if self.latitude is None else float(self.latitude)

    def resolve_longitude(self, info):
        return None if self.longitude is None else float(self.longitude)


class WeatherReadingType(DjangoObjectType):
    class Meta:
        model = WeatherReading
        fields = '__all__'
        convert_choices_to_enum = False


class WeatherForecastType(DjangoObjectType):
    class Meta:
        model = WeatherForecast
        fields = '__all__'
        convert_choices_to_enum = False


class FarmFieldType(DjangoObjectType):
    latitude = graphene.Float()
    longitude = graphene.Float()
    latest_ndvi = graphene.Float()

    class Meta:
        model = FarmField
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_latitude(self, info):
        return None if self.latitude is None else float(self.latitude)

    def resolve_longitude(self, info):
        return None if self.longitude is None else float(self.longitude)

    def resolve_latest_ndvi(self, info):
        return None if self.latest_ndvi is None else float(self.latest_ndvi)


class NDVIRecordType(DjangoObjectType):
    class Meta:
        model = NDVIRecord
        fields = '__all__'
        convert_choices_to_enum = False


class WeatherQuery(graphene.ObjectType):
    weather_stations = graphene.List(WeatherStationType)
    weather_station = graphene.Field(WeatherStationType, id=graphene.UUID(required=True))
    weather_readings = graphene.List(WeatherReadingType, station_id=graphene.UUID(required=True), limit=graphene.Int())
    latest_reading = graphene.Field(WeatherReadingType, station_id=graphene.UUID(required=True))
    weather_forecast = graphene.List(WeatherForecastType, station_id=graphene.UUID(required=True))
    farm_fields = graphene.List(FarmFieldType)
    farm_field = graphene.Field(FarmFieldType, id=graphene.UUID(required=True))
    ndvi_records = graphene.List(NDVIRecordType, field_id=graphene.UUID(required=True))
    weather_alerts = graphene.List(WeatherReadingType)
    weather_overview = graphene.Field('apps.weather.schema.WeatherOverviewType')

    def resolve_weather_overview(self, info):
        return build_overview(_org(info))

    def resolve_weather_stations(self, info):
        return WeatherStation.objects.filter(organization=_org(info), is_active=True)

    def resolve_weather_station(self, info, id):
        return WeatherStation.objects.get(pk=id, organization=_org(info))

    def resolve_weather_readings(self, info, station_id, limit=100):
        return WeatherReading.objects.filter(station_id=station_id, organization=_org(info))[:limit]

    def resolve_latest_reading(self, info, station_id):
        return WeatherReading.objects.filter(station_id=station_id, organization=_org(info)).first()

    def resolve_weather_forecast(self, info, station_id):
        return WeatherForecast.objects.filter(station_id=station_id, organization=_org(info))

    def resolve_farm_fields(self, info):
        return FarmField.objects.filter(organization=_org(info))

    def resolve_farm_field(self, info, id):
        return FarmField.objects.get(pk=id, organization=_org(info))

    def resolve_ndvi_records(self, info, field_id):
        return NDVIRecord.objects.filter(field_id=field_id, organization=_org(info))

    def resolve_weather_alerts(self, info):
        return WeatherReading.objects.filter(organization=_org(info), is_alert=True).order_by('-recorded_at')[:20]


class CreateWeatherStation(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        latitude = graphene.Float()
        longitude = graphene.Float()
        provider = graphene.String()
        station_id = graphene.String()

    station = graphene.Field(WeatherStationType)

    def mutate(self, info, name, **kwargs):
        station = WeatherStation.objects.create(
            organization=_org(info), name=name,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateWeatherStation(station=station)


class LogWeatherReading(graphene.Mutation):
    class Arguments:
        station_id = graphene.UUID(required=True)
        recorded_at = graphene.DateTime(required=True)
        temperature_c = graphene.Float()
        humidity_pct = graphene.Int()
        wind_speed_kmh = graphene.Float()
        wind_direction_deg = graphene.Int()
        rainfall_mm = graphene.Float()
        pressure_hpa = graphene.Float()
        uv_index = graphene.Float()
        is_alert = graphene.Boolean()
        alert_type = graphene.String()

    reading = graphene.Field(WeatherReadingType)

    def mutate(self, info, station_id, recorded_at, **kwargs):
        station = WeatherStation.objects.get(pk=station_id, organization=_org(info))
        reading = WeatherReading.objects.create(
            organization=_org(info), station=station, recorded_at=recorded_at,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogWeatherReading(reading=reading)


class UpsertForecast(graphene.Mutation):
    class Arguments:
        station_id = graphene.UUID(required=True)
        forecast_date = graphene.Date(required=True)
        condition = graphene.String()
        temp_min_c = graphene.Float()
        temp_max_c = graphene.Float()
        rain_probability_pct = graphene.Int()
        expected_rainfall_mm = graphene.Float()
        farming_advisory = graphene.String()

    forecast = graphene.Field(WeatherForecastType)

    def mutate(self, info, station_id, forecast_date, **kwargs):
        station = WeatherStation.objects.get(pk=station_id, organization=_org(info))
        forecast, _ = WeatherForecast.objects.update_or_create(
            station=station, forecast_date=forecast_date,
            organization=_org(info),
            defaults={k: v for k, v in kwargs.items() if v is not None},
        )
        return UpsertForecast(forecast=forecast)


class CreateFarmField(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        area_ha = graphene.Float()
        crop_type = graphene.String()
        crop_stage = graphene.String()
        planting_date = graphene.Date()
        expected_harvest_date = graphene.Date()
        soil_type = graphene.String()
        nearest_station_id = graphene.UUID()
        enterprise_id = graphene.UUID()
        notes = graphene.String()
        latitude = graphene.Float()
        longitude = graphene.Float()
        gps_boundary = graphene.JSONString()

    field = graphene.Field(FarmFieldType)

    def mutate(self, info, name, **kwargs):
        field = FarmField.objects.create(
            organization=_org(info), name=name,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateFarmField(field=field)


class LogNDVI(graphene.Mutation):
    class Arguments:
        field_id = graphene.UUID(required=True)
        ndvi_value = graphene.Float(required=True)
        recorded_at = graphene.Date(required=True)
        source = graphene.String()
        image_url = graphene.String()
        health_assessment = graphene.String()
        recommendations = graphene.List(graphene.String)

    record = graphene.Field(NDVIRecordType)

    def mutate(self, info, field_id, ndvi_value, recorded_at, **kwargs):
        field = FarmField.objects.get(pk=field_id, organization=_org(info))
        record = NDVIRecord(
            organization=_org(info), field=field,
            ndvi_value=ndvi_value, recorded_at=recorded_at,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        record.save()
        return LogNDVI(record=record)


class WeatherMutation(graphene.ObjectType):
    create_weather_station = CreateWeatherStation.Field()
    log_weather_reading = LogWeatherReading.Field()
    upsert_forecast = UpsertForecast.Field()
    create_farm_field = CreateFarmField.Field()
    log_ndvi = LogNDVI.Field()


# ─── Live-data overview + sync ────────────────────────────────────────────────

class StationOverviewType(graphene.ObjectType):
    id = graphene.UUID()
    name = graphene.String()
    latitude = graphene.Float()
    longitude = graphene.Float()
    provider = graphene.String()
    last_synced_at = graphene.DateTime()
    current = graphene.Field(WeatherReadingType)
    forecast = graphene.List(WeatherForecastType)


class FieldOverviewType(graphene.ObjectType):
    id = graphene.UUID()
    name = graphene.String()
    crop_type = graphene.String()
    crop_stage = graphene.String()
    area_ha = graphene.Float()
    latitude = graphene.Float()
    longitude = graphene.Float()
    latest_ndvi = graphene.Float()
    latest_ndvi_date = graphene.Date()
    health = graphene.String()
    recommendations = graphene.List(graphene.String)
    ndvi_history = graphene.List(NDVIRecordType)


class WeatherAlertType(graphene.ObjectType):
    station_name = graphene.String()
    alert_type = graphene.String()
    recorded_at = graphene.DateTime()
    temperature_c = graphene.Float()
    wind_speed_kmh = graphene.Float()


class WeatherOverviewType(graphene.ObjectType):
    stations = graphene.List(StationOverviewType)
    fields = graphene.List(FieldOverviewType)
    rain_days_7 = graphene.Int()
    expected_rainfall_mm_7 = graphene.Float()
    avg_max_temp_c_7 = graphene.Float()
    alerts = graphene.List(WeatherAlertType)


def build_overview(org):
    from datetime import date, timedelta
    from django.utils import timezone
    from .services import ndvi_assessment, field_coords
    today = date.today()
    stations = []
    for st in WeatherStation.objects.filter(organization=org, is_active=True):
        fc = list(WeatherForecast.objects.filter(station=st, forecast_date__gte=today).order_by('forecast_date')[:7])
        cur = WeatherReading.objects.filter(station=st).order_by('-recorded_at').first()
        stations.append(StationOverviewType(
            id=st.id, name=st.name, latitude=st.latitude, longitude=st.longitude, provider=st.provider,
            last_synced_at=cur.recorded_at if cur else None, current=cur, forecast=fc))
    # 7-day aggregates use the first station with a forecast (the farm's primary station)
    primary = next((s.forecast for s in stations if s.forecast), [])
    fields = []
    for f in FarmField.objects.filter(organization=org).select_related('nearest_station'):
        hist = list(NDVIRecord.objects.filter(field=f).order_by('-recorded_at')[:12])
        health, recs = (ndvi_assessment(float(f.latest_ndvi), f.crop_stage) if f.latest_ndvi is not None else (None, []))
        coords = field_coords(f)
        fields.append(FieldOverviewType(
            id=f.id, name=f.name, crop_type=f.crop_type, crop_stage=f.crop_stage, area_ha=f.area_ha,
            latitude=coords[0] if coords else None, longitude=coords[1] if coords else None,
            latest_ndvi=f.latest_ndvi, latest_ndvi_date=f.latest_ndvi_date, health=health,
            recommendations=recs, ndvi_history=list(reversed(hist))))
    since = timezone.now() - timedelta(days=2)
    alerts = [WeatherAlertType(station_name=r.station.name, alert_type=r.alert_type, recorded_at=r.recorded_at,
                               temperature_c=r.temperature_c, wind_speed_kmh=r.wind_speed_kmh)
              for r in WeatherReading.objects.filter(organization=org, is_alert=True, recorded_at__gte=since)
              .select_related('station').order_by('-recorded_at')[:10]]
    return WeatherOverviewType(
        stations=stations, fields=fields,
        rain_days_7=sum(1 for d in primary if d.rain_probability_pct > 50),
        expected_rainfall_mm_7=float(sum(d.expected_rainfall_mm for d in primary)),
        avg_max_temp_c_7=(float(sum(d.temp_max_c or 0 for d in primary)) / len(primary)) if primary else None,
        alerts=alerts,
    )


class SyncStationForecast(graphene.Mutation):
    """Pull a live 7-day forecast + current conditions (Open-Meteo) for one station."""
    class Arguments:
        station_id = graphene.UUID(required=True)

    forecast_days = graphene.Int()
    station = graphene.Field(StationOverviewType)

    def mutate(self, info, station_id):
        from . import services
        org = _org(info)
        try:
            st = WeatherStation.objects.get(pk=station_id, organization=org)
        except WeatherStation.DoesNotExist:
            raise Exception('Station not found')
        if st.latitude is None or st.longitude is None:
            raise Exception('Station has no coordinates; set latitude and longitude first')
        try:
            n = services.sync_station_forecast(st, fetch=services.fetch_open_meteo)
        except Exception as e:
            raise Exception(f'Weather provider unavailable: {e}')
        ov = build_overview(org)
        return SyncStationForecast(forecast_days=n, station=next((s for s in ov.stations if s.id == st.id), None))


class SyncFieldNdvi(graphene.Mutation):
    """Pull satellite NDVI (NASA MODIS, 250 m, 16-day composites) for one field."""
    class Arguments:
        field_id = graphene.UUID(required=True)

    new_records = graphene.Int()
    field = graphene.Field(FarmFieldType)

    def mutate(self, info, field_id):
        from . import services
        org = _org(info)
        try:
            f = FarmField.objects.select_related('nearest_station').get(pk=field_id, organization=org)
        except FarmField.DoesNotExist:
            raise Exception('Field not found')
        if not services.field_coords(f):
            raise Exception('Field has no location; set coordinates, a boundary, or a nearest station')
        try:
            n = services.sync_field_ndvi(f, fetch=services.fetch_modis_ndvi)
        except Exception as e:
            raise Exception(f'Satellite provider unavailable: {e}')
        f.refresh_from_db()
        return SyncFieldNdvi(new_records=n, field=f)


class SyncWeatherNow(graphene.Mutation):
    """Sync every station and field of the caller's organisation."""
    stations = graphene.Int()
    forecast_days = graphene.Int()
    fields = graphene.Int()
    ndvi_records = graphene.Int()
    errors = graphene.List(graphene.String)

    def mutate(self, info):
        from . import services
        rbac.require_module(info.context.user, 'weather', 'edit')
        s = services.sync_organization(_org(info), fetch_weather=services.fetch_open_meteo,
                                       fetch_ndvi=services.fetch_modis_ndvi)
        return SyncWeatherNow(stations=s['stations'], forecast_days=s['forecast_days'], fields=s['fields'],
                              ndvi_records=s['ndvi_records'], errors=s['errors'])


class UpdateWeatherStation(graphene.Mutation):
    class Arguments:
        station_id = graphene.UUID(required=True)
        name = graphene.String()
        latitude = graphene.Float()
        longitude = graphene.Float()
        is_active = graphene.Boolean()

    station = graphene.Field(WeatherStationType)

    def mutate(self, info, station_id, **kwargs):
        st = WeatherStation.objects.get(pk=station_id, organization=_org(info))
        for k, v in kwargs.items():
            if v is not None:
                setattr(st, k, v)
        st.save()
        return UpdateWeatherStation(station=st)


class DeleteWeatherStation(graphene.Mutation):
    class Arguments:
        station_id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, station_id):
        n, _ = WeatherStation.objects.filter(pk=station_id, organization=_org(info)).delete()
        return DeleteWeatherStation(ok=bool(n))


class UpdateFarmField(graphene.Mutation):
    class Arguments:
        field_id = graphene.UUID(required=True)
        name = graphene.String()
        crop_type = graphene.String()
        crop_stage = graphene.String()
        area_ha = graphene.Float()
        latitude = graphene.Float()
        longitude = graphene.Float()
        nearest_station_id = graphene.UUID()

    field = graphene.Field(FarmFieldType)

    def mutate(self, info, field_id, **kwargs):
        f = FarmField.objects.get(pk=field_id, organization=_org(info))
        for k, v in kwargs.items():
            if v is not None:
                setattr(f, k, v)
        f.save()
        return UpdateFarmField(field=f)


class DeleteFarmField(graphene.Mutation):
    class Arguments:
        field_id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, field_id):
        n, _ = FarmField.objects.filter(pk=field_id, organization=_org(info)).delete()
        return DeleteFarmField(ok=bool(n))


class WeatherMutation(WeatherMutation):  # noqa: F811 — extend the base mutation set (graphene collects fields at class creation)
    sync_station_forecast = SyncStationForecast.Field()
    sync_field_ndvi = SyncFieldNdvi.Field()
    sync_weather_now = SyncWeatherNow.Field()
    update_weather_station = UpdateWeatherStation.Field()
    delete_weather_station = DeleteWeatherStation.Field()
    update_farm_field = UpdateFarmField.Field()
    delete_farm_field = DeleteFarmField.Field()
