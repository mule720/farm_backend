import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import AutomationRule, AutomationTriggerLog, Task
from .engine import evaluate_rule


class AutomationRuleType(DjangoObjectType):
    trigger_count = graphene.Int()

    class Meta:
        model = AutomationRule
        fields = ['id', 'name', 'description', 'is_enabled', 'condition_metric',
                  'condition_operator', 'condition_value', 'action_type',
                  'action_message', 'action_assign_to', 'action_channel',
                  'action_priority', 'cooldown_minutes', 'last_triggered_at',
                  'enterprise', 'created_at', 'updated_at']

    def resolve_trigger_count(self, info):
        return self.trigger_logs.count()


class TriggerLogType(DjangoObjectType):
    class Meta:
        model = AutomationTriggerLog
        fields = ['id', 'rule', 'triggered_at', 'triggered_value',
                  'action_taken', 'notified_user', 'resolved', 'resolved_at']


class TaskType(DjangoObjectType):
    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'status', 'priority',
                  'assigned_to', 'due_date', 'completed_at', 'source',
                  'automation_rule', 'enterprise', 'batch', 'created_at', 'updated_at']


# ─── Inputs ──────────────────────────────────────────────────────────────────

class AutomationRuleInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    description = graphene.String()
    enterprise_id = graphene.ID()
    is_enabled = graphene.Boolean()
    condition_metric = graphene.String(required=True)
    condition_operator = graphene.String(required=True)
    condition_value = graphene.Float(required=True)
    action_type = graphene.String(required=True)
    action_message = graphene.String(required=True)
    action_assign_to_id = graphene.ID()
    action_channel = graphene.String()
    action_priority = graphene.String()
    cooldown_minutes = graphene.Int()


