from django.contrib import admin
from .models import AIRecommendation


@admin.register(AIRecommendation)
class AIRecommendationAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'recommendation_type', 'urgency',
                    'is_actioned', 'generated_at']
    list_filter = ['recommendation_type', 'urgency', 'is_actioned', 'organization']
    search_fields = ['title']
    readonly_fields = ['id', 'generated_at']
