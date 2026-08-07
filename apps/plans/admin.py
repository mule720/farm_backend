from django.contrib import admin
from .models import Plan, PlanBudgetItem, DailyPlan, DailyPlanTask, MarketingPlan


class PlanBudgetItemInline(admin.TabularInline):
    model = PlanBudgetItem
    extra = 0
    readonly_fields = ['total_cost']


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['title', 'plan_type', 'status', 'enterprise', 'start_date', 'end_date', 'created_by']
    list_filter = ['plan_type', 'status', 'organization']
    search_fields = ['title', 'description']
    inlines = [PlanBudgetItemInline]
    readonly_fields = ['estimated_total_cost', 'actual_total_cost']


@admin.register(PlanBudgetItem)
class PlanBudgetItemAdmin(admin.ModelAdmin):
    list_display = ['item_name', 'category', 'quantity', 'unit_cost', 'total_cost', 'plan']
    list_filter = ['category']
    readonly_fields = ['total_cost']


class DailyPlanTaskInline(admin.TabularInline):
    model = DailyPlanTask
    extra = 0


@admin.register(DailyPlan)
class DailyPlanAdmin(admin.ModelAdmin):
    list_display = ['plan_date', 'enterprise', 'status', 'supervisor', 'created_by']
    list_filter = ['status', 'organization']
    inlines = [DailyPlanTaskInline]


@admin.register(DailyPlanTask)
class DailyPlanTaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'task_type', 'status', 'priority', 'assigned_to', 'daily_plan']
    list_filter = ['status', 'priority', 'task_type']


@admin.register(MarketingPlan)
class MarketingPlanAdmin(admin.ModelAdmin):
    list_display = ['plan', 'target_market', 'target_revenue', 'expected_quantity']
