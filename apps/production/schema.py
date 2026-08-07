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
        qs = ProductionRecord.objects.filter(organization=org)
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

class CreateProductionRecord(graphene.Mutation):
    class Arguments:
        input = ProductionRecordInput(required=True)

    record = graphene.Field(ProductionRecordType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        record = ProductionRecord.objects.create(
            organization=user.organization,
            recorded_by=user,
            enterprise_id=input.enterprise_id,
            record_date=input.record_date,
            record_type=input.get('record_type', 'daily'),
            data=input.data or {},
            batch_id=input.get('batch_id'),
            stage_id=input.get('stage_id'),
        )
        # After saving, run automation rules on the new data
        from apps.automation.engine import run_all_rules
        for metric, value in (input.data or {}).items():
            try:
                run_all_rules(user.organization, metric, float(value), user)
            except (ValueError, TypeError):
                pass
        return CreateProductionRecord(record=record)


class UpdateProductionRecord(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        data = graphene.JSONString(required=True)

    record = graphene.Field(ProductionRecordType)

    def mutate(self, info, id, data):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        record = ProductionRecord.objects.get(id=id, organization=user.organization)
        record.data = data
        record.save()
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
