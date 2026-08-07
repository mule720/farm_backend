from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Organization, Profile


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'plan', 'country', 'is_active', 'created_at']
    list_filter = ['plan', 'is_active', 'country']
    search_fields = ['name', 'slug']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Profile)
class ProfileAdmin(UserAdmin):
    list_display = ['email', 'full_name', 'organization', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['email', 'full_name']
    ordering = ['email']
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_login']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal', {'fields': ('full_name', 'phone', 'avatar_url')}),
        ('Organization', {'fields': ('organization', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Preferences', {'fields': ('preferences',)}),
        ('Dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'organization', 'role', 'password1', 'password2'),
        }),
    )
    filter_horizontal = []
