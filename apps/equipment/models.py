import uuid
from django.db import models
from django.conf import settings


class Equipment(models.Model):
    TYPE_CHOICES = [
        ('tractor', 'Tractor'), ('planter', 'Planter'), ('harvester', 'Harvester'),
        ('sprayer', 'Sprayer'), ('truck', 'Truck'), ('generator', 'Generator'),
        ('pump', 'Pump'), ('drone', 'Agricultural Drone'), ('implement', 'Implement'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('operational', 'Operational'), ('in_use', 'In Use'),
        ('maintenance', 'Under Maintenance'), ('repair', 'Needs Repair'),
        ('retired', 'Retired'),
    ]
    AUTONOMOUS_LEVEL_CHOICES = [
        ('manual', 'Manual'), ('assisted', 'Driver Assisted'),
        ('semi_auto', 'Semi-Autonomous'), ('full_auto', 'Fully Autonomous'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='equipment')
    name = models.CharField(max_length=255)
    equipment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='tractor')
    model_number = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    year_manufactured = models.PositiveSmallIntegerField(null=True, blank=True)
    serial_number = models.CharField(max_length=100, blank=True, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='operational')
    autonomous_level = models.CharField(max_length=20, choices=AUTONOMOUS_LEVEL_CHOICES, default='manual')
    purchase_date = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Telemetry / tracking
    device = models.OneToOneField('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment')
    gps_tracker_id = models.CharField(max_length=100, blank=True)
    engine_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    odometer_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fuel_capacity_l = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    current_fuel_pct = models.PositiveSmallIntegerField(default=100)
    # Maintenance
    service_interval_hours = models.PositiveIntegerField(default=250)
    last_service_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    next_service_due = models.DateField(null=True, blank=True)
    current_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'equipment'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_equipment_type_display()})'

    @property
    def hours_until_service(self):
        return max(0, float(self.service_interval_hours) - float(self.engine_hours - self.last_service_hours))

    @property
    def service_due_soon(self):
        return self.hours_until_service < 20


class EquipmentTelemetry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='telemetry')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    heading_degrees = models.PositiveSmallIntegerField(default=0)
    engine_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fuel_pct = models.PositiveSmallIntegerField(default=100)
    rpm = models.PositiveIntegerField(default=0)
    engine_temp_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_engine_on = models.BooleanField(default=False)
    is_autonomous = models.BooleanField(default=False)
    alerts = models.JSONField(default=list)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'equipment_telemetry'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        Equipment.objects.filter(pk=self.equipment_id).update(
            engine_hours=self.engine_hours,
            current_fuel_pct=self.fuel_pct,
            current_latitude=self.latitude,
            current_longitude=self.longitude,
        )


class FieldOperation(models.Model):
    OPERATION_CHOICES = [
        ('ploughing', 'Ploughing'), ('discing', 'Discing'), ('planting', 'Planting'),
        ('spraying', 'Spraying'), ('fertilizing', 'Fertilizing'), ('harvesting', 'Harvesting'),
        ('mowing', 'Mowing'), ('baling', 'Baling'), ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('planned', 'Planned'), ('in_progress', 'In Progress'),
        ('completed', 'Completed'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='field_operations')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='field_operations')
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations')
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='field_operations')
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    field_name = models.CharField(max_length=255, blank=True)
    area_ha = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    scheduled_date = models.DateField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    fuel_used_l = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    hours_spent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gps_track = models.JSONField(default=list, help_text='List of [lat,lng] waypoints')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'field_operations'
        ordering = ['-scheduled_date']


class MaintenanceRecord(models.Model):
    TYPE_CHOICES = [
        ('service', 'Scheduled Service'), ('repair', 'Repair'), ('inspection', 'Inspection'),
        ('tyre', 'Tyre Change'), ('oil', 'Oil Change'), ('filter', 'Filter Replacement'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='maintenance_records')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    maintenance_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='service')
    description = models.TextField()
    technician = models.CharField(max_length=255, blank=True)
    parts_used = models.JSONField(default=list)
    labour_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    engine_hours_at_service = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    service_date = models.DateField()
    next_service_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'maintenance_records'
        ordering = ['-service_date']

    def save(self, *args, **kwargs):
        self.total_cost = self.labour_cost + self.parts_cost
        super().save(*args, **kwargs)
        Equipment.objects.filter(pk=self.equipment_id).update(
            last_service_hours=self.engine_hours_at_service,
            next_service_due=self.next_service_date,
        )


class ImplementAttachment(models.Model):
    ATTACHMENT_CHOICES = [
        ('plough', 'Plough'), ('disc_harrow', 'Disc Harrow'), ('ripper', 'Ripper'),
        ('planter', 'Planter'), ('sprayer_boom', 'Spray Boom'), ('spreader', 'Fertilizer Spreader'),
        ('mower', 'Mower/Slasher'), ('baler', 'Baler'), ('trailer', 'Trailer'),
        ('ridger', 'Ridger'), ('cultivator', 'Cultivator'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='implement_attachments')
    name = models.CharField(max_length=255)
    attachment_type = models.CharField(max_length=20, choices=ATTACHMENT_CHOICES, default='other')
    compatible_equipment = models.ManyToManyField(Equipment, related_name='compatible_implements', blank=True)
    width_m = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    condition = models.CharField(max_length=50, blank=True, help_text='Good, Fair, Poor')
    is_available = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'implement_attachments'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.attachment_type})'


class ImplementUsageLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    implement = models.ForeignKey(ImplementAttachment, on_delete=models.CASCADE, related_name='usage_logs')
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name='implement_usage_logs')
    field_operation = models.ForeignKey(FieldOperation, on_delete=models.SET_NULL, null=True, blank=True, related_name='implement_usage_logs')
    field_name = models.CharField(max_length=255, blank=True)
    area_ha = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hours_used = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'implement_usage_logs'
        ordering = ['-started_at']


class AutonomousTask(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'), ('sent', 'Sent to Equipment'),
        ('executing', 'Executing'), ('completed', 'Completed'),
        ('failed', 'Failed'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='autonomous_tasks')
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='autonomous_tasks')
    operation_type = models.CharField(max_length=100)
    field_name = models.CharField(max_length=255, blank=True)
    field_boundary = models.JSONField(default=list, help_text='GPS polygon for the field')
    path_plan = models.JSONField(default=list, help_text='Generated waypoints')
    speed_kmh = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    overlap_pct = models.PositiveSmallIntegerField(default=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    progress_pct = models.PositiveSmallIntegerField(default=0)
    area_completed_ha = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'autonomous_tasks'
        ordering = ['-scheduled_at']
