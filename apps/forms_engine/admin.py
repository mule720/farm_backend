from django.contrib import admin
from .models import CustomField, Form, FormField, FormSubmission


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ['name', 'label', 'field_type', 'organization', 'is_active']
    list_filter = ['field_type', 'is_active', 'organization']
    search_fields = ['name', 'label']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'enterprise', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(FormField)
class FormFieldAdmin(admin.ModelAdmin):
    list_display = ['form', 'custom_field', 'field_order', 'is_required']
    list_filter = ['is_required', 'form']
    ordering = ['form', 'field_order']


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = ['form', 'enterprise', 'submitted_by', 'submitted_at']
    list_filter = ['form', 'organization']
    readonly_fields = ['id', 'submitted_at']
