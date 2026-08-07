import graphene
from graphene_django import DjangoObjectType
from .models import EnterpriseTemplate, Enterprise, EnterpriseStage, EnterpriseBatch


class EnterpriseTemplateType(DjangoObjectType):
    class Meta:
        model = EnterpriseTemplate
        fields = ['id', 'name', 'category', 'production_type', 'icon', 'color',
                  'description', 'is_built_in', 'stages', 'kpis', 'forms',
                  'inventory_rules', 'financial_categories', 'automation_rules',
                  'dashboard_widgets', 'tags', 'version', 'created_at', 'updated_at']


class EnterpriseType(DjangoObjectType):
    stage_count = graphene.Int()
    active_batch_count = graphene.Int()

    class Meta:
        model = Enterprise
        fields = ['id', 'name', 'category', 'production_type', 'icon', 'color',
                  'description', 'batch_unit', 'settings', 'is_active',
                  'template', 'created_at', 'updated_at']

    def resolve_stage_count(self, info):
        return self.stages.count()

    def resolve_active_batch_count(self, info):
        return self.batches.filter(status='active').count()


class EnterpriseStageType(DjangoObjectType):
    class Meta:
        model = EnterpriseStage
        fields = ['id', 'name', 'stage_order', 'duration_days', 'color',
                  'description', 'feeding_rules', 'health_checks', 'kpi_targets',
                  'alerts', 'required_records', 'created_at', 'updated_at']


class EnterpriseBatchType(DjangoObjectType):
    class Meta:
        model = EnterpriseBatch
        fields = ['id', 'name', 'batch_number', 'quantity', 'unit', 'start_date',
                  'expected_end_date', 'actual_end_date', 'status', 'notes',
                  'metadata', 'enterprise', 'current_stage', 'created_at', 'updated_at']
        convert_choices_to_enum = False


# ─── Inputs ──────────────────────────────────────────────────────────────────

class CreateEnterpriseInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    category = graphene.String(required=True)
    production_type = graphene.String(required=True)
    icon = graphene.String()
    color = graphene.String()
    description = graphene.String()
    batch_unit = graphene.String()
    template_id = graphene.String()
    settings = graphene.JSONString()


class UpdateEnterpriseInput(graphene.InputObjectType):
    name = graphene.String()
    icon = graphene.String()
    color = graphene.String()
    description = graphene.String()
    batch_unit = graphene.String()
    is_active = graphene.Boolean()
    settings = graphene.JSONString()


class StageInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    stage_order = graphene.Int()
    duration_days = graphene.Int()
    color = graphene.String()
    description = graphene.String()
    feeding_rules = graphene.JSONString()
    health_checks = graphene.JSONString()
    kpi_targets = graphene.JSONString()
    alerts = graphene.JSONString()
    required_records = graphene.JSONString()


class CreateBatchInput(graphene.InputObjectType):
    enterprise_id = graphene.ID(required=True)
    name = graphene.String(required=True)
    batch_number = graphene.String()
    quantity = graphene.Float(required=True)
    unit = graphene.String()
    start_date = graphene.Date(required=True)
    expected_end_date = graphene.Date()
    notes = graphene.String()
    metadata = graphene.JSONString()


class CreateTemplateInput(graphene.InputObjectType):
    id = graphene.String(required=True)
    name = graphene.String(required=True)
    category = graphene.String(required=True)
    production_type = graphene.String(required=True)
    icon = graphene.String()
    color = graphene.String()
    description = graphene.String()
    stages = graphene.JSONString()
    kpis = graphene.JSONString()
    forms = graphene.JSONString()
    tags = graphene.JSONString()


# ─── Queries ──────────────────────────────────────────────────────────────────

