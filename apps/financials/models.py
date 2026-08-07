import uuid
from django.db import models
from django.conf import settings
from django.db.models import Sum


class BatchFinancials(models.Model):
    """Real-time P&L tracker per production batch."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='batch_financials')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='financials')
    batch_name = models.CharField(max_length=255)
    batch_ref = models.CharField(max_length=100, blank=True, help_text='External batch/cycle reference')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    # Cached totals — updated by CostEntry/RevenueEntry signals
    total_costs = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # Break-even
    break_even_units = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    break_even_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    target_units = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'batch_financials'
        ordering = ['-start_date']

    @property
    def gross_profit(self):
        return float(self.total_revenue) - float(self.total_costs)

    @property
    def profit_margin_pct(self):
        if not self.total_revenue:
            return 0
        return round(self.gross_profit / float(self.total_revenue) * 100, 2)

    @property
    def roi_pct(self):
        if not self.total_costs:
            return 0
        return round(self.gross_profit / float(self.total_costs) * 100, 2)

    def recalculate(self):
        costs = self.cost_entries.aggregate(t=Sum('amount'))['t'] or 0
        revenue = self.revenue_entries.aggregate(t=Sum('amount'))['t'] or 0
        self.total_costs = costs
        self.total_revenue = revenue
        self.save(update_fields=['total_costs', 'total_revenue', 'updated_at'])


class CostEntry(models.Model):
    CATEGORY_CHOICES = [
        ('feed', 'Feed & Nutrition'), ('stock', 'Livestock / Seed Purchase'),
        ('vet', 'Veterinary & Health'), ('labour', 'Labour'),
        ('equipment', 'Equipment & Machinery'), ('fuel', 'Fuel & Energy'),
        ('water', 'Water'), ('packaging', 'Packaging'),
        ('transport', 'Transport & Logistics'), ('marketing', 'Marketing'),
        ('overhead', 'Overheads'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='cost_entries')
    batch_financials = models.ForeignKey(BatchFinancials, on_delete=models.CASCADE, related_name='cost_entries')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    unit = models.CharField(max_length=30, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    entry_date = models.DateField()
    invoice_ref = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cost_entries'
        ordering = ['-entry_date']

    def save(self, *args, **kwargs):
        if self.quantity and self.unit_cost:
            self.amount = float(self.quantity) * float(self.unit_cost)
        super().save(*args, **kwargs)
        self.batch_financials.recalculate()


class RevenueEntry(models.Model):
    CATEGORY_CHOICES = [
        ('sales_live', 'Live Animal Sales'), ('sales_processed', 'Processed Product Sales'),
        ('sales_crop', 'Crop / Produce Sales'), ('milk', 'Milk Sales'), ('eggs', 'Egg Sales'),
        ('wool_hide', 'Wool / Hide'), ('subsidy', 'Government Subsidy / Grant'),
        ('insurance', 'Insurance Payout'), ('carbon_credit', 'Carbon Credits'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='revenue_entries')
    batch_financials = models.ForeignKey(BatchFinancials, on_delete=models.CASCADE, related_name='revenue_entries')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    unit = models.CharField(max_length=30, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    buyer = models.CharField(max_length=255, blank=True)
    entry_date = models.DateField()
    invoice_ref = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'revenue_entries'
        ordering = ['-entry_date']

    def save(self, *args, **kwargs):
        if self.quantity and self.unit_price:
            self.amount = float(self.quantity) * float(self.unit_price)
        super().save(*args, **kwargs)
        self.batch_financials.recalculate()


class BreakEvenAnalysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='breakeven_analyses')
    batch_financials = models.ForeignKey(BatchFinancials, on_delete=models.CASCADE, related_name='breakeven_analyses')
    name = models.CharField(max_length=255)
    # Inputs
    fixed_costs = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    variable_cost_per_unit = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    selling_price_per_unit = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    expected_units = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Computed results (auto on save)
    contribution_margin = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    break_even_units = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    break_even_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    margin_of_safety_units = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    margin_of_safety_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    projected_profit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'breakeven_analyses'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        sp = float(self.selling_price_per_unit)
        vc = float(self.variable_cost_per_unit)
        fc = float(self.fixed_costs)
        units = float(self.expected_units)
        self.contribution_margin = sp - vc
        if self.contribution_margin > 0:
            self.break_even_units = fc / float(self.contribution_margin)
            self.break_even_revenue = float(self.break_even_units) * sp
            self.margin_of_safety_units = units - float(self.break_even_units)
            self.margin_of_safety_pct = (float(self.margin_of_safety_units) / units * 100) if units else 0
            self.projected_profit = (units * sp) - (units * vc) - fc
        super().save(*args, **kwargs)


class LoanApplication(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('under_review', 'Under Review'),
        ('approved', 'Approved'), ('disbursed', 'Disbursed'), ('rejected', 'Rejected'),
        ('repaying', 'Repaying'), ('settled', 'Settled'),
    ]
    LOAN_TYPE_CHOICES = [
        ('seasonal', 'Seasonal / Input Loan'), ('equipment', 'Equipment Finance'),
        ('land', 'Land Purchase'), ('infrastructure', 'Infrastructure'),
        ('working_capital', 'Working Capital'), ('emergency', 'Emergency'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='loan_applications')
    loan_type = models.CharField(max_length=20, choices=LOAN_TYPE_CHOICES, default='seasonal')
    lender_name = models.CharField(max_length=255)
    amount_requested = models.DecimalField(max_digits=16, decimal_places=2)
    amount_approved = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    interest_rate_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    term_months = models.PositiveSmallIntegerField(default=12)
    monthly_repayment = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    purpose = models.TextField()
    collateral = models.TextField(blank=True)
    application_date = models.DateField(null=True, blank=True)
    approval_date = models.DateField(null=True, blank=True)
    disbursement_date = models.DateField(null=True, blank=True)
    repayment_start = models.DateField(null=True, blank=True)
    # AI credit scoring
    ai_credit_score = models.PositiveSmallIntegerField(null=True, blank=True)
    ai_risk_assessment = models.TextField(blank=True)
    ai_recommendation = models.CharField(max_length=50, blank=True)
    documents = models.JSONField(default=list)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'loan_applications'
        ordering = ['-created_at']


class InsuranceClaim(models.Model):
    CLAIM_TYPE_CHOICES = [
        ('crop_loss', 'Crop Loss / Drought'), ('flood', 'Flood Damage'),
        ('fire', 'Fire'), ('livestock_death', 'Livestock Death / Disease'),
        ('equipment', 'Equipment Damage'), ('theft', 'Theft'), ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('under_assessment', 'Under Assessment'),
        ('approved', 'Approved'), ('paid', 'Paid'), ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='insurance_claims')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='insurance_claims')
    claim_type = models.CharField(max_length=20, choices=CLAIM_TYPE_CHOICES)
    insurer_name = models.CharField(max_length=255)
    policy_number = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    estimated_loss = models.DecimalField(max_digits=16, decimal_places=2)
    amount_claimed = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_approved = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    incident_date = models.DateField()
    submission_date = models.DateField(null=True, blank=True)
    assessment_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    # Supporting evidence (satellite, photos, NDVI, sensor data)
    evidence_urls = models.JSONField(default=list)
    ndvi_evidence = models.TextField(blank=True, help_text='NDVI field health data as evidence')
    weather_evidence = models.TextField(blank=True, help_text='Weather station data as evidence')
    assessor_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'insurance_claims'
        ordering = ['-incident_date']
