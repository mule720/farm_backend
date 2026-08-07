from django.contrib import admin
from .models import AutomationRule, AutomationTriggerLog, Task


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'condition_metric', 'condition_operator', 'condition_value',
                    'action_type', 'is_enabled', 'trigger_count']
    list_filter = ['action_type', 'is_enabled', 'organization']
    search_fields = ['name', 'condition_metric']
    readonly_fields = ['id', 'trigger_count', 'last_triggered_at', 'created_at', 'updated_at']


@admin.register(AutomationTriggerLog)
class AutomationTriggerLogAdmin(admin.ModelAdmin):
    list_display = ['rule', 'triggered_value', 'action_taken', 'triggered_at']
    list_filter = ['rule', 'action_taken']
    readonly_fields = ['id', 'triggered_at']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'enterprise', 'assigned_to', 'status',
                    'priority', 'due_date']
    list_filter = ['status', 'priority', 'organization']
    search_fields = ['title']
    readonly_fields = ['id', 'created_at', 'updated_at']
