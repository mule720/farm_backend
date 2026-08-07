import graphene
from graphene_django import DjangoObjectType
from .models import WeatherStation, WeatherReading, WeatherForecast, FarmField, NDVIRecord
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class WeatherStationType(DjangoObjectType):
    class Meta:
        model = WeatherStation
        fields = '__all__'


class WeatherReadingType(DjangoObjectType):
    class Meta:
        model = WeatherReading
        fields = '__all__'


class WeatherForecastType(DjangoObjectType):
    class Meta:
        model = WeatherForecast
        fields = '__all__'


class FarmFieldType(DjangoObjectType):
    class Meta:
        model = FarmField
        fields = '__all__'


class NDVIRecordType(DjangoObjectType):
    class Meta:
        model = NDVIRecord
        fields = '__all__'


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
