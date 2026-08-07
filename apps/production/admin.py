from django.contrib import admin
from .models import ProductionRecord


@admin.register(ProductionRecord)
class ProductionRecordAdmin(admin.ModelAdmin):
    list_display = ['enterprise', 'batch', 'record_type', 'record_date', 'recorded_by']
    list_filter = ['record_type', 'organization', 'enterprise']
    search_fields = ['enterprise__name']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'record_date'
