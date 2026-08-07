import graphene
from graphene_django import DjangoObjectType
from .models import KPIDefinition, KPIValue
from .calculator import evaluate_formula, compute_aggregation


class KPIDefinitionType(DjangoObjectType):
    latest_value = graphene.Float()
    status = graphene.String()

    class Meta:
        model = KPIDefinition
        fields = ['id', 'name', 'description', 'unit', 'aggregation', 'target',
                  'warning_threshold', 'critical_threshold', 'higher_is_better',
                  'icon', 'color', 'category', 'formula', 'is_active',
                  'enterprise', 'created_at', 'updated_at']

    def resolve_latest_value(self, info):
        v = self.values.first()
        return float(v.value) if v else None

    def resolve_status(self, info):
        v = self.values.first()
        if not v:
            return 'no_data'
        val = float(v.value)
        if self.critical_threshold is not None:
            c = float(self.critical_threshold)
            if (self.higher_is_better and val <= c) or (not self.higher_is_better and val >= c):
                return 'critical'
        if self.warning_threshold is not None:
            w = float(self.warning_threshold)
            if (self.higher_is_better and val <= w) or (not self.higher_is_better and val >= w):
                return 'warning'
        return 'ok'


class KPIValueType(DjangoObjectType):
    class Meta:
        model = KPIValue
        fields = ['id', 'kpi', 'batch', 'enterprise', 'value',
                  'recorded_at', 'recorded_by', 'source', 'notes']


class KPISummaryType(graphene.ObjectType):
    kpi_id = graphene.ID()
    name = graphene.String()
    unit = graphene.String()
    current_value = graphene.Float()
    target = graphene.Float()
    status = graphene.String()
    trend = graphene.List(graphene.Float)


# ─── Inputs ──────────────────────────────────────────────────────────────────

class KPIDefinitionInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    description = graphene.String()
    unit = graphene.String()
    aggregation = graphene.String()
    target = graphene.Float()
    warning_threshold = graphene.Float()
    critical_threshold = graphene.Float()
    higher_is_better = graphene.Boolean()
    icon = graphene.String()
    color = graphene.String()
    category = graphene.String()
    formula = graphene.String()
    enterprise_id = graphene.ID()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class KPIQuery(graphene.ObjectType):
    kpis = graphene.List(
        KPIDefinitionType,
        enterprise_id=graphene.ID(),
        category=graphene.String(),
        is_active=graphene.Boolean(),
    )
    kpi = graphene.Field(KPIDefinitionType, id=graphene.ID(required=True))
    kpi_values = graphene.List(
        KPIValueType,
        kpi_id=graphene.ID(required=True),
        batch_id=graphene.ID(),
        limit=graphene.Int(),
    )
    kpi_summary = graphene.List(KPISummaryType, enterprise_id=graphene.ID())

    def resolve_kpis(self, info, enterprise_id=None, category=None, is_active=None):
        org = _org(info)
        qs = KPIDefinition.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if category:
            qs = qs.filter(category=category)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def resolve_kpi(self, info, id):
        org = _org(info)
        return KPIDefinition.objects.get(id=id, organization=org)

    def resolve_kpi_values(self, info, kpi_id, batch_id=None, limit=50):
        org = _org(info)
        qs = KPIValue.objects.filter(kpi_id=kpi_id, organization=org)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs[:limit]

    def resolve_kpi_summary(self, info, enterprise_id=None):
        org = _org(info)
        qs = KPIDefinition.objects.filter(organization=org, is_active=True)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        result = []
        for kpi in qs:
            values = list(kpi.values.values_list('value', flat=True)[:10])
            current = compute_aggregation(values, kpi.aggregation) if values else None
            target = float(kpi.target) if kpi.target else None
            status = 'no_data'
            if current is not None and kpi.critical_threshold:
                c = float(kpi.critical_threshold)
                status = 'critical' if (
                    (kpi.higher_is_better and current <= c) or
                    (not kpi.higher_is_better and current >= c)
                ) else 'ok'
            result.append(KPISummaryType(
                kpi_id=str(kpi.id),
                name=kpi.name,
                unit=kpi.unit,
                current_value=current,
                target=target,
                status=status,
                trend=[float(v) for v in values],
            ))
        return result


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateKPI(graphene.Mutation):
    class Arguments:
        input = KPIDefinitionInput(required=True)

    kpi = graphene.Field(KPIDefinitionType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        kpi = KPIDefinition.objects.create(
            organization=user.organization,
            created_by=user,
            **{k: v for k, v in input.items() if v is not None and k != 'enterprise_id'},
            enterprise_id=input.get('enterprise_id'),
        )
        return CreateKPI(kpi=kpi)


class UpdateKPI(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = KPIDefinitionInput(required=True)

    kpi = graphene.Field(KPIDefinitionType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        kpi = KPIDefinition.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None:
                setattr(kpi, k, v)
        kpi.save()
        return UpdateKPI(kpi=kpi)


class DeleteKPI(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'saas_admin'):
            raise Exception('Permission denied')
        KPIDefinition.objects.get(id=id, organization=user.organization).delete()
        return DeleteKPI(success=True)


class RecordKPIValue(graphene.Mutation):
    class Arguments:
        kpi_id = graphene.ID(required=True)
        value = graphene.Float(required=True)
        batch_id = graphene.ID()
        enterprise_id = graphene.ID()
        notes = graphene.String()

    kpi_value = graphene.Field(KPIValueType)

    def mutate(self, info, kpi_id, value, batch_id=None, enterprise_id=None, notes=''):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        kpi = KPIDefinition.objects.get(id=kpi_id, organization=user.organization)
        kv = KPIValue.objects.create(
            organization=user.organization,
            kpi=kpi,
            value=value,
            batch_id=batch_id,
            enterprise_id=enterprise_id or kpi.enterprise_id,
            recorded_by=user,
            source='manual',
            notes=notes,
        )
        return RecordKPIValue(kpi_value=kv)


class CalculateKPI(graphene.Mutation):
    """Evaluate a formula-based KPI from recent production records."""
    class Arguments:
        kpi_id = graphene.ID(required=True)
        batch_id = graphene.ID()

    kpi_value = graphene.Field(KPIValueType)
    computed_value = graphene.Float()

    def mutate(self, info, kpi_id, batch_id=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        kpi = KPIDefinition.objects.get(id=kpi_id, organization=user.organization)
        if not kpi.formula:
            raise Exception('This KPI has no formula defined.')
        value = evaluate_formula(kpi.formula, kpi.organization, batch_id)
        kv = KPIValue.objects.create(
            organization=user.organization,
            kpi=kpi,
            value=value,
            batch_id=batch_id,
            enterprise_id=kpi.enterprise_id,
            recorded_by=user,
            source='formula',
        )
        return CalculateKPI(kpi_value=kv, computed_value=float(value))


class KPIMutation(graphene.ObjectType):
    create_kpi = CreateKPI.Field()
    update_kpi = UpdateKPI.Field()
    delete_kpi = DeleteKPI.Field()
    record_kpi_value = RecordKPIValue.Field()
    calculate_kpi = CalculateKPI.Field()
