from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ('title', 'recipient', 'category', 'priority', 'is_read', 'created_at')
    list_filter   = ('priority', 'category', 'is_read')
    search_fields = ('title', 'message', 'recipient__email')
    readonly_fields = ('id', 'created_at', 'read_at')
    ordering      = ('-created_at',)
