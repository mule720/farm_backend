import graphene
from graphene_django import DjangoObjectType
from .models import Equipment, EquipmentTelemetry, FieldOperation, MaintenanceRecord
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class EquipmentType(DjangoObjectType):
    class Meta:
        model = Equipment
        fields = '__all__'

    hours_until_service = graphene.Float()
    service_due_soon = graphene.Boolean()

    def resolve_hours_until_service(self, info):
        return self.hours_until_service

    def resolve_service_due_soon(self, info):
        return self.service_due_soon


class EquipmentTelemetryType(DjangoObjectType):
    class Meta:
        model = EquipmentTelemetry
        fields = '__all__'


class FieldOperationType(DjangoObjectType):
    class Meta:
        model = FieldOperation
        fields = '__all__'


class MaintenanceRecordType(DjangoObjectType):
    class Meta:
        model = MaintenanceRecord
        fields = '__all__'


class EquipmentQuery(graphene.ObjectType):
    all_equipment = graphene.List(EquipmentType, status=graphene.String())
    equipment_item = graphene.Field(EquipmentType, id=graphene.UUID(required=True))
    equipment_telemetry = graphene.List(EquipmentTelemetryType, equipment_id=graphene.UUID(required=True), limit=graphene.Int())
    field_operations = graphene.List(FieldOperationType, equipment_id=graphene.UUID(), status=graphene.String(), limit=graphene.Int())
    maintenance_records = graphene.List(MaintenanceRecordType, equipment_id=graphene.UUID(required=True))
    service_due = graphene.List(EquipmentType)

    def resolve_all_equipment(self, info, status=None):
        qs = Equipment.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_equipment_item(self, info, id):
        return Equipment.objects.get(pk=id, organization=_org(info))

    def resolve_equipment_telemetry(self, info, equipment_id, limit=100):
        return EquipmentTelemetry.objects.filter(equipment_id=equipment_id, organization=_org(info))[:limit]

    def resolve_field_operations(self, info, equipment_id=None, status=None, limit=50):
        qs = FieldOperation.objects.filter(organization=_org(info))
        if equipment_id:
            qs = qs.filter(equipment_id=equipment_id)
        if status:
            qs = qs.filter(status=status)
        return qs[:limit]

    def resolve_maintenance_records(self, info, equipment_id):
        return MaintenanceRecord.objects.filter(equipment_id=equipment_id, organization=_org(info))

    def resolve_service_due(self, info):
        items = Equipment.objects.filter(organization=_org(info), status='operational')
        return [e for e in items if e.service_due_soon]


class CreateEquipment(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        equipment_type = graphene.String()
        model_number = graphene.String()
        manufacturer = graphene.String()
        serial_number = graphene.String()
        autonomous_level = graphene.String()
        purchase_cost = graphene.Float()
        purchase_date = graphene.Date()
        service_interval_hours = graphene.Int()

    equipment = graphene.Field(EquipmentType)

    def mutate(self, info, name, **kwargs):
        eq = Equipment.objects.create(
            organization=_org(info), name=name,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateEquipment(equipment=eq)


class UpdateEquipmentStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)
        notes = graphene.String()

    equipment = graphene.Field(EquipmentType)

    def mutate(self, info, id, status, notes=None):
        eq = Equipment.objects.get(pk=id, organization=_org(info))
        eq.status = status
        if notes:
            eq.notes = notes
        eq.save()
        return UpdateEquipmentStatus(equipment=eq)


class LogTelemetry(graphene.Mutation):
    class Arguments:
        equipment_id = graphene.UUID(required=True)
        latitude = graphene.Float()
        longitude = graphene.Float()
        speed_kmh = graphene.Float()
        engine_hours = graphene.Float()
        fuel_pct = graphene.Int()
        rpm = graphene.Int()
        is_engine_on = graphene.Boolean()
        is_autonomous = graphene.Boolean()
        alerts = graphene.List(graphene.String)

    telemetry = graphene.Field(EquipmentTelemetryType)

    def mutate(self, info, equipment_id, **kwargs):
        eq = Equipment.objects.get(pk=equipment_id, organization=_org(info))
        t = EquipmentTelemetry(
            equipment=eq, organization=_org(info),
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        t.save()
        return LogTelemetry(telemetry=t)


class CreateFieldOperation(graphene.Mutation):
    class Arguments:
        operation_type = graphene.String(required=True)
        scheduled_date = graphene.Date(required=True)
        equipment_id = graphene.UUID()
        enterprise_id = graphene.UUID()
        field_name = graphene.String()
        area_ha = graphene.Float()
        notes = graphene.String()

    operation = graphene.Field(FieldOperationType)

    def mutate(self, info, operation_type, scheduled_date, **kwargs):
        op = FieldOperation.objects.create(
            organization=_org(info),
            operation_type=operation_type,
            scheduled_date=scheduled_date,
            operator=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateFieldOperation(operation=op)


class UpdateFieldOperation(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String()
        hours_spent = graphene.Float()
        fuel_used_l = graphene.Float()
        cost = graphene.Float()
        notes = graphene.String()

    operation = graphene.Field(FieldOperationType)

    def mutate(self, info, id, **kwargs):
        op = FieldOperation.objects.get(pk=id, organization=_org(info))
        for k, v in kwargs.items():
            if v is not None:
                setattr(op, k, v)
        op.save()
        return UpdateFieldOperation(operation=op)


class CreateMaintenanceRecord(graphene.Mutation):
    class Arguments:
        equipment_id = graphene.UUID(required=True)
        maintenance_type = graphene.String()
        description = graphene.String(required=True)
        technician = graphene.String()
        labour_cost = graphene.Float()
        parts_cost = graphene.Float()
        engine_hours_at_service = graphene.Float()
        service_date = graphene.Date(required=True)
        next_service_date = graphene.Date()

    record = graphene.Field(MaintenanceRecordType)

    def mutate(self, info, equipment_id, description, service_date, **kwargs):
        eq = Equipment.objects.get(pk=equipment_id, organization=_org(info))
        record = MaintenanceRecord(
            equipment=eq, organization=_org(info),
            description=description, service_date=service_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        record.save()
        return CreateMaintenanceRecord(record=record)


class EquipmentMutation(graphene.ObjectType):
    create_equipment = CreateEquipment.Field()
    update_equipment_status = UpdateEquipmentStatus.Field()
    log_telemetry = LogTelemetry.Field()
    create_field_operation = CreateFieldOperation.Field()
    update_field_operation = UpdateFieldOperation.Field()
    create_maintenance_record = CreateMaintenanceRecord.Field()
