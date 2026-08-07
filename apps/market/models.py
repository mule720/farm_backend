import uuid
from django.db import models
from django.conf import settings


class CommodityPrice(models.Model):
    UNIT_CHOICES = [
        ('kg', 'per kg'), ('tonne', 'per tonne'), ('head', 'per head'),
        ('litre', 'per litre'), ('bag_50kg', 'per 50 kg bag'), ('crate', 'per crate'), ('each', 'each'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    commodity = models.CharField(max_length=255)
    market_name = models.CharField(max_length=255)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='kg')
    price = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=10, default='ZMW')
    price_date = models.DateField()
    source = models.CharField(max_length=255, blank=True, help_text='FRA, local market, buyer, etc.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'commodity_prices'
        ordering = ['-price_date', 'commodity']

    def __str__(self):
        return f'{self.commodity} @ {self.price} {self.currency}/{self.unit} — {self.price_date}'


class BuyerProfile(models.Model):
    BUYER_TYPE_CHOICES = [
        ('individual', 'Individual'), ('company', 'Company'), ('exporter', 'Exporter'),
        ('processor', 'Processor'), ('restaurant', 'Restaurant / Hospitality'),
        ('supermarket', 'Supermarket'), ('ngo', 'NGO / Aid Organization'), ('government', 'Government'),
    ]
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='buyer_profiles')
    name = models.CharField(max_length=255)
    buyer_type = models.CharField(max_length=20, choices=BUYER_TYPE_CHOICES, default='company')
    contact_person = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    town = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Zambia')
    commodities_wanted = models.JSONField(default=list, help_text='List of commodity names they buy')
    preferred_volume_kg = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_terms = models.CharField(max_length=255, blank=True, help_text='COD, 30 days, etc.')
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'buyer_profiles'
        ordering = ['name']


class MarketListing(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('active', 'Listed / Active'), ('negotiating', 'In Negotiation'),
        ('sold', 'Sold'), ('expired', 'Expired'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='market_listings')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='listings')
    commodity = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity_available = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, default='kg')
    asking_price = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=10, default='ZMW')
    min_order_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    available_from = models.DateField(null=True, blank=True)
    available_until = models.DateField(null=True, blank=True)
    delivery_available = models.BooleanField(default=False)
    location = models.CharField(max_length=255, blank=True)
    photos = models.JSONField(default=list)
    certifications = models.JSONField(default=list)
    views_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_listings'
        ordering = ['-created_at']


class TradeContract(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('offered', 'Offer Sent'), ('accepted', 'Accepted'),
        ('in_progress', 'In Progress'), ('fulfilled', 'Fulfilled'),
        ('disputed', 'Disputed'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='trade_contracts')
    listing = models.ForeignKey(MarketListing, on_delete=models.SET_NULL, null=True, blank=True, related_name='contracts')
    buyer = models.ForeignKey(BuyerProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='contracts')
    commodity = models.CharField(max_length=255)
    quantity_agreed = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, default='kg')
    agreed_price = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=10, default='ZMW')
    total_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    delivery_date = models.DateField(null=True, blank=True)
    delivery_address = models.TextField(blank=True)
    payment_terms = models.TextField(blank=True)
    deposit_pct = models.PositiveSmallIntegerField(default=0)
    deposit_paid = models.BooleanField(default=False)
    final_paid = models.BooleanField(default=False)
    quantity_delivered = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    terms_and_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trade_contracts'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        self.total_value = float(self.quantity_agreed) * float(self.agreed_price)
        super().save(*args, **kwargs)


class AuctionEvent(models.Model):
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'), ('open', 'Open for Bids'),
        ('closed', 'Bidding Closed'), ('sold', 'Sold'), ('unsold', 'Passed In'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='auction_events')
    listing = models.ForeignKey(MarketListing, on_delete=models.CASCADE, related_name='auctions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    reserve_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    current_highest_bid = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    winner_buyer = models.ForeignKey(BuyerProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    winning_bid = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    bids = models.JSONField(default=list, help_text='List of {buyer, amount, timestamp} dicts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auction_events'
        ordering = ['-opens_at']


class ColdChainLog(models.Model):
    STATUS_CHOICES = [
        ('ok', 'Within Range'), ('breach', 'Temperature Breach'), ('warning', 'Near Limit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='cold_chain_logs')
    contract = models.ForeignKey(TradeContract, on_delete=models.SET_NULL, null=True, blank=True, related_name='cold_chain_logs')
    location_name = models.CharField(max_length=255, help_text='Truck, store, depot name')
    commodity = models.CharField(max_length=255)
    temp_min_target = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    temp_max_target = models.DecimalField(max_digits=5, decimal_places=2, default=4)
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2)
    humidity_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ok')
    device_id = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    recorded_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cold_chain_logs'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        t = float(self.temperature_c)
        min_t = float(self.temp_min_target)
        max_t = float(self.temp_max_target)
        if t < min_t or t > max_t:
            self.status = 'breach'
        elif t < min_t + 1 or t > max_t - 1:
            self.status = 'warning'
        else:
            self.status = 'ok'
        super().save(*args, **kwargs)


class ExportDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('phytosanitary', 'Phytosanitary Certificate'), ('packing_list', 'Packing List'),
        ('invoice', 'Commercial Invoice'), ('coo', 'Certificate of Origin'),
        ('health_cert', 'Veterinary Health Certificate'), ('fumigation', 'Fumigation Certificate'),
        ('customs', 'Customs Declaration'), ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved / Issued'), ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='export_documents')
    contract = models.ForeignKey(TradeContract, on_delete=models.SET_NULL, null=True, blank=True, related_name='export_documents')
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES)
    doc_number = models.CharField(max_length=100, blank=True)
    issuing_authority = models.CharField(max_length=255, blank=True)
    commodity = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, blank=True)
    destination_country = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    document_url = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'export_documents'
        ordering = ['-created_at']
