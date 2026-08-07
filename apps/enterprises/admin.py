from django.contrib import admin
from .models import EnterpriseTemplate, Enterprise, EnterpriseStage, EnterpriseBatch


@admin.register(EnterpriseTemplate)
class EnterpriseTemplateAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'category', 'is_built_in']
    list_filter = ['category', 'is_built_in']
    search_fields = ['id', 'name']


@admin.register(Enterprise)
class EnterpriseAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'template', 'category', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization']
    search_fields = ['name', 'category']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(EnterpriseStage)
class EnterpriseStageAdmin(admin.ModelAdmin):
    list_display = ['name', 'enterprise', 'stage_order', 'duration_days']
    list_filter = ['enterprise']
    ordering = ['enterprise', 'stage_order']


@admin.register(EnterpriseBatch)
class EnterpriseBatchAdmin(admin.ModelAdmin):
    list_display = ['name', 'enterprise', 'current_stage', 'status', 'start_date']
    list_filter = ['status', 'enterprise']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'updated_at']
