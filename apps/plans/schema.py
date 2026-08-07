import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import Plan, PlanBudgetItem, DailyPlan, DailyPlanTask, MarketingPlan


# ─── Types ────────────────────────────────────────────────────────────────────

class PlanBudgetItemType(DjangoObjectType):
    class Meta:
        model = PlanBudgetItem
        fields = ['id', 'plan', 'category', 'item_name', 'description',
                  'quantity', 'unit', 'unit_cost', 'total_cost', 'actual_cost',
                  'notes', 'created_at']


class MarketingPlanType(DjangoObjectType):
    class Meta:
        model = MarketingPlan
        fields = ['id', 'plan', 'target_market', 'target_revenue', 'expected_quantity',
                  'expected_unit', 'expected_unit_price', 'channels', 'key_activities',
                  'notes', 'created_at', 'updated_at']


class PlanType(DjangoObjectType):
    estimated_total_cost = graphene.Float()
    actual_total_cost = graphene.Float()

    class Meta:
        model = Plan
        fields = ['id', 'enterprise', 'batch', 'plan_type', 'title', 'description',
                  'status', 'start_date', 'end_date', 'initiate_product',
                  'assigned_to', 'created_by', 'created_at', 'updated_at',
                  'budget_items', 'marketing_detail']

    def resolve_estimated_total_cost(self, info):
        return float(self.estimated_total_cost)

    def resolve_actual_total_cost(self, info):
        return float(self.actual_total_cost)


class DailyPlanTaskType(DjangoObjectType):
    class Meta:
        model = DailyPlanTask
        fields = ['id', 'daily_plan', 'title', 'task_type', 'description',
                  'assigned_to', 'priority', 'estimated_duration_hours',
                  'estimated_cost', 'actual_cost', 'status', 'completion_notes',
                  'completed_at', 'sort_order', 'created_at', 'updated_at']


class DailyPlanType(DjangoObjectType):
    estimated_cost = graphene.Float()
    completion_rate = graphene.Int()

    class Meta:
        model = DailyPlan
        fields = ['id', 'enterprise', 'batch', 'plan_date', 'title', 'notes',
                  'status', 'supervisor', 'created_by', 'created_at', 'updated_at',
                  'tasks']

    def resolve_estimated_cost(self, info):
        return float(self.estimated_cost)

    def resolve_completion_rate(self, info):
        return self.completion_rate


# ─── Inputs ───────────────────────────────────────────────────────────────────

class PlanInput(graphene.InputObjectType):
    enterprise_id = graphene.ID()
    batch_id = graphene.ID()
    plan_type = graphene.String(required=True)
    title = graphene.String(required=True)
    description = graphene.String()
    status = graphene.String()
    start_date = graphene.Date()
    end_date = graphene.Date()
    initiate_product = graphene.Boolean()
    assigned_to_id = graphene.ID()


class PlanBudgetItemInput(graphene.InputObjectType):
    plan_id = graphene.ID(required=True)
    category = graphene.String(required=True)
    item_name = graphene.String(required=True)
    description = graphene.String()
    quantity = graphene.Float()
    unit = graphene.String()
    unit_cost = graphene.Float()
    actual_cost = graphene.Float()
    notes = graphene.String()


class DailyPlanInput(graphene.InputObjectType):
    enterprise_id = graphene.ID()
    batch_id = graphene.ID()
    plan_date = graphene.Date(required=True)
    title = graphene.String()
    notes = graphene.String()
    status = graphene.String()
    supervisor_id = graphene.ID()


class DailyPlanTaskInput(graphene.InputObjectType):
    daily_plan_id = graphene.ID(required=True)
    title = graphene.String(required=True)
    task_type = graphene.String()
    description = graphene.String()
    assigned_to_id = graphene.ID()
    priority = graphene.String()
    estimated_duration_hours = graphene.Float()
    estimated_cost = graphene.Float()
    sort_order = graphene.Int()


