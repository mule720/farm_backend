import graphene
from graphene_django import DjangoObjectType
from .models import AnimalRecord, AnimalWeightEvent, AnimalHealthEvent, HeatEvent, FeedingRecord
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class AnimalRecordType(DjangoObjectType):
    class Meta:
        model = AnimalRecord
        fields = '__all__'


class AnimalWeightEventType(DjangoObjectType):
    class Meta:
        model = AnimalWeightEvent
        fields = '__all__'


class AnimalHealthEventType(DjangoObjectType):
    class Meta:
        model = AnimalHealthEvent
        fields = '__all__'


class HeatEventType(DjangoObjectType):
    class Meta:
        model = HeatEvent
        fields = '__all__'


class FeedingRecordType(DjangoObjectType):
    class Meta:
        model = FeedingRecord
        fields = '__all__'


class TrackingQuery(graphene.ObjectType):
    animals = graphene.List(AnimalRecordType, species=graphene.String(), status=graphene.String(), enterprise_id=graphene.UUID())
    animal = graphene.Field(AnimalRecordType, id=graphene.UUID(), tag_number=graphene.String(), rfid_tag=graphene.String())
    animal_weight_history = graphene.List(AnimalWeightEventType, animal_id=graphene.UUID(required=True))
    animal_health_events = graphene.List(AnimalHealthEventType, animal_id=graphene.UUID(required=True))
    heat_events = graphene.List(HeatEventType, status=graphene.String(), limit=graphene.Int())
    feeding_records = graphene.List(FeedingRecordType, animal_id=graphene.UUID(), pen=graphene.String(), limit=graphene.Int())
    pregnant_animals = graphene.List(AnimalRecordType)

    def resolve_animals(self, info, species=None, status=None, enterprise_id=None):
        qs = AnimalRecord.objects.filter(organization=_org(info))
        if species:
            qs = qs.filter(species=species)
        if status:
            qs = qs.filter(status=status)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_animal(self, info, id=None, tag_number=None, rfid_tag=None):
        qs = AnimalRecord.objects.filter(organization=_org(info))
        if id:
            return qs.get(pk=id)
        if tag_number:
            return qs.get(tag_number=tag_number)
        if rfid_tag:
            return qs.get(rfid_tag=rfid_tag)
        return None

    def resolve_animal_weight_history(self, info, animal_id):
        return AnimalWeightEvent.objects.filter(animal_id=animal_id, organization=_org(info))

    def resolve_animal_health_events(self, info, animal_id):
        return AnimalHealthEvent.objects.filter(animal_id=animal_id, organization=_org(info))

    def resolve_heat_events(self, info, status=None, limit=50):
        qs = HeatEvent.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs[:limit]

    def resolve_feeding_records(self, info, animal_id=None, pen=None, limit=100):
        qs = FeedingRecord.objects.filter(organization=_org(info))
        if animal_id:
            qs = qs.filter(animal_id=animal_id)
        if pen:
            qs = qs.filter(pen=pen)
        return qs[:limit]

    def resolve_pregnant_animals(self, info):
        return AnimalRecord.objects.filter(organization=_org(info), is_pregnant=True, status='active')


class CreateAnimal(graphene.Mutation):
    class Arguments:
        tag_number = graphene.String(required=True)
        species = graphene.String(required=True)
        sex = graphene.String()
        breed = graphene.String()
        rfid_tag = graphene.String()
        name = graphene.String()
        date_of_birth = graphene.Date()
        date_of_acquisition = graphene.Date()
        acquisition_cost = graphene.Float()
        current_weight_kg = graphene.Float()
        current_pen = graphene.String()
        enterprise_id = graphene.UUID()
        dam_tag = graphene.String()
        sire_tag = graphene.String()

    animal = graphene.Field(AnimalRecordType)

    def mutate(self, info, tag_number, species, **kwargs):
        animal = AnimalRecord.objects.create(
            organization=_org(info),
            tag_number=tag_number,
            species=species,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateAnimal(animal=animal)


class LogAnimalWeight(graphene.Mutation):
    class Arguments:
        animal_id = graphene.UUID(required=True)
        weight_kg = graphene.Float(required=True)
        weigh_date = graphene.Date(required=True)
        previous_weight_kg = graphene.Float()
        days_since_last = graphene.Int()
        notes = graphene.String()

    event = graphene.Field(AnimalWeightEventType)

    def mutate(self, info, animal_id, weight_kg, weigh_date, **kwargs):
        animal = AnimalRecord.objects.get(pk=animal_id, organization=_org(info))
        event = AnimalWeightEvent(
            animal=animal, organization=_org(info),
            weight_kg=weight_kg, weigh_date=weigh_date,
            weighed_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        event.save()
        return LogAnimalWeight(event=event)


class LogHealthEvent(graphene.Mutation):
    class Arguments:
        animal_id = graphene.UUID(required=True)
        event_type = graphene.String(required=True)
        event_date = graphene.Date(required=True)
        severity = graphene.String()
        diagnosis = graphene.String()
        treatment = graphene.String()
        medication = graphene.String()
        dosage = graphene.String()
        withholding_days = graphene.Int()
        cost = graphene.Float()
        vet_name = graphene.String()
        follow_up_date = graphene.Date()
        notes = graphene.String()

    event = graphene.Field(AnimalHealthEventType)

    def mutate(self, info, animal_id, event_type, event_date, **kwargs):
        animal = AnimalRecord.objects.get(pk=animal_id, organization=_org(info))
        event = AnimalHealthEvent.objects.create(
            animal=animal, organization=_org(info),
            event_type=event_type, event_date=event_date,
            recorded_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogHealthEvent(event=event)


class RecordHeatEvent(graphene.Mutation):
    class Arguments:
        animal_id = graphene.UUID(required=True)
        detected_at = graphene.DateTime(required=True)
        detection_method = graphene.String()
        status = graphene.String()
        sire_used = graphene.String()
        service_date = graphene.Date()
        is_ai = graphene.Boolean()
        notes = graphene.String()

    heat_event = graphene.Field(HeatEventType)

    def mutate(self, info, animal_id, detected_at, **kwargs):
        animal = AnimalRecord.objects.get(pk=animal_id, organization=_org(info))
        event = HeatEvent(
            animal=animal, organization=_org(info),
            detected_at=detected_at,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        event.save()
        return RecordHeatEvent(heat_event=event)


class LogFeeding(graphene.Mutation):
    class Arguments:
        feed_type = graphene.String(required=True)
        quantity_kg = graphene.Float(required=True)
        feed_date = graphene.Date(required=True)
        animal_id = graphene.UUID()
        pen = graphene.String()
        cost_per_kg = graphene.Float()
        feed_time = graphene.Time()
        dispensed_by = graphene.String()
        notes = graphene.String()

    record = graphene.Field(FeedingRecordType)

    def mutate(self, info, feed_type, quantity_kg, feed_date, **kwargs):
        record = FeedingRecord(
            organization=_org(info),
            feed_type=feed_type,
            quantity_kg=quantity_kg,
            feed_date=feed_date,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        record.save()
        return LogFeeding(record=record)


class TrackingMutation(graphene.ObjectType):
    create_animal = CreateAnimal.Field()
    log_animal_weight = LogAnimalWeight.Field()
    log_health_event = LogHealthEvent.Field()
    record_heat_event = RecordHeatEvent.Field()
    log_feeding = LogFeeding.Field()