def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class EnterpriseQuery(graphene.ObjectType):
    templates = graphene.List(
        EnterpriseTemplateType,
        category=graphene.String(),
        built_in_only=graphene.Boolean(),
    )
    template = graphene.Field(EnterpriseTemplateType, id=graphene.String(required=True))

    enterprises = graphene.List(EnterpriseType, is_active=graphene.Boolean())
    enterprise = graphene.Field(EnterpriseType, id=graphene.ID(required=True))

    stages = graphene.List(EnterpriseStageType, enterprise_id=graphene.ID(required=True))

    batches = graphene.List(
        EnterpriseBatchType,
        enterprise_id=graphene.ID(),
        status=graphene.String(),
    )
    batch = graphene.Field(EnterpriseBatchType, id=graphene.ID(required=True))

    def resolve_templates(self, info, category=None, built_in_only=None):
        org = _org(info)
        qs = EnterpriseTemplate.objects.filter(
            graphene.Q(is_built_in=True) | graphene.Q(organization=org)
        )
        if category:
            qs = qs.filter(category=category)
        if built_in_only:
            qs = qs.filter(is_built_in=True)
        return qs

    def resolve_template(self, info, id):
        org = _org(info)
        from django.db.models import Q
        return EnterpriseTemplate.objects.get(
            Q(id=id) & (Q(is_built_in=True) | Q(organization=org))
        )

    def resolve_enterprises(self, info, is_active=None):
        org = _org(info)
        qs = Enterprise.objects.filter(organization=org)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def resolve_enterprise(self, info, id):
        org = _org(info)
        return Enterprise.objects.get(id=id, organization=org)

    def resolve_stages(self, info, enterprise_id):
        org = _org(info)
        return EnterpriseStage.objects.filter(enterprise_id=enterprise_id, organization=org)

    def resolve_batches(self, info, enterprise_id=None, status=None):
        org = _org(info)
        qs = EnterpriseBatch.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_batch(self, info, id):
        org = _org(info)
        return EnterpriseBatch.objects.get(id=id, organization=org)


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateEnterprise(graphene.Mutation):
    class Arguments:
        input = CreateEnterpriseInput(required=True)

    enterprise = graphene.Field(EnterpriseType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        template = None
        if input.get('template_id'):
            template = EnterpriseTemplate.objects.get(id=input.template_id)
        ent = Enterprise.objects.create(
            organization=user.organization,
            template=template,
            name=input.name,
            category=input.category,
            production_type=input.production_type,
            icon=input.get('icon', 'leaf'),
            color=input.get('color', '#2D5016'),
            description=input.get('description', ''),
            batch_unit=input.get('batch_unit', 'batch'),
            settings=input.get('settings') or {},
            created_by=user,
        )
        return CreateEnterprise(enterprise=ent)


class UpdateEnterprise(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = UpdateEnterpriseInput(required=True)

    enterprise = graphene.Field(EnterpriseType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        ent = Enterprise.objects.get(id=id, organization=user.organization)
        for field, value in input.items():
            if value is not None:
                setattr(ent, field, value)
        ent.save()
        return UpdateEnterprise(enterprise=ent)


class DeleteEnterprise(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied')
        Enterprise.objects.get(id=id, organization=user.organization).delete()
        return DeleteEnterprise(success=True)


class CreateStage(graphene.Mutation):
    class Arguments:
        enterprise_id = graphene.ID(required=True)
        input = StageInput(required=True)

    stage = graphene.Field(EnterpriseStageType)

    def mutate(self, info, enterprise_id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        ent = Enterprise.objects.get(id=enterprise_id, organization=user.organization)
        stage = EnterpriseStage.objects.create(
            enterprise=ent,
            organization=user.organization,
            name=input.name,
            stage_order=input.get('stage_order', 0),
            duration_days=input.get('duration_days'),
            color=input.get('color', '#2D5016'),
            description=input.get('description', ''),
            feeding_rules=input.get('feeding_rules') or [],
            health_checks=input.get('health_checks') or [],
            kpi_targets=input.get('kpi_targets') or [],
            alerts=input.get('alerts') or [],
            required_records=input.get('required_records') or [],
        )
        return CreateStage(stage=stage)


class UpdateStage(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = StageInput(required=True)

    stage = graphene.Field(EnterpriseStageType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        stage = EnterpriseStage.objects.get(id=id, organization=user.organization)
        for field, value in input.items():
            if value is not None:
                setattr(stage, field, value)
        stage.save()
        return UpdateStage(stage=stage)


class DeleteStage(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        EnterpriseStage.objects.get(id=id, organization=user.organization).delete()
        return DeleteStage(success=True)


class CreateBatch(graphene.Mutation):
    class Arguments:
        input = CreateBatchInput(required=True)

    batch = graphene.Field(EnterpriseBatchType)

    def mutate(self, info, input):
        from decimal import Decimal
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        ent = Enterprise.objects.get(id=input.enterprise_id, organization=user.organization)
        first_stage = ent.stages.order_by('stage_order').first()
        batch = EnterpriseBatch.objects.create(
            organization=user.organization,
            enterprise=ent,
            name=input.name,
            batch_number=input.get('batch_number', ''),
            quantity=Decimal(str(input.quantity)),
            unit=input.get('unit', ent.batch_unit),
            start_date=input.start_date,
            expected_end_date=input.get('expected_end_date'),
            notes=input.get('notes', ''),
            metadata=input.get('metadata') or {},
            current_stage=first_stage,
            created_by=user,
        )
        return CreateBatch(batch=batch)


class UpdateBatch(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        status = graphene.String()
        notes = graphene.String()
        current_stage_id = graphene.ID()
        metadata = graphene.JSONString()

    batch = graphene.Field(EnterpriseBatchType)

    def mutate(self, info, id, status=None, notes=None, current_stage_id=None, metadata=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        batch = EnterpriseBatch.objects.get(id=id, organization=user.organization)
        if status:
            batch.status = status
            if status == 'completed':
                from django.utils import timezone
                batch.actual_end_date = timezone.now().date()
        if notes is not None:
            batch.notes = notes
        if current_stage_id:
            batch.current_stage = EnterpriseStage.objects.get(
                id=current_stage_id, enterprise=batch.enterprise
            )
        if metadata:
            batch.metadata = metadata
        batch.save()
        return UpdateBatch(batch=batch)


class AdvanceBatchStage(graphene.Mutation):
    class Arguments:
        batch_id = graphene.ID(required=True)

    batch = graphene.Field(EnterpriseBatchType)
    message = graphene.String()

    def mutate(self, info, batch_id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        batch = EnterpriseBatch.objects.get(id=batch_id, organization=user.organization)
        stages = list(batch.enterprise.stages.order_by('stage_order'))
        if not stages:
            raise Exception('No stages defined for this enterprise.')
        if batch.current_stage is None:
            batch.current_stage = stages[0]
            msg = f'Batch moved to stage: {stages[0].name}'
        else:
            current_idx = next((i for i, s in enumerate(stages) if s.id == batch.current_stage_id), -1)
            if current_idx >= len(stages) - 1:
                batch.status = 'completed'
                from django.utils import timezone
                batch.actual_end_date = timezone.now().date()
                msg = 'Batch completed — final stage reached.'
            else:
                batch.current_stage = stages[current_idx + 1]
                msg = f'Batch advanced to stage: {stages[current_idx + 1].name}'
        batch.save()
        return AdvanceBatchStage(batch=batch, message=msg)


class CreateCustomTemplate(graphene.Mutation):
    class Arguments:
        input = CreateTemplateInput(required=True)

    template = graphene.Field(EnterpriseTemplateType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        template = EnterpriseTemplate.objects.create(
            id=input.id,
            organization=user.organization,
            name=input.name,
            category=input.category,
            production_type=input.production_type,
            icon=input.get('icon', 'leaf'),
            color=input.get('color', '#2D5016'),
            description=input.get('description', ''),
            stages=input.get('stages') or [],
            kpis=input.get('kpis') or [],
            forms=input.get('forms') or [],
            tags=input.get('tags') or [],
            is_built_in=False,
            created_by=user,
        )
        return CreateCustomTemplate(template=template)


class EnterpriseMutation(graphene.ObjectType):
    create_enterprise = CreateEnterprise.Field()
    update_enterprise = UpdateEnterprise.Field()
    delete_enterprise = DeleteEnterprise.Field()
    create_stage = CreateStage.Field()
    update_stage = UpdateStage.Field()
    delete_stage = DeleteStage.Field()
    create_batch = CreateBatch.Field()
    update_batch = UpdateBatch.Field()
    advance_batch_stage = AdvanceBatchStage.Field()
    create_custom_template = CreateCustomTemplate.Field()
