import graphene
from graphene_django import DjangoObjectType
from .models import (
    GreenhouseZone, ClimateTarget, ClimateReading,
    ClimateActuatorEvent, GrowLightSchedule, FertigationSchedule,
    FertigationEvent, HydroponicReading,
)


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class GreenhouseZoneType(DjangoObjectType):
    class Meta:
        model = GreenhouseZone
        fields = '__all__'


class ClimateTargetType(DjangoObjectType):
    class Meta:
        model = ClimateTarget
        fields = '__all__'


class ClimateReadingType(DjangoObjectType):
    class Meta:
        model = ClimateReading
        fields = '__all__'


class ClimateActuatorEventType(DjangoObjectType):
    class Meta:
        model = ClimateActuatorEvent
        fields = '__all__'


class GrowLightScheduleType(DjangoObjectType):
    class Meta:
        model = GrowLightSchedule
        fields = '__all__'


class FertigationScheduleType(DjangoObjectType):
    class Meta:
        model = FertigationSchedule
        fields = '__all__'


class FertigationEventType(DjangoObjectType):
    class Meta:
        model = FertigationEvent
        fields = '__all__'


class HydroponicReadingType(DjangoObjectType):
    class Meta:
        model = HydroponicReading
        fields = '__all__'


class GreenhouseQuery(graphene.ObjectType):
    greenhouse_zones = graphene.List(GreenhouseZoneType)
    greenhouse_zone = graphene.Field(GreenhouseZoneType, id=graphene.UUID(required=True))
    climate_readings = graphene.List(ClimateReadingType, zone_id=graphene.UUID(required=True), limit=graphene.Int())
    latest_climate = graphene.Field(ClimateReadingType, zone_id=graphene.UUID(required=True))
    climate_alerts = graphene.List(ClimateReadingType)
    fertigation_events = graphene.List(FertigationEventType, zone_id=graphene.UUID(required=True), limit=graphene.Int())
    hydroponic_readings = graphene.List(HydroponicReadingType, zone_id=graphene.UUID(required=True), limit=graphene.Int())

    def resolve_greenhouse_zones(self, info):
        return GreenhouseZone.objects.filter(organization=_org(info), is_active=True)

    def resolve_greenhouse_zone(self, info, id):
        return GreenhouseZone.objects.get(pk=id, organization=_org(info))

    def resolve_climate_readings(self, info, zone_id, limit=100):
        return ClimateReading.objects.filter(zone_id=zone_id, organization=_org(info))[:limit]

    def resolve_latest_climate(self, info, zone_id):
        return ClimateReading.objects.filter(zone_id=zone_id, organization=_org(info)).first()

    def resolve_climate_alerts(self, info):
        return ClimateReading.objects.filter(organization=_org(info), is_alert=True).order_by('-recorded_at')[:50]

    def resolve_fertigation_events(self, info, zone_id, limit=50):
        return FertigationEvent.objects.filter(zone_id=zone_id, organization=_org(info))[:limit]

    def resolve_hydroponic_readings(self, info, zone_id, limit=100):
        return HydroponicReading.objects.filter(zone_id=zone_id, organization=_org(info))[:limit]


class CreateGreenhouseZone(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        zone_type = graphene.String()
        area_m2 = graphene.Float()
        crop_type = graphene.String()
        enterprise_id = graphene.UUID()

    zone = graphene.Field(GreenhouseZoneType)

    def mutate(self, info, name, **kwargs):
        zone = GreenhouseZone.objects.create(
            organization=_org(info), name=name,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateGreenhouseZone(zone=zone)


class SetClimateTarget(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        temp_min_c = graphene.Float()
        temp_max_c = graphene.Float()
        humidity_min_pct = graphene.Int()
        humidity_max_pct = graphene.Int()
        co2_min_ppm = graphene.Int()
        co2_max_ppm = graphene.Int()

    target = graphene.Field(ClimateTargetType)

    def mutate(self, info, zone_id, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        target, _ = ClimateTarget.objects.update_or_create(
            zone=zone,
            defaults={k: v for k, v in kwargs.items() if v is not None},
        )
        return SetClimateTarget(target=target)


class LogClimateReading(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        recorded_at = graphene.DateTime(required=True)
        temperature_c = graphene.Float()
        humidity_pct = graphene.Int()
        co2_ppm = graphene.Int()
        light_lux = graphene.Int()
        vpd = graphene.Float()

    reading = graphene.Field(ClimateReadingType)

    def mutate(self, info, zone_id, recorded_at, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        reading = ClimateReading(
            organization=_org(info), zone=zone, recorded_at=recorded_at,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        reading.save()
        return LogClimateReading(reading=reading)


class TriggerActuator(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        actuator_type = graphene.String(required=True)
        action = graphene.String(required=True)
        trigger = graphene.String()
        value_pct = graphene.Int()
        reason = graphene.String()

    event = graphene.Field(ClimateActuatorEventType)

    def mutate(self, info, zone_id, actuator_type, action, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        event = ClimateActuatorEvent.objects.create(
            organization=_org(info), zone=zone,
            actuator_type=actuator_type, action=action,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return TriggerActuator(event=event)


class CreateGrowLightSchedule(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        name = graphene.String(required=True)
        lights_on_time = graphene.Time(required=True)
        lights_off_time = graphene.Time(required=True)
        intensity_pct = graphene.Int()
        crop_stage = graphene.String()
        spectrum = graphene.String()

    schedule = graphene.Field(GrowLightScheduleType)

    def mutate(self, info, zone_id, name, lights_on_time, lights_off_time, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        schedule = GrowLightSchedule.objects.create(
            zone=zone, name=name,
            lights_on_time=lights_on_time, lights_off_time=lights_off_time,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateGrowLightSchedule(schedule=schedule)


class LogFertigationEvent(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        volume_litres = graphene.Float(required=True)
        ec_before = graphene.Float()
        ec_after = graphene.Float()
        ph_before = graphene.Float()
        ph_after = graphene.Float()
        cost = graphene.Float()

    event = graphene.Field(FertigationEventType)

    def mutate(self, info, zone_id, volume_litres, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        event = FertigationEvent.objects.create(
            organization=_org(info), zone=zone, volume_litres=volume_litres,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogFertigationEvent(event=event)


class LogHydroponicReading(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        ec_ms_cm = graphene.Float()
        ph = graphene.Float()
        water_temp_c = graphene.Float()
        dissolved_oxygen_mg_l = graphene.Float()
        tank_level_pct = graphene.Int()

    reading = graphene.Field(HydroponicReadingType)

    def mutate(self, info, zone_id, **kwargs):
        zone = GreenhouseZone.objects.get(pk=zone_id, organization=_org(info))
        reading = HydroponicReading.objects.create(
            organization=_org(info), zone=zone,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogHydroponicReading(reading=reading)


class GreenhouseMutation(graphene.ObjectType):
    create_greenhouse_zone = CreateGreenhouseZone.Field()
    set_climate_target = SetClimateTarget.Field()
    log_climate_reading = LogClimateReading.Field()
    trigger_actuator = TriggerActuator.Field()
    create_grow_light_schedule = CreateGrowLightSchedule.Field()
    log_fertigation_event = LogFertigationEvent.Field()
    log_hydroponic_reading = LogHydroponicReading.Field()
