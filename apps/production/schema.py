import graphene
from graphene_django import DjangoObjectType
from .models import ProductionRecord


class ProductionRecordType(DjangoObjectType):
    class Meta:
        model = ProductionRecord
        fields = ['id', 'enterprise', 'batch', 'stage', 'record_date',
                  'record_type', 'data', 'recorded_by', 'created_at']
        convert_choices_to_enum = False


class ProductionStatsType(graphene.ObjectType):
    enterprise_id = graphene.ID()
    total_records = graphene.Int()
    date_from = graphene.Date()
    date_to = graphene.Date()
    record_types = graphene.List(graphene.String)


# ─── Inputs ──────────────────────────────────────────────────────────────────

class ProductionRecordInput(graphene.InputObjectType):
    enterprise_id = graphene.ID(required=True)
    record_date = graphene.Date(required=True)
    record_type = graphene.String()
    data = graphene.JSONString(required=True)
    batch_id = graphene.ID()
    stage_id = graphene.ID()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class ProductionQuery(graphene.ObjectType):
    production_records = graphene.List(
        ProductionRecordType,
        enterprise_id=graphene.ID(),
        batch_id=graphene.ID(),
        record_type=graphene.String(),
        date_from=graphene.Date(),
        date_to=graphene.Date(),
        limit=graphene.Int(),
    )
    production_record = graphene.Field(ProductionRecordType, id=graphene.ID(required=True))
    production_stats = graphene.Field(ProductionStatsType, enterprise_id=graphene.ID(required=True))

    def resolve_production_records(self, info, enterprise_id=None, batch_id=None,
                                    record_type=None, date_from=None, date_to=None, limit=100):
        org = _org(info)
        qs = ProductionRecord.objects.filter(organization=org).order_by('-record_date', '-created_at')
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if record_type:
            qs = qs.filter(record_type=record_type)
        if date_from:
            qs = qs.filter(record_date__gte=date_from)
        if date_to:
            qs = qs.filter(record_date__lte=date_to)
        return qs[:limit]

    def resolve_production_record(self, info, id):
        org = _org(info)
        return ProductionRecord.objects.get(id=id, organization=org)

    def resolve_production_stats(self, info, enterprise_id):
        org = _org(info)
        qs = ProductionRecord.objects.filter(organization=org, enterprise_id=enterprise_id)
        from django.db.models import Min, Max
        agg = qs.aggregate(d_from=Min('record_date'), d_to=Max('record_date'))
        types = list(qs.values_list('record_type', flat=True).distinct())
        return ProductionStatsType(
            enterprise_id=enterprise_id,
            total_records=qs.count(),
            date_from=agg['d_from'],
            date_to=agg['d_to'],
            record_types=types,
        )


# ─── Mutations ────────────────────────────────────────────────────────────────

# ─── Validation helpers ───────────────────────────────────────────────────────

# Per-field acceptable ranges — (min, max, human label)
_RANGES = {
    'mortality':        (0,      5000,   'Mortality count'),
    'mortality_count':  (0,      5000,   'Mortality count'),
    'feed_kg':          (0,      50000,  'Feed (kg)'),
    'feed_consumed_kg': (0,      50000,  'Feed consumed (kg)'),
    'water_l':          (0,     200000,  'Water (L)'),
    'water_consumed_l': (0,     200000,  'Water (L)'),
    'avg_weight_kg':    (0.001,   300,   'Average weight (kg)'),
    'weight_kg':        (0.001,   300,   'Weight (kg)'),
    'quantity':         (0,     200000,  'Quantity'),
    'eggs_count':       (0,     500000,  'Egg count'),
    'temperature_c':    (-10,    60,     'Temperature (°C)'),
    'humidity_pct':     (0,     100,     'Humidity (%)'),
}


def _validate_data(data: dict):
    """Raise Exception if any data field is outside its expected range."""
    for key, value in data.items():
        k = key.lower()
        if k in _RANGES and value is not None:
            lo, hi, label = _RANGES[k]
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if not (lo <= v <= hi):
                raise Exception(
                    f'{label} value {v} is out of the expected range ({lo}–{hi}). '
                    f'Please check the figure and resubmit.'
                )


class CreateProductionRecord(graphene.Mutation):
    class Arguments:
        input = ProductionRecordInput(required=True)

    record = graphene.Field(ProductionRecordType)
    was_updated = graphene.Boolean()   # True if an existing record was updated instead of created

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')

        data = input.data or {}
        _validate_data(data)

        record_type = input.get('record_type', 'daily')
        batch_id = input.get('batch_id')

        # ── Upsert: update existing record if same enterprise+batch+date+type ─
        lookup = dict(
            organization=user.organization,
            enterprise_id=input.enterprise_id,
            record_date=input.record_date,
            record_type=record_type,
        )
        if batch_id:
            lookup['batch_id'] = batch_id

        existing = ProductionRecord.objects.filter(**lookup).first()
        if existing:
            # Merge new data into existing record (overwrite changed keys, keep others)
            merged = dict(existing.data or {})
            merged.update(data)
            existing.data = merged
            existing.recorded_by = user
            existing.save(update_fields=['data', 'recorded_by'])
            record = existing
            was_updated = True
        else:
            record = ProductionRecord.objects.create(
                organization=user.organization,
                recorded_by=user,
                enterprise_id=input.enterprise_id,
                record_date=input.record_date,
                record_type=record_type,
                data=data,
                batch_id=batch_id,
                stage_id=input.get('stage_id'),
            )
            was_updated = False

        # Run automation rules on the saved data
        from apps.automation.engine import run_all_rules
        for metric, value in data.items():
            try:
                run_all_rules(user.organization, metric, float(value), user)
            except (ValueError, TypeError):
                pass
        return CreateProductionRecord(record=record, was_updated=was_updated)


class UpdateProductionRecord(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        data = graphene.JSONString(required=True)

    record = graphene.Field(ProductionRecordType)

    def mutate(self, info, id, data):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        _validate_data(data if isinstance(data, dict) else {})
        record = ProductionRecord.objects.get(id=id, organization=user.organization)
        merged = dict(record.data or {})
        merged.update(data if isinstance(data, dict) else {})
        record.data = merged
        record.save(update_fields=['data'])
        return UpdateProductionRecord(record=record)


class DeleteProductionRecord(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'supervisor', 'saas_admin'):
            raise Exception('Permission denied')
        ProductionRecord.objects.get(id=id, organization=user.organization).delete()
        return DeleteProductionRecord(success=True)


class ProductionMutation(graphene.ObjectType):
    create_production_record = CreateProductionRecord.Field()
    update_production_record = UpdateProductionRecord.Field()
    delete_production_record = DeleteProductionRecord.Field()
