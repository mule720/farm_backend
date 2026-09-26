"""
Marketplace Provider models — AgroNexus Phase 3 backend
Extends the existing market app with persistent provider profiles,
services, reviews, certifications, equipment catalogs, bookings, and vet appointments.
"""
import uuid
from django.db import models
from django.conf import settings


PROVIDER_TYPE_CHOICES = [
    ('agro_dealer',     'Agro Dealer / Input Supplier'),
    ('equipment_hire',  'Equipment Hire'),
    ('vet_services',    'Veterinary Services'),
    ('processing',      'Agro Processing'),
    ('transport',       'Transport & Logistics'),
    ('finance',         'Agricultural Finance'),
    ('insurance',       'Crop / Livestock Insurance'),
    ('extension',       'Extension & Advisory Services'),
    ('cold_storage',    'Cold Storage'),
    ('certification',   'Certification & Inspection'),
    ('agrifood',        'AgriFood Seller / Fresh Produce'),
    ('agri_services',   'Agricultural Services'),
]

# Organization.business_type -> directory provider_type
BUSINESS_TO_PROVIDER_TYPE = {
    'agro_dealer': 'agro_dealer', 'agrisupply_provider': 'agro_dealer', 'vet_provider': 'vet_services', 'equipment_hire': 'equipment_hire',
    'processor': 'processing', 'transport': 'transport', 'agriservices_provider': 'agri_services', 'agrifood_seller': 'agrifood',
    'cooperative': 'agrifood', 'farmer': 'agrifood',
}

ZAMBIA_DISTRICTS = [
    'Lusaka', 'Kitwe', 'Ndola', 'Kabwe', 'Chingola', 'Mufulira', 'Livingstone',
    'Kasama', 'Chipata', 'Solwezi', 'Mansa', 'Mongu', 'Choma', 'Mazabuka',
    'Kalulushi', 'Kafue', 'Luanshya', 'Mbala', 'Kapiri Mposhi', 'Sesheke',
    'Petauke', 'Lundazi', 'Isoka', 'Nakonde', 'Samfya', 'Nchelenge', 'Other',
]


class Provider(models.Model):
    """Core provider business profile — persistent identity across the platform."""

    STATUS_CHOICES = [
        ('pending',   'Pending Review'),
        ('active',    'Active / Verified'),
        ('suspended', 'Suspended'),
        ('inactive',  'Inactive'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_type   = models.CharField(max_length=20, choices=PROVIDER_TYPE_CHOICES)
    name            = models.CharField(max_length=255)
    slug            = models.SlugField(max_length=280, unique=True)
    tagline         = models.CharField(max_length=255, blank=True)
    description     = models.TextField(blank=True)

    # Contact
    phone           = models.CharField(max_length=50, blank=True)
    email           = models.EmailField(blank=True)
    website         = models.URLField(blank=True)
    whatsapp        = models.CharField(max_length=50, blank=True)

    # Location
    district        = models.CharField(max_length=100, blank=True)
    town            = models.CharField(max_length=100, blank=True)
    address         = models.TextField(blank=True)
    latitude        = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude       = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    coverage_districts = models.JSONField(default=list, help_text='Districts this provider serves')

    # Profile media
    logo_url        = models.CharField(max_length=500, blank=True)
    cover_url       = models.CharField(max_length=500, blank=True)
    photos          = models.JSONField(default=list)

    # Trust & verification
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_verified     = models.BooleanField(default=False)
    verified_at     = models.DateTimeField(null=True, blank=True)
    verified_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='verified_providers'
    )
    trust_score     = models.DecimalField(max_digits=4, decimal_places=2, default=0)

    # Business metadata
    year_established = models.PositiveSmallIntegerField(null=True, blank=True)
    business_reg_no  = models.CharField(max_length=100, blank=True)
    tax_id           = models.CharField(max_length=100, blank=True)
    tags             = models.JSONField(default=list)
    specialties      = models.JSONField(default=list, help_text='Crops, species, or domains of expertise')
    service_hours    = models.CharField(max_length=255, blank=True, help_text='e.g. Mon-Fri 08:00-17:00')
    mobile_service   = models.BooleanField(default=False, help_text='Provider comes to the farm')
    emergency_available = models.BooleanField(default=False)

    # Aggregate stats (denormalised for fast reads)
    review_count    = models.PositiveIntegerField(default=0)
    avg_rating      = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    booking_count   = models.PositiveIntegerField(default=0)

    # Ownership — the farm/org that registered this provider
    registered_by   = models.ForeignKey(
        'accounts.Organization', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='registered_providers'
    )
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_providers'
    )
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_providers'
        ordering = ['-avg_rating', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_provider_type_display()})'

    def update_rating(self):
        """Recalculate avg_rating and review_count from ProviderReview."""
        reviews = self.reviews.filter(approved=True)
        self.review_count = reviews.count()
        if self.review_count:
            total = sum(r.rating for r in reviews)
            self.avg_rating = round(total / self.review_count, 2)
        else:
            self.avg_rating = 0
        self.save(update_fields=['review_count', 'avg_rating'])


