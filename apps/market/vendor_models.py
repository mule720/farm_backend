"""
Vendor operations — what a marketplace provider needs to *run* its business
inside AGRINUXES, beyond the public directory profile:

* VendorOrder        — sales orders for dealers, agri-supply and agrifood sellers
* WorkOrder          — jobs for service providers and transporters
* EquipmentMaintenance — service / repair log per catalogue item
* ProcessingBatch    — intake → processing → finished goods (traceability lots)
* VendorInvoice      — invoices across every vendor type
"""
import uuid
import datetime
from django.conf import settings
from django.db import models

from .provider_models import Provider, ProviderService, ProviderStaff, EquipmentCatalog


def _ref(model, prefix, field):
    yr = datetime.date.today().year
    n = model.objects.filter(**{f'{field}__startswith': f'{prefix}-{yr}-'}).count()
    return f'{prefix}-{yr}-{n + 1:04d}'


class VendorOrder(models.Model):
    """A sale of goods by a dealer / supplier / agrifood seller (walk-in or platform customer)."""

    STATUS_CHOICES = [('new', 'New'), ('confirmed', 'Confirmed'), ('packed', 'Packed / Ready'), ('out_for_delivery', 'Out for delivery'),
                      ('delivered', 'Delivered'), ('cancelled', 'Cancelled')]
    SOURCE_CHOICES = [('walk_in', 'Walk-in / phone'), ('marketplace', 'Marketplace'), ('voucher', 'Programme voucher')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_ref = models.CharField(max_length=30, unique=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='orders')
    client_org = models.ForeignKey('accounts.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_orders')
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='walk_in')
    items = models.JSONField(default=list, help_text='[{listing_id?, name, quantity, unit, unit_price}]')
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='ZMW')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    delivery_required = models.BooleanField(default=False)
    delivery_address = models.TextField(blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_orders'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_ref:
            self.order_ref = _ref(VendorOrder, 'SO', 'order_ref')
        super().save(*args, **kwargs)


class WorkOrder(models.Model):
    """A job for a service provider (irrigation install, soil test, spraying, transport run …)."""

    KIND_CHOICES = [('service', 'Service job'), ('transport', 'Transport / haulage'), ('delivery', 'Delivery'),
                    ('installation', 'Installation'), ('consulting', 'Consulting / advisory'), ('other', 'Other')]
    STATUS_CHOICES = [('requested', 'Requested'), ('quoted', 'Quoted'), ('scheduled', 'Scheduled'), ('in_progress', 'In progress'),
                      ('completed', 'Completed'), ('cancelled', 'Cancelled')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_ref = models.CharField(max_length=30, unique=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='work_orders')
    service = models.ForeignKey(ProviderService, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_orders')
    client_org = models.ForeignKey('accounts.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='work_orders')
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=50, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='service')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True, help_text='Site / farm / pick-up')
    destination = models.CharField(max_length=255, blank=True, help_text='Drop-off for transport jobs')
    district = models.CharField(max_length=100, blank=True)
    distance_km = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=30, blank=True, help_text='ha, tonnes, trips, hours')
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    assigned_staff = models.ForeignKey(ProviderStaff, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    equipment = models.ForeignKey(EquipmentCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested')
    quoted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    agreed_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default='ZMW')
    paid = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_work_orders'
        ordering = ['-scheduled_date', '-created_at']

    def save(self, *args, **kwargs):
        if not self.job_ref:
            self.job_ref = _ref(WorkOrder, 'JOB', 'job_ref')
        super().save(*args, **kwargs)


class EquipmentMaintenance(models.Model):
    KIND_CHOICES = [('service', 'Routine service'), ('repair', 'Repair'), ('inspection', 'Inspection'), ('tyres', 'Tyres / tracks'), ('other', 'Other')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    equipment = models.ForeignKey(EquipmentCatalog, on_delete=models.CASCADE, related_name='maintenance')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='service')
    date = models.DateField()
    description = models.CharField(max_length=255)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='ZMW')
    hours_reading = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    downtime_days = models.PositiveSmallIntegerField(default=0)
    next_due_date = models.DateField(null=True, blank=True)
    performed_by = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vendor_equipment_maintenance'
        ordering = ['-date']


class ProcessingBatch(models.Model):
    """One processing lot: raw intake from a source → finished product. Carries traceability."""

    STATUS_CHOICES = [('received', 'Raw material received'), ('processing', 'Processing'), ('completed', 'Completed'),
                      ('sold_out', 'Sold out'), ('rejected', 'Rejected / QC fail')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lot_code = models.CharField(max_length=30, unique=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='batches')
    source_org = models.ForeignKey('accounts.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='supplied_batches')
    source_name = models.CharField(max_length=255, blank=True)
    source_district = models.CharField(max_length=100, blank=True)
    input_commodity = models.CharField(max_length=255)
    input_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    input_unit = models.CharField(max_length=20, default='kg')
    price_paid = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, help_text='Total paid to the source')
    currency = models.CharField(max_length=10, default='ZMW')
    received_on = models.DateField()
    product = models.CharField(max_length=255, blank=True, help_text='Finished product, e.g. Mealie meal 25 kg')
    output_quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    output_unit = models.CharField(max_length=20, blank=True)
    quantity_sold = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    started_on = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    qc_passed = models.BooleanField(null=True, blank=True)
    qc_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_processing_batches'
        ordering = ['-received_on', '-created_at']

    def save(self, *args, **kwargs):
        if not self.lot_code:
            self.lot_code = _ref(ProcessingBatch, 'LOT', 'lot_code')
        super().save(*args, **kwargs)

    @property
    def yield_pct(self):
        if self.output_quantity is None or not self.input_quantity:
            return None
        return round(float(self.output_quantity) / float(self.input_quantity) * 100, 1)


class VendorInvoice(models.Model):
    STATUS_CHOICES = [('draft', 'Draft'), ('sent', 'Sent'), ('paid', 'Paid'), ('overdue', 'Overdue'), ('void', 'Void')]
    LINK_CHOICES = [('', 'None'), ('hire', 'Hire booking'), ('vet', 'Vet appointment'), ('job', 'Work order'), ('order', 'Sales order')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_ref = models.CharField(max_length=30, unique=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='invoices')
    client_org = models.ForeignKey('accounts.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_invoices')
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=50, blank=True)
    link_type = models.CharField(max_length=10, choices=LINK_CHOICES, blank=True, default='')
    link_id = models.UUIDField(null=True, blank=True)
    link_ref = models.CharField(max_length=30, blank=True)
    items = models.JSONField(default=list, help_text='[{description, quantity, unit_price}]')
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='ZMW')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    issued_on = models.DateField()
    due_on = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_invoices'
        ordering = ['-issued_on', '-created_at']

    def save(self, *args, **kwargs):
        if not self.invoice_ref:
            self.invoice_ref = _ref(VendorInvoice, 'INV', 'invoice_ref')
        super().save(*args, **kwargs)
