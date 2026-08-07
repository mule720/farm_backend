from django.contrib import admin
from .models import DashboardWidget, Report


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ['title', 'widget_type', 'organization', 'profile', 'widget_size',
                    'widget_order', 'is_enabled']
    list_filter = ['widget_type', 'widget_size', 'is_enabled', 'organization']
    search_fields = ['title']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['name', 'report_type', 'output_format', 'status',
                    'generated_by', 'generated_at']
    list_filter = ['report_type', 'output_format', 'status', 'organization']
    search_fields = ['name']
    readonly_fields = ['id', 'generated_at']