class ProviderStaff(models.Model):
    """Staff members listed under a provider (vet officers, sales reps, technicians)."""

    ROLE_CHOICES = [
        ('owner',       'Owner / Director'),
        ('manager',     'Branch Manager'),
        ('vet_officer', 'Veterinary Officer'),
        ('agronomist',  'Agronomist'),
        ('sales_rep',   'Sales Representative'),
        ('technician',  'Technician'),
        ('driver',      'Driver / Delivery'),
        ('other',       'Other'),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider    = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='staff')
    name        = models.CharField(max_length=255)
    role        = models.CharField(max_length=20, choices=ROLE_CHOICES, default='other')
    phone       = models.CharField(max_length=50, blank=True)
    email       = models.EmailField(blank=True)
    bio         = models.TextField(blank=True)
    qualifications = models.JSONField(default=list)
    photo_url   = models.CharField(max_length=500, blank=True)
    licence_no  = models.CharField(max_length=100, blank=True, help_text='HPCZ/VRAZ/ZEMA licence number')
    active      = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'provider_staff'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} — {self.provider.name}'


class ProviderService(models.Model):
    """Services or products offered by a provider, with pricing."""

    PRICING_MODEL_CHOICES = [
        ('fixed',       'Fixed Price'),
        ('per_unit',    'Per Unit'),
        ('per_ha',      'Per Hectare'),
        ('per_head',    'Per Head'),
        ('per_hour',    'Per Hour'),
        ('per_day',     'Per Day'),
        ('per_km',      'Per km'),
        ('negotiable',  'Negotiable / Quote'),
        ('free',        'Free'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='services')
    name            = models.CharField(max_length=255)
    description     = models.TextField(blank=True)
    category        = models.CharField(max_length=100, blank=True)
    pricing_model   = models.CharField(max_length=20, choices=PRICING_MODEL_CHOICES, default='negotiable')
    price           = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_max       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text='Upper bound for price ranges')
    currency        = models.CharField(max_length=10, default='ZMW')
    unit_label      = models.CharField(max_length=50, blank=True, help_text='e.g. "50kg bag", "per animal"')
    is_available    = models.BooleanField(default=True)
    lead_time_days  = models.PositiveSmallIntegerField(default=0, help_text='Typical lead time')
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'provider_services'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} — {self.provider.name}'


class ProviderCertification(models.Model):
    """Regulatory certifications, licences, and accreditations held by a provider."""

    STATUS_CHOICES = [
        ('valid',   'Valid'),
        ('expired', 'Expired'),
        ('pending', 'Pending Renewal'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='certifications')
    name            = models.CharField(max_length=255, help_text='e.g. SCCI Registered Dealer')
    issuing_body    = models.CharField(max_length=255, blank=True, help_text='e.g. SCCI, ZABS, ZEMA, HPCZ')
    cert_number     = models.CharField(max_length=100, blank=True)
    issued_date     = models.DateField(null=True, blank=True)
    expiry_date     = models.DateField(null=True, blank=True)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='valid')
    document_url    = models.CharField(max_length=500, blank=True)
    verified        = models.BooleanField(default=False, help_text='Platform admin has verified this cert')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'provider_certifications'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} — {self.provider.name}'


