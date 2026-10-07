"""Sales: customers, orders and the payments received against them — one copy per organisation."""
import uuid
from datetime import date as date_cls
from decimal import Decimal

from django.conf import settings
from django.db import models


class SaleCustomer(models.Model):
    TYPES = ('individual', 'business', 'wholesale', 'export')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='sale_customers')
    name = models.CharField(max_length=255)
    customer_type = models.CharField(max_length=20, default='individual')
    phone = models.CharField(max_length=40, blank=True)
    email = models.CharField(max_length=254, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    legacy_id = models.CharField(max_length=64, blank=True, help_text='Id from the old browser-only record, for idempotent import')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale_customers'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'legacy_id'], condition=~models.Q(legacy_id=''), name='uniq_sale_customer_legacy'),
        ]

    def __str__(self):
        return self.name


class SaleOrder(models.Model):
    STATUSES = ('draft', 'confirmed', 'fulfilled', 'cancelled')
    # status → statuses it may move to
    FLOW = {'draft': {'confirmed', 'cancelled'}, 'confirmed': {'fulfilled', 'cancelled'}, 'fulfilled': set(), 'cancelled': set()}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='sale_orders')
    order_number = models.CharField(max_length=40)
    customer = models.ForeignKey(SaleCustomer, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    customer_name = models.CharField(max_length=255, help_text='Kept on the order so it survives deleting the customer')
    date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, default='draft')
    lines = models.JSONField(default=list, help_text='[{id, description, qty, unit, unitPrice}]')
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    discount_amt = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cycle_ref = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    legacy_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale_orders'
        ordering = ['-date', '-created_at']
        indexes = [models.Index(fields=['organization', 'date'])]
        constraints = [
            models.UniqueConstraint(fields=['organization', 'order_number'], name='uniq_sale_order_number'),
            models.UniqueConstraint(fields=['organization', 'legacy_id'], condition=~models.Q(legacy_id=''), name='uniq_sale_order_legacy'),
        ]

    def __str__(self):
        return self.order_number

    @property
    def payment_status(self):
        if self.amount_paid >= self.total and self.total > 0:
            return 'paid'
        late = self.due_date is not None and self.due_date < date_cls.today() and self.status != 'cancelled'
        if self.amount_paid > Decimal('0'):
            return 'overdue' if late else 'partial'
        return 'overdue' if late and self.total > 0 else 'unpaid'


class SalePayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(SaleOrder, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_on = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sale_payments'
        ordering = ['paid_on', 'created_at']
