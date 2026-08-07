from django.contrib import admin
from .models import AIVisionAnalysis, StockCountLog, FarmerReport, DroneFieldReport


@admin.register(AIVisionAnalysis)
class AIVisionAnalysisAdmin(admin.ModelAdmin):
    list_display = ['analysis_type', 'diagnosis', 'severity', 'confidence_pct',
                    'enterprise', 'is_public', 'created_at']
    list_filter = ['analysis_type', 'severity', 'is_public']
    readonly_fields = ['findings', 'recommendations', 'extra_data']


@admin.register(StockCountLog)
class StockCountLogAdmin(admin.ModelAdmin):
    list_display = ['enterprise', 'batch', 'counted_quantity', 'expected_quantity',
                    'discrepancy', 'discrepancy_pct', 'status', 'counted_at']
    list_filter = ['status', 'organization']


@admin.register(FarmerReport)
class FarmerReportAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'visibility', 'is_resolved', 'helpful_count', 'created_at']
    list_filter = ['category', 'visibility', 'is_resolved']


@admin.register(DroneFieldReport)
class DroneFieldReportAdmin(admin.ModelAdmin):
    list_display = ['enterprise', 'overall_health', 'health_score', 'generated_at']
    list_filter = ['overall_health']