class TaskInput(graphene.InputObjectType):
    title = graphene.String(required=True)
    description = graphene.String()
    enterprise_id = graphene.ID()
    batch_id = graphene.ID()
    priority = graphene.String()
    assigned_to_id = graphene.ID()
    due_date = graphene.Date()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class AutomationQuery(graphene.ObjectType):
    automation_rules = graphene.List(
        AutomationRuleType,
        enterprise_id=graphene.ID(),
        is_enabled=graphene.Boolean(),
    )
    automation_rule = graphene.Field(AutomationRuleType, id=graphene.ID(required=True))
    trigger_log = graphene.List(
        TriggerLogType,
        rule_id=graphene.ID(),
        resolved=graphene.Boolean(),
        limit=graphene.Int(),
    )

    tasks = graphene.List(
        TaskType,
        status=graphene.String(),
        priority=graphene.String(),
        assigned_to_id=graphene.ID(),
        enterprise_id=graphene.ID(),
    )
    task = graphene.Field(TaskType, id=graphene.ID(required=True))
    my_tasks = graphene.List(TaskType, status=graphene.String())

    def resolve_automation_rules(self, info, enterprise_id=None, is_enabled=None):
        org = _org(info)
        qs = AutomationRule.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if is_enabled is not None:
            qs = qs.filter(is_enabled=is_enabled)
        return qs

    def resolve_automation_rule(self, info, id):
        org = _org(info)
        return AutomationRule.objects.get(id=id, organization=org)

    def resolve_trigger_log(self, info, rule_id=None, resolved=None, limit=50):
        org = _org(info)
        qs = AutomationTriggerLog.objects.filter(organization=org)
        if rule_id:
            qs = qs.filter(rule_id=rule_id)
        if resolved is not None:
            qs = qs.filter(resolved=resolved)
        return qs[:limit]

    def resolve_tasks(self, info, status=None, priority=None,
                      assigned_to_id=None, enterprise_id=None):
        org = _org(info)
        qs = Task.objects.filter(organization=org)
        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if assigned_to_id:
            qs = qs.filter(assigned_to_id=assigned_to_id)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_task(self, info, id):
        org = _org(info)
        return Task.objects.get(id=id, organization=org)

    def resolve_my_tasks(self, info, status=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        qs = Task.objects.filter(organization=user.organization, assigned_to=user)
        if status:
            qs = qs.filter(status=status)
        return qs


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateAutomationRule(graphene.Mutation):
    class Arguments:
        input = AutomationRuleInput(required=True)

    rule = graphene.Field(AutomationRuleType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        rule = AutomationRule.objects.create(
            organization=user.organization,
            created_by=user,
            name=input.name,
            description=input.get('description', ''),
            enterprise_id=input.get('enterprise_id'),
            is_enabled=input.get('is_enabled', True),
            condition_metric=input.condition_metric,
            condition_operator=input.condition_operator,
            condition_value=input.condition_value,
            action_type=input.action_type,
            action_message=input.action_message,
            action_assign_to_id=input.get('action_assign_to_id'),
            action_channel=input.get('action_channel', 'in_app'),
            action_priority=input.get('action_priority', 'warning'),
            cooldown_minutes=input.get('cooldown_minutes', 60),
        )
        return CreateAutomationRule(rule=rule)


class UpdateAutomationRule(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = AutomationRuleInput(required=True)

    rule = graphene.Field(AutomationRuleType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        rule = AutomationRule.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None:
                setattr(rule, k, v)
        rule.save()
        return UpdateAutomationRule(rule=rule)


class ToggleAutomationRule(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    rule = graphene.Field(AutomationRuleType)

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        rule = AutomationRule.objects.get(id=id, organization=user.organization)
        rule.is_enabled = not rule.is_enabled
        rule.save()
        return ToggleAutomationRule(rule=rule)


class DeleteAutomationRule(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'saas_admin'):
            raise Exception('Permission denied')
        AutomationRule.objects.get(id=id, organization=user.organization).delete()
        return DeleteAutomationRule(success=True)


class TestAutomationRule(graphene.Mutation):
    """Manually evaluate a rule against a supplied metric value."""
    class Arguments:
        id = graphene.ID(required=True)
        test_value = graphene.Float(required=True)

    triggered = graphene.Boolean()
    message = graphene.String()
    log = graphene.Field(TriggerLogType)

    def mutate(self, info, id, test_value):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        rule = AutomationRule.objects.get(id=id, organization=user.organization)
        triggered, log = evaluate_rule(rule, test_value, user, dry_run=False)
        return TestAutomationRule(
            triggered=triggered,
            message=f'Rule {"triggered" if triggered else "not triggered"} for value {test_value}',
            log=log,
        )


class ResolveAlert(graphene.Mutation):
    class Arguments:
        log_id = graphene.ID(required=True)

    log = graphene.Field(TriggerLogType)

    def mutate(self, info, log_id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        log = AutomationTriggerLog.objects.get(id=log_id, organization=user.organization)
        log.resolved = True
        log.resolved_at = timezone.now()
        log.save()
        return ResolveAlert(log=log)


class CreateTask(graphene.Mutation):
    class Arguments:
        input = TaskInput(required=True)

    task = graphene.Field(TaskType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        task = Task.objects.create(
            organization=user.organization,
            created_by=user,
            title=input.title,
            description=input.get('description', ''),
            enterprise_id=input.get('enterprise_id'),
            batch_id=input.get('batch_id'),
            priority=input.get('priority', 'medium'),
            assigned_to_id=input.get('assigned_to_id'),
            due_date=input.get('due_date'),
        )
        return CreateTask(task=task)


class UpdateTask(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        status = graphene.String()
        priority = graphene.String()
        assigned_to_id = graphene.ID()
        due_date = graphene.Date()
        description = graphene.String()

    task = graphene.Field(TaskType)

    def mutate(self, info, id, status=None, priority=None,
               assigned_to_id=None, due_date=None, description=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        task = Task.objects.get(id=id, organization=user.organization)
        if status:
            task.status = status
            if status == 'done':
                task.completed_at = timezone.now()
        if priority:
            task.priority = priority
        if assigned_to_id is not None:
            task.assigned_to_id = assigned_to_id
        if due_date is not None:
            task.due_date = due_date
        if description is not None:
            task.description = description
        task.save()
        return UpdateTask(task=task)


class DeleteTask(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        Task.objects.get(id=id, organization=user.organization).delete()
        return DeleteTask(success=True)


class AutomationMutation(graphene.ObjectType):
    create_automation_rule = CreateAutomationRule.Field()
    update_automation_rule = UpdateAutomationRule.Field()
    toggle_automation_rule = ToggleAutomationRule.Field()
    delete_automation_rule = DeleteAutomationRule.Field()
    test_automation_rule = TestAutomationRule.Field()
    resolve_alert = ResolveAlert.Field()
    create_task = CreateTask.Field()
    update_task = UpdateTask.Field()
    delete_task = DeleteTask.Field()
