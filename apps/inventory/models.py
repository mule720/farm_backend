import uuid
from django.db import models
from django.conf import settings


class InventoryItem(models.Model):
    CATEGORY_CHOICES = [
        ('feed', 'Feed'), ('medicine', 'Medicine'), ('equipment', 'Equipment'),
        ('chemical', 'Chemical'), ('packaging', 'Packaging'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='inventory_items'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inventory_items'
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='feed')
    sku = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=50, default='kg')
    current_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    supplier = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_items'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level

    @property
    def stock_value(self):
        if self.unit_cost:
            return self.current_stock * self.unit_cost
        return None


class InventoryTransaction(models.Model):
    TYPE_CHOICES = [
        ('purchase', 'Purchase'), ('usage', 'Usage'), ('adjustment', 'Adjustment'),
        ('transfer', 'Transfer'), ('disposal', 'Disposal'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='inventory_transactions'
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, related_name='transactions'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inventory_transactions'
    )
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inventory_transactions'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        if self.unit_cost and not self.total_cost:
            self.total_cost = abs(self.quantity) * self.unit_cost
        super().save(*args, **kwargs)
        # Update stock
        item = self.item
        if self.transaction_type in ('purchase', 'adjustment'):
            item.current_stock += self.quantity
        elif self.transaction_type in ('usage', 'disposal', 'transfer'):
            item.current_stock -= abs(self.quantity)
        item.save(update_fields=['current_stock'])

    def __str__(self):
        return f'{self.transaction_type} — {self.item.name} ({self.quantity})'
