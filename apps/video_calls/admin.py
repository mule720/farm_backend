from django.contrib import admin
from .models import VideoCall


@admin.register(VideoCall)
class VideoCallAdmin(admin.ModelAdmin):
    list_display  = ('room_name', 'initiator', 'provider_name', 'status', 'started_at', 'ended_at')
    list_filter   = ('status',)
    search_fields = ('room_name', 'provider_name', 'initiator__username')
    readonly_fields = ('id', 'room_name', 'started_at', 'joined_at', 'ended_at')