class MarketingPlanInput(graphene.InputObjectType):
    plan_id = graphene.ID(required=True)
    target_market = graphene.String()
    target_revenue = graphene.Float()
    expected_quantity = graphene.Float()
    expected_unit = graphene.String()
    expected_unit_price = graphene.Float()
    channels = graphene.List(graphene.String)
    key_activities = graphene.List(graphene.String)
    notes = graphene.String()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class PlansQuery(graphene.ObjectType):
    plans = graphene.List(
        PlanType,
        plan_type=graphene.String(),
        status=graphene.String(),
        enterprise_id=graphene.ID(),
    )
    plan = graphene.Field(PlanType, id=graphene.ID(required=True))

    daily_plans = graphene.List(
        DailyPlanType,
        enterprise_id=graphene.ID(),
        date_from=graphene.Date(),
        date_to=graphene.Date(),
        status=graphene.String(),
    )
    daily_plan = graphene.Field(DailyPlanType, id=graphene.ID(required=True))
    daily_plan_by_date = graphene.Field(
        DailyPlanType,
        enterprise_id=graphene.ID(required=True),
        plan_date=graphene.Date(required=True),
    )

    def resolve_plans(self, info, plan_type=None, status=None, enterprise_id=None):
        org = _org(info)
        qs = Plan.objects.filter(organization=org).prefetch_related('budget_items')
        if plan_type:
            qs = qs.filter(plan_type=plan_type)
        if status:
            qs = qs.filter(status=status)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_plan(self, info, id):
        org = _org(info)
        return Plan.objects.prefetch_related('budget_items').get(id=id, organization=org)

    def resolve_daily_plans(self, info, enterprise_id=None, date_from=None,
                            date_to=None, status=None):
        org = _org(info)
        qs = DailyPlan.objects.filter(organization=org).prefetch_related('tasks')
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if date_from:
            qs = qs.filter(plan_date__gte=date_from)
        if date_to:
            qs = qs.filter(plan_date__lte=date_to)
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_daily_plan(self, info, id):
        org = _org(info)
        return DailyPlan.objects.prefetch_related('tasks').get(id=id, organization=org)

    def resolve_daily_plan_by_date(self, info, enterprise_id, plan_date):
        org = _org(info)
        try:
            return DailyPlan.objects.prefetch_related('tasks').get(
                organization=org, enterprise_id=enterprise_id, plan_date=plan_date
            )
        except DailyPlan.DoesNotExist:
            return None


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreatePlan(graphene.Mutation):
    class Arguments:
        input = PlanInput(required=True)

    plan = graphene.Field(PlanType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        plan = Plan.objects.create(
            organization=user.organization,
            created_by=user,
            enterprise_id=input.get('enterprise_id'),
            batch_id=input.get('batch_id'),
            plan_type=input.plan_type,
            title=input.title,
            description=input.get('description', ''),
            status=input.get('status', 'draft'),
            start_date=input.get('start_date'),
            end_date=input.get('end_date'),
            initiate_product=input.get('initiate_product', False),
            assigned_to_id=input.get('assigned_to_id'),
        )
        return CreatePlan(plan=plan)


class UpdatePlan(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = PlanInput(required=True)

    plan = graphene.Field(PlanType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        plan = Plan.objects.get(id=id, organization=user.organization)
        for field in ['enterprise_id', 'batch_id', 'plan_type', 'title', 'description',
                      'status', 'start_date', 'end_date', 'initiate_product', 'assigned_to_id']:
            val = input.get(field)
            if val is not None:
                setattr(plan, field, val)
        plan.save()
        return UpdatePlan(plan=plan)


class DeletePlan(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'supervisor', 'saas_admin'):
            raise Exception('Permission denied')
        Plan.objects.get(id=id, organization=user.organization).delete()
        return DeletePlan(success=True)


class CreatePlanBudgetItem(graphene.Mutation):
    class Arguments:
        input = PlanBudgetItemInput(required=True)

    item = graphene.Field(PlanBudgetItemType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        plan = Plan.objects.get(id=input.plan_id, organization=user.organization)
        item = PlanBudgetItem.objects.create(
            plan=plan,
            category=input.category,
            item_name=input.item_name,
            description=input.get('description', ''),
            quantity=input.get('quantity', 1),
            unit=input.get('unit', 'unit'),
            unit_cost=input.get('unit_cost', 0),
            actual_cost=input.get('actual_cost', 0),
            notes=input.get('notes', ''),
        )
        return CreatePlanBudgetItem(item=item)


class UpdatePlanBudgetItem(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        category = graphene.String()
        item_name = graphene.String()
        description = graphene.String()
        quantity = graphene.Float()
        unit = graphene.String()
        unit_cost = graphene.Float()
        actual_cost = graphene.Float()
        notes = graphene.String()

    item = graphene.Field(PlanBudgetItemType)

    def mutate(self, info, id, **kwargs):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        item = PlanBudgetItem.objects.get(id=id, plan__organization=user.organization)
        for k, v in kwargs.items():
            if v is not None:
                setattr(item, k, v)
        item.save()
        return UpdatePlanBudgetItem(item=item)


class DeletePlanBudgetItem(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        PlanBudgetItem.objects.get(id=id, plan__organization=user.organization).delete()
        return DeletePlanBudgetItem(success=True)


class CreateDailyPlan(graphene.Mutation):
    class Arguments:
        input = DailyPlanInput(required=True)

    daily_plan = graphene.Field(DailyPlanType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        daily_plan = DailyPlan.objects.create(
            organization=user.organization,
            created_by=user,
            enterprise_id=input.get('enterprise_id'),
            batch_id=input.get('batch_id'),
            plan_date=input.plan_date,
            title=input.get('title', ''),
            notes=input.get('notes', ''),
            status=input.get('status', 'draft'),
            supervisor_id=input.get('supervisor_id') or user.id,
        )
        return CreateDailyPlan(daily_plan=daily_plan)


class UpdateDailyPlan(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        title = graphene.String()
        notes = graphene.String()
        status = graphene.String()
        supervisor_id = graphene.ID()
        batch_id = graphene.ID()

    daily_plan = graphene.Field(DailyPlanType)

    def mutate(self, info, id, **kwargs):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        dp = DailyPlan.objects.get(id=id, organization=user.organization)
        for k, v in kwargs.items():
            if v is not None:
                setattr(dp, k, v)
        dp.save()
        return UpdateDailyPlan(daily_plan=dp)


class DeleteDailyPlan(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'supervisor', 'saas_admin'):
            raise Exception('Permission denied')
        DailyPlan.objects.get(id=id, organization=user.organization).delete()
        return DeleteDailyPlan(success=True)


class CreateDailyPlanTask(graphene.Mutation):
    class Arguments:
        input = DailyPlanTaskInput(required=True)

    task = graphene.Field(DailyPlanTaskType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        dp = DailyPlan.objects.get(id=input.daily_plan_id, organization=user.organization)
        task = DailyPlanTask.objects.create(
            daily_plan=dp,
            title=input.title,
            task_type=input.get('task_type', 'other'),
            description=input.get('description', ''),
            assigned_to_id=input.get('assigned_to_id'),
            priority=input.get('priority', 'medium'),
            estimated_duration_hours=input.get('estimated_duration_hours', 1),
            estimated_cost=input.get('estimated_cost', 0),
            sort_order=input.get('sort_order', 0),
        )
        return CreateDailyPlanTask(task=task)


class UpdateDailyPlanTask(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        title = graphene.String()
        task_type = graphene.String()
        description = graphene.String()
        assigned_to_id = graphene.ID()
        priority = graphene.String()
        estimated_duration_hours = graphene.Float()
        estimated_cost = graphene.Float()
        actual_cost = graphene.Float()
        status = graphene.String()
        completion_notes = graphene.String()
        sort_order = graphene.Int()

    task = graphene.Field(DailyPlanTaskType)

    def mutate(self, info, id, **kwargs):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        task = DailyPlanTask.objects.get(id=id, daily_plan__organization=user.organization)
        for k, v in kwargs.items():
            if v is not None:
                setattr(task, k, v)
        if kwargs.get('status') == 'done' and not task.completed_at:
            task.completed_at = timezone.now()
        task.save()
        return UpdateDailyPlanTask(task=task)


class DeleteDailyPlanTask(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        DailyPlanTask.objects.get(id=id, daily_plan__organization=user.organization).delete()
        return DeleteDailyPlanTask(success=True)


class UpsertMarketingPlan(graphene.Mutation):
    class Arguments:
        input = MarketingPlanInput(required=True)

    marketing_plan = graphene.Field(MarketingPlanType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        plan = Plan.objects.get(id=input.plan_id, organization=user.organization)
        mp, _ = MarketingPlan.objects.get_or_create(plan=plan)
        for field in ['target_market', 'target_revenue', 'expected_quantity',
                      'expected_unit', 'expected_unit_price', 'channels',
                      'key_activities', 'notes']:
            val = input.get(field)
            if val is not None:
                setattr(mp, field, val)
        mp.save()
        return UpsertMarketingPlan(marketing_plan=mp)


# ─── Root ─────────────────────────────────────────────────────────────────────

class PlansMutation(graphene.ObjectType):
    create_plan = CreatePlan.Field()
    update_plan = UpdatePlan.Field()
    delete_plan = DeletePlan.Field()

    create_plan_budget_item = CreatePlanBudgetItem.Field()
    update_plan_budget_item = UpdatePlanBudgetItem.Field()
    delete_plan_budget_item = DeletePlanBudgetItem.Field()

    create_daily_plan = CreateDailyPlan.Field()
    update_daily_plan = UpdateDailyPlan.Field()
    delete_daily_plan = DeleteDailyPlan.Field()

    create_daily_plan_task = CreateDailyPlanTask.Field()
    update_daily_plan_task = UpdateDailyPlanTask.Field()
    delete_daily_plan_task = DeleteDailyPlanTask.Field()

    upsert_marketing_plan = UpsertMarketingPlan.Field()
