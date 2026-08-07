import graphene
from graphene_django import DjangoObjectType
from .models import IrrigationZone, IrrigationSchedule, IrrigationEvent, SoilMoistureReading
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class IrrigationZoneType(DjangoObjectType):
    class Meta:
        model = IrrigationZone
        fields = '__all__'

    hours_until_next_service = graphene.Float()
    service_due_soon = graphene.Boolean()


class IrrigationScheduleType(DjangoObjectType):
    class Meta:
        model = IrrigationSchedule
        fields = '__all__'


class IrrigationEventType(DjangoObjectType):
    class Meta:
        model = IrrigationEvent
        fields = '__all__'


class SoilMoistureReadingType(DjangoObjectType):
    class Meta:
        model = SoilMoistureReading
        fields = '__all__'


class IrrigationQuery(graphene.ObjectType):
    irrigation_zones = graphene.List(IrrigationZoneType)
    irrigation_zone = graphene.Field(IrrigationZoneType, id=graphene.UUID(required=True))
    irrigation_events = graphene.List(IrrigationEventType, zone_id=graphene.UUID(), limit=graphene.Int())
    soil_moisture_readings = graphene.List(SoilMoistureReadingType, zone_id=graphene.UUID(required=True), limit=graphene.Int())
    low_moisture_zones = graphene.List(IrrigationZoneType)

    def resolve_irrigation_zones(self, info):
        return IrrigationZone.objects.filter(organization=_org(info), is_active=True)

    def resolve_irrigation_zone(self, info, id):
        return IrrigationZone.objects.get(pk=id, organization=_org(info))

    def resolve_irrigation_events(self, info, zone_id=None, limit=50):
        qs = IrrigationEvent.objects.filter(organization=_org(info))
        if zone_id:
            qs = qs.filter(zone_id=zone_id)
        return qs[:limit]

    def resolve_soil_moisture_readings(self, info, zone_id, limit=100):
        return SoilMoistureReading.objects.filter(zone_id=zone_id, organization=_org(info))[:limit]

    def resolve_low_moisture_zones(self, info):
        from django.db.models import F
        return IrrigationZone.objects.filter(
            organization=_org(info),
            is_active=True,
            current_moisture_pct__lt=F('moisture_min_pct'),
        )


class CreateIrrigationZone(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        zone_type = graphene.String()
        water_source = graphene.String()
        area_ha = graphene.Float()
        flow_rate_lph = graphene.Float()
        moisture_min_pct = graphene.Int()
        moisture_max_pct = graphene.Int()
        crop_type = graphene.String()
        location_coords = graphene.String()
        enterprise_id = graphene.UUID()

    zone = graphene.Field(IrrigationZoneType)

    def mutate(self, info, name, **kwargs):
        org = _org(info)
        enterprise_id = kwargs.pop('enterprise_id', None)
        zone = IrrigationZone.objects.create(
            organization=org, name=name,
            enterprise_id=enterprise_id,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateIrrigationZone(zone=zone)


class UpdateIrrigationZone(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        name = graphene.String()
        is_active = graphene.Boolean()
        is_watering = graphene.Boolean()
        moisture_min_pct = graphene.Int()
        moisture_max_pct = graphene.Int()
        crop_type = graphene.String()
        notes = graphene.String()

    zone = graphene.Field(IrrigationZoneType)

    def mutate(self, info, id, **kwargs):
        zone = IrrigationZone.objects.get(pk=id, organization=_org(info))
        for k, v in kwargs.items():
            if v is not None:
                setattr(zone, k, v)
        zone.save()
        return UpdateIrrigationZone(zone=zone)


class CreateIrrigationSchedule(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        name = graphene.String(required=True)
        frequency = graphene.String()
        start_time = graphene.String(required=True)
        duration_minutes = graphene.Int()
        days_of_week = graphene.List(graphene.String)
        sensor_trigger = graphene.Boolean()

    schedule = graphene.Field(IrrigationScheduleType)

    def mutate(self, info, zone_id, name, start_time, **kwargs):
        zone = IrrigationZone.objects.get(pk=zone_id, organization=_org(info))
        schedule = IrrigationSchedule.objects.create(
            zone=zone, name=name, start_time=start_time,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateIrrigationSchedule(schedule=schedule)


class LogIrrigationEvent(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        trigger = graphene.String()
        started_at = graphene.DateTime(required=True)
        ended_at = graphene.DateTime()
        duration_minutes = graphene.Int()
        volume_litres = graphene.Float()
        moisture_before = graphene.Int()
        moisture_after = graphene.Int()
        notes = graphene.String()

    event = graphene.Field(IrrigationEventType)

    def mutate(self, info, zone_id, started_at, **kwargs):
        zone = IrrigationZone.objects.get(pk=zone_id, organization=_org(info))
        event = IrrigationEvent.objects.create(
            organization=_org(info), zone=zone, started_at=started_at,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogIrrigationEvent(event=event)


class LogSoilMoisture(graphene.Mutation):
    class Arguments:
        zone_id = graphene.UUID(required=True)
        moisture_pct = graphene.Int(required=True)
        temperature_c = graphene.Float()

    reading = graphene.Field(SoilMoistureReadingType)

    def mutate(self, info, zone_id, moisture_pct, **kwargs):
        zone = IrrigationZone.objects.get(pk=zone_id, organization=_org(info))
        reading = SoilMoistureReading(
            organization=_org(info), zone=zone, moisture_pct=moisture_pct,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        reading.save()
        return LogSoilMoisture(reading=reading)


class IrrigationMutation(graphene.ObjectType):
    create_irrigation_zone = CreateIrrigationZone.Field()
    update_irrigation_zone = UpdateIrrigationZone.Field()
    create_irrigation_schedule = CreateIrrigationSchedule.Field()
    log_irrigation_event = LogIrrigationEvent.Field()
    log_soil_moisture = LogSoilMoisture.Field()
