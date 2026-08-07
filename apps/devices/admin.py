from django.contrib import admin
from .models import Device, SensorReading, DroneFlight, CameraEvent, SecurityAlert


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'device_type', 'model', 'status', 'battery_pct',
                    'signal_strength', 'organization', 'last_seen_at']
    list_filter = ['device_type', 'status', 'organization']
    search_fields = ['name', 'model']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ['device', 'metric', 'value', 'unit', 'is_alert', 'recorded_at']
    list_filter = ['metric', 'is_alert', 'organization']
    readonly_fields = ['id', 'recorded_at']
    date_hierarchy = 'recorded_at'


@admin.register(DroneFlight)
class DroneFlightAdmin(admin.ModelAdmin):
    list_display = ['device', 'flight_type', 'status', 'area_covered_ha',
                    'altitude_m', 'piloted_by', 'start_time']
    list_filter = ['flight_type', 'status', 'organization']
    readonly_fields = ['id', 'created_at']


@admin.register(CameraEvent)
class CameraEventAdmin(admin.ModelAdmin):
    list_display = ['device', 'event_type', 'confidence', 'is_reviewed',
                    'reviewed_by', 'detected_at']
    list_filter = ['event_type', 'is_reviewed', 'organization']
    readonly_fields = ['id', 'detected_at']


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'source', 'severity', 'is_resolved',
                    'resolved_by', 'created_at']
    list_filter = ['source', 'severity', 'is_resolved', 'organization']
    search_fields = ['title']
    readonly_fields = ['id', 'created_at']
