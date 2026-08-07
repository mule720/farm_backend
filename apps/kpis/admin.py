from django.contrib import admin
from .models import KPIDefinition, KPIValue


@admin.register(KPIDefinition)
class KPIDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'enterprise', 'unit', 'aggregation', 'is_active']
    list_filter = ['aggregation', 'is_active', 'higher_is_better', 'organization']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(KPIValue)
class KPIValueAdmin(admin.ModelAdmin):
    list_display = ['kpi', 'value', 'source', 'recorded_at']
    list_filter = ['source', 'kpi']
    readonly_fields = ['id', 'recorded_at']