class ProviderReview(models.Model):
    """Farm review of a provider after a service interaction."""

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='reviews')
    organization    = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='provider_reviews')
    reviewed_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='provider_reviews'
    )
    rating          = models.PositiveSmallIntegerField(help_text='1–5')
    title           = models.CharField(max_length=255, blank=True)
    body            = models.TextField(blank=True)
    service_used    = models.CharField(max_length=255, blank=True)
    verified_purchase = models.BooleanField(default=False, help_text='Linked to a confirmed booking')
    helpful_votes   = models.PositiveIntegerField(default=0)
    approved        = models.BooleanField(default=False)
    approved_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'provider_reviews'
        ordering = ['-created_at']
        unique_together = [('provider', 'organization')]  # one review per org per provider

    def save(self, *args, **kwargs):
        if self.rating < 1: self.rating = 1
        if self.rating > 5: self.rating = 5
        super().save(*args, **kwargs)
        self.provider.update_rating()

    def __str__(self):
        return f'{self.rating}★ — {self.provider.name} by {self.organization}'


# ──────────────────────────────────────────────────────────────────────────────
# Equipment Hire specific models
# ──────────────────────────────────────────────────────────────────────────────

class EquipmentCatalog(models.Model):
    """Individual equipment item available for hire from an equipment_hire provider."""

    EQUIPMENT_TYPE_CHOICES = [
        ('tractor',         'Tractor'),
        ('plough',          'Plough / Ridger'),
        ('planter',         'Planter'),
        ('harvester',       'Combine Harvester'),
        ('sprayer',         'Sprayer'),
        ('drone',           'Agricultural Drone'),
        ('irrigation',      'Irrigation System / Centre Pivot'),
        ('truck',           'Truck / Transport'),
        ('generator',       'Generator'),
        ('storage',         'Storage Equipment'),
        ('processing',      'Processing Equipment'),
        ('other',           'Other'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='equipment')
    equipment_type  = models.CharField(max_length=20, choices=EQUIPMENT_TYPE_CHOICES)
    name            = models.CharField(max_length=255)
    make            = models.CharField(max_length=100, blank=True)
    model           = models.CharField(max_length=100, blank=True)
    year            = models.PositiveSmallIntegerField(null=True, blank=True)
    capacity        = models.CharField(max_length=100, blank=True, help_text='e.g. 90HP, 3.5t, 36m wingspan')
    daily_rate      = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    per_ha_rate     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency        = models.CharField(max_length=10, default='ZMW')
    operator_included = models.BooleanField(default=True)
    fuel_included   = models.BooleanField(default=False)
    min_hire_days   = models.PositiveSmallIntegerField(default=1)
    photos          = models.JSONField(default=list)
    specs           = models.JSONField(default=dict, help_text='Additional specs as key-value pairs')
    is_available    = models.BooleanField(default=True)
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'provider_equipment_catalog'
        ordering = ['equipment_type', 'name']

    def __str__(self):
        return f'{self.name} — {self.provider.name}'


class HireBooking(models.Model):
    """Equipment hire booking placed by a farm organisation."""

    STATUS_CHOICES = [
        ('enquiry',   'Enquiry'),
        ('quoted',    'Quote Sent'),
        ('confirmed', 'Confirmed'),
        ('active',    'In Use / On-site'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_ref     = models.CharField(max_length=30, unique=True, blank=True)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='hire_bookings')
    equipment       = models.ForeignKey(EquipmentCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    organization    = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='hire_bookings')
    client_name     = models.CharField(max_length=255, blank=True, help_text='Walk-in customer (no platform account)')
    client_phone    = models.CharField(max_length=50, blank=True)
    enterprise      = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='hire_bookings')
    requested_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='hire_bookings'
    )

    start_date      = models.DateField()
    end_date        = models.DateField()
    hectares        = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='enquiry')
    quoted_amount   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    agreed_amount   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency        = models.CharField(max_length=10, default='ZMW')
    deposit_paid    = models.BooleanField(default=False)
    final_paid      = models.BooleanField(default=False)
    delivery_address = models.TextField(blank=True)
    notes           = models.TextField(blank=True)
    provider_notes  = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'provider_hire_bookings'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.booking_ref:
            import datetime
            yr = datetime.date.today().year
            # count existing refs this year and increment
            count = HireBooking.objects.filter(booking_ref__startswith=f'HB-{yr}-').count()
            self.booking_ref = f'HB-{yr}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.booking_ref} — {self.provider.name}'


