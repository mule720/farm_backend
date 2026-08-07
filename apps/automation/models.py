import uuid
from django.db import models
from django.conf import settings


class AutomationRule(models.Model):
    OPERATOR_CHOICES = [
        ('gt', 'Greater than'), ('lt', 'Less than'), ('gte', 'Greater or equal'),
        ('lte', 'Less or equal'), ('eq', 'Equal'), ('neq', 'Not equal'),
    ]
    ACTION_CHOICES = [
        ('alert', 'Alert'), ('task', 'Create Task'),
        ('notification', 'Notification'), ('escalate', 'Escalate'),
        ('record', 'Auto-record'),
    ]
    CHANNEL_CHOICES = [
        ('in_app', 'In-App'), ('sms', 'SMS'), ('email', 'Email'), ('push', 'Push'),
    ]
    PRIORITY_CHOICES = [
        ('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='automation_rules'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='automation_rules'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)

    condition_metric = models.CharField(max_length=100)
    condition_operator = models.CharField(max_length=10, choices=OPERATOR_CHOICES)
    condition_value = models.DecimalField(max_digits=12, decimal_places=4)

    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES)
    action_message = models.TextField()
    action_assign_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_rules'
    )
    action_channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='in_app')
    action_priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='warning')

    cooldown_minutes = models.PositiveIntegerField(default=60)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    trigger_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'automation_rules'
        ordering = ['-action_priority', 'name']

    def __str__(self):
        return self.name


class AutomationTriggerLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='+'
    )
    rule = models.ForeignKey(
        AutomationRule, on_delete=models.CASCADE, related_name='trigger_logs'
    )
    triggered_at = models.DateTimeField(auto_now_add=True)
    triggered_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    action_taken = models.TextField(blank=True)
    notified_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'automation_trigger_log'
        ordering = ['-triggered_at']

    def __str__(self):
        return f'{self.rule.name} @ {self.triggered_at}'


class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('in_progress', 'In Progress'),
        ('done', 'Done'), ('cancelled', 'Cancelled'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical'),
    ]
    SOURCE_CHOICES = [('manual', 'Manual'), ('automation', 'Automation')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='tasks'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks'
    )
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    automation_rule = models.ForeignKey(
        AutomationRule, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='generated_tasks'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        ordering = ['-priority', 'due_date']

    def __str__(self):
        return self.title
