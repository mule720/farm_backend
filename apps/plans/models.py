import uuid
from django.db import models
from django.conf import settings
from django.db.models import Sum


class Plan(models.Model):
    TYPE_CHOICES = [
        ('enterprise_plan', 'Enterprise Plan'),
        ('daily_plan', 'Daily Plan'),
        ('marketing_plan', 'Marketing Plan'),
        ('budget_plan', 'Budget Plan'),
        ('seasonal_plan', 'Seasonal Plan'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='plans'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='plans'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='plans'
    )
    plan_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # If True, this plan can be used to initiate a new enterprise/batch
    initiate_product = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_plans'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_plans'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plans'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.get_plan_type_display()})'

    @property
    def estimated_total_cost(self):
        agg = self.budget_items.aggregate(total=Sum('total_cost'))
        return agg['total'] or 0

    @property
    def actual_total_cost(self):
        agg = self.budget_items.aggregate(total=Sum('actual_cost'))
        return agg['total'] or 0


class PlanBudgetItem(models.Model):
    CATEGORY_CHOICES = [
        ('labor', 'Labor'),
        ('materials', 'Materials'),
        ('equipment', 'Equipment / Tools'),
        ('seeds_livestock', 'Seeds / Livestock'),
        ('feeds', 'Feeds'),
        ('chemicals', 'Chemicals / Pesticides'),
        ('transport', 'Transport'),
        ('marketing', 'Marketing'),
        ('utilities', 'Utilities'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='budget_items')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    item_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit = models.CharField(max_length=50, default='unit')
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'plan_budget_items'
        ordering = ['category', 'item_name']

    def save(self, *args, **kwargs):
        self.total_cost = self.quantity * self.unit_cost
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.item_name} — {self.plan.title}'


class DailyPlan(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='daily_plans'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='daily_plans'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='daily_plans'
    )
    plan_date = models.DateField()
    title = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='supervised_daily_plans'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_daily_plans'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_plans'
        ordering = ['-plan_date', '-created_at']
        unique_together = [('organization', 'enterprise', 'plan_date')]

    def __str__(self):
        return f'{self.enterprise.name if self.enterprise else "General"} — {self.plan_date}'

    @property
    def estimated_cost(self):
        agg = self.tasks.aggregate(total=Sum('estimated_cost'))
        return agg['total'] or 0

    @property
    def completion_rate(self):
        total = self.tasks.count()
        if total == 0:
            return 0
        done = self.tasks.filter(status='done').count()
        return round((done / total) * 100)


DAILY_TASK_TYPES = [
    ('feeding', 'Feeding'),
    ('health_check', 'Health Check'),
    ('harvest', 'Harvesting'),
    ('irrigation', 'Irrigation'),
    ('spraying', 'Spraying / Chemicals'),
    ('weeding', 'Weeding'),
    ('pruning', 'Pruning'),
    ('planting', 'Planting / Transplanting'),
    ('record_keeping', 'Record Keeping'),
    ('cleaning', 'Cleaning / Sanitation'),
    ('equipment', 'Equipment Maintenance'),
    ('transport', 'Transport / Delivery'),
    ('marketing', 'Marketing / Sales'),
    ('other', 'Other'),
]


class DailyPlanTask(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('skipped', 'Skipped'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    daily_plan = models.ForeignKey(DailyPlan, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=255)
    task_type = models.CharField(max_length=30, choices=DAILY_TASK_TYPES, default='other')
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='daily_tasks'
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    estimated_duration_hours = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    completion_notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_plan_tasks'
        ordering = ['sort_order', 'priority']

    def __str__(self):
        return f'{self.title} — {self.daily_plan.plan_date}'


class MarketingPlan(models.Model):
    CHANNEL_CHOICES = [
        ('social_media', 'Social Media'),
        ('local_market', 'Local Market'),
        ('wholesale', 'Wholesale / Buyer'),
        ('retail', 'Retail'),
        ('export', 'Export'),
        ('direct_sale', 'Direct Sale'),
        ('online', 'Online Platform'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.OneToOneField(Plan, on_delete=models.CASCADE, related_name='marketing_detail')
    target_market = models.CharField(max_length=255, blank=True)
    target_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_unit = models.CharField(max_length=50, default='kg')
    expected_unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    channels = models.JSONField(default=list)
    key_activities = models.JSONField(default=list)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_plans'

    def __str__(self):
        return f'Marketing: {self.plan.title}'
