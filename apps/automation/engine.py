"""Automation rule evaluation engine."""
from django.utils import timezone
from .models import AutomationRule, AutomationTriggerLog, Task


OPERATORS = {
    'gt': lambda a, b: a > b,
    'lt': lambda a, b: a < b,
    'gte': lambda a, b: a >= b,
    'lte': lambda a, b: a <= b,
    'eq': lambda a, b: a == b,
    'neq': lambda a, b: a != b,
}


def evaluate_rule(rule: AutomationRule, current_value: float, user=None,
                  dry_run: bool = False):
    """
    Returns (triggered: bool, log: AutomationTriggerLog | None).

    If dry_run=True, does not persist the log or create tasks.
    """
    op_fn = OPERATORS.get(rule.condition_operator)
    if op_fn is None:
        return False, None

    triggered = op_fn(current_value, float(rule.condition_value))
    if not triggered:
        return False, None

    # Check cooldown
    if rule.last_triggered_at and not dry_run:
        elapsed = (timezone.now() - rule.last_triggered_at).total_seconds() / 60
        if elapsed < rule.cooldown_minutes:
            return False, None

    if dry_run:
        return True, None

    # Record trigger log
    log = AutomationTriggerLog.objects.create(
        organization=rule.organization,
        rule=rule,
        triggered_value=current_value,
        action_taken=rule.action_message,
        notified_user=rule.action_assign_to or user,
    )

    # Execute action
    if rule.action_type == 'task':
        Task.objects.create(
            organization=rule.organization,
            title=f'[Auto] {rule.name}',
            description=rule.action_message,
            priority=rule.action_priority,
            assigned_to=rule.action_assign_to,
            source='automation',
            automation_rule=rule,
        )

    # Update rule stats
    rule.last_triggered_at = timezone.now()
    rule.trigger_count += 1
    rule.save(update_fields=['last_triggered_at', 'trigger_count'])

    return True, log


def run_all_rules(organization, metric: str, value: float, user=None):
    """Evaluate all enabled rules that watch a given metric for an org."""
    rules = AutomationRule.objects.filter(
        organization=organization,
        is_enabled=True,
        condition_metric=metric,
    )
    results = []
    for rule in rules:
        triggered, log = evaluate_rule(rule, value, user)
        if triggered:
            results.append({'rule': rule, 'log': log})
    return results
