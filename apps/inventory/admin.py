from django.contrib import admin
from .models import InventoryItem, InventoryTransaction


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'unit', 'current_stock', 'reorder_level',
                    'unit_cost', 'supplier', 'organization']
    list_filter = ['category', 'organization']
    search_fields = ['name', 'supplier']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ['item', 'transaction_type', 'quantity', 'recorded_by', 'recorded_at']
    list_filter = ['transaction_type', 'item']
    readonly_fields = ['id', 'recorded_at']