# ──────────────────────────────────────────────────────────────────────────────
# Vet Services specific models
# ──────────────────────────────────────────────────────────────────────────────

class VetAppointment(models.Model):
    """Veterinary appointment booked by a farm organisation."""

    TYPE_CHOICES = [
        ('consultation',  'General Consultation'),
        ('vaccination',   'Vaccination'),
        ('treatment',     'Treatment / Procedure'),
        ('diagnosis',     'Diagnosis / Lab'),
        ('deworming',     'Deworming'),
        ('pregnancy',     'Pregnancy Check'),
        ('slaughter_cert','Pre-slaughter Certification'),
        ('teleconsult',   'Teleconsultation (Remote)'),
        ('other',         'Other'),
    ]

    STATUS_CHOICES = [
        ('requested',  'Requested'),
        ('confirmed',  'Confirmed'),
        ('in_progress','In Progress'),
        ('completed',  'Completed'),
        ('no_show',    'No Show'),
        ('cancelled',  'Cancelled'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appt_ref        = models.CharField(max_length=30, unique=True, blank=True)
    provider        = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='vet_appointments')
    organization    = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='vet_appointments')
    client_name     = models.CharField(max_length=255, blank=True, help_text='Walk-in client (no platform account)')
    client_phone    = models.CharField(max_length=50, blank=True)
    enterprise      = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='vet_appointments')
    requested_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vet_appointments'
    )
    vet_officer     = models.ForeignKey(ProviderStaff, on_delete=models.SET_NULL, null=True, blank=True, related_name='appointments')

    appt_type       = models.CharField(max_length=20, choices=TYPE_CHOICES)
    appt_date       = models.DateField()
    appt_time       = models.TimeField(null=True, blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested')

    # Animals
    species         = models.CharField(max_length=100, blank=True, help_text='e.g. Broilers, Tilapia, Cattle')
    animal_count    = models.PositiveIntegerField(default=0)
    symptoms        = models.TextField(blank=True)

    # Outcome
    diagnosis       = models.TextField(blank=True)
    treatment_given = models.TextField(blank=True)
    medications     = models.JSONField(default=list, help_text='[{name, dose, route, days}]')
    follow_up_date  = models.DateField(null=True, blank=True)
    outcome_notes   = models.TextField(blank=True)

    # Billing
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_amount    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency        = models.CharField(max_length=10, default='ZMW')
    paid            = models.BooleanField(default=False)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'provider_vet_appointments'
        ordering = ['-appt_date', '-created_at']

    def save(self, *args, **kwargs):
        if not self.appt_ref:
            import datetime
            yr = datetime.date.today().year
            count = VetAppointment.objects.filter(appt_ref__startswith=f'VA-{yr}-').count()
            self.appt_ref = f'VA-{yr}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.appt_ref} — {self.provider.name} ({self.appt_type})'


from .vendor_models import VendorOrder, WorkOrder, EquipmentMaintenance, ProcessingBatch, VendorInvoice  # noqa: E402,F401
