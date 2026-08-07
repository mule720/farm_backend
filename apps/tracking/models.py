import uuid
from django.db import models
from django.conf import settings


class AnimalRecord(models.Model):
    SEX_CHOICES = [('male', 'Male'), ('female', 'Female'), ('castrated', 'Castrated Male')]
    STATUS_CHOICES = [
        ('active', 'Active'), ('sold', 'Sold'), ('deceased', 'Deceased'),
        ('culled', 'Culled'), ('transferred', 'Transferred'),
    ]
    SPECIES_CHOICES = [
        ('cattle', 'Cattle'), ('sheep', 'Sheep'), ('goat', 'Goat'), ('pig', 'Pig'),
        ('chicken', 'Chicken'), ('duck', 'Duck'), ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='animal_records')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='animal_records')
    # Identification
    tag_number = models.CharField(max_length=100)
    rfid_tag = models.CharField(max_length=100, blank=True, db_index=True)
    name = models.CharField(max_length=100, blank=True)
    species = models.CharField(max_length=20, choices=SPECIES_CHOICES, default='cattle')
    breed = models.CharField(max_length=100, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, default='female')
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_acquisition = models.DateField(null=True, blank=True)
    acquisition_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    # Physical
    current_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    target_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    color = models.CharField(max_length=100, blank=True)
    markings = models.TextField(blank=True)
    # Reproduction
    is_pregnant = models.BooleanField(default=False)
    expected_delivery = models.DateField(null=True, blank=True)
    dam_tag = models.CharField(max_length=100, blank=True, help_text='Mother tag number')
    sire_tag = models.CharField(max_length=100, blank=True, help_text='Father tag number')
    # Location
    current_pen = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    photo_url = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'animal_records'
        ordering = ['tag_number']
        unique_together = [('organization', 'tag_number')]

    def __str__(self):
        return f'{self.tag_number} ({self.species})'


class AnimalWeightEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    animal = models.ForeignKey(AnimalRecord, on_delete=models.CASCADE, related_name='weight_events')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2)
    previous_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    gain_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    days_since_last = models.PositiveIntegerField(null=True, blank=True)
    adg_kg = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, help_text='Average daily gain')
    weighed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    weigh_date = models.DateField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'animal_weight_events'
        ordering = ['-weigh_date']

    def save(self, *args, **kwargs):
        if self.previous_weight_kg:
            self.gain_kg = self.weight_kg - self.previous_weight_kg
            if self.days_since_last and self.days_since_last > 0:
                self.adg_kg = self.gain_kg / self.days_since_last
        super().save(*args, **kwargs)
        AnimalRecord.objects.filter(pk=self.animal_id).update(current_weight_kg=self.weight_kg)


class AnimalHealthEvent(models.Model):
    EVENT_CHOICES = [
        ('vaccination', 'Vaccination'), ('treatment', 'Treatment'), ('deworming', 'Deworming'),
        ('diagnosis', 'Diagnosis'), ('injury', 'Injury'), ('surgery', 'Surgery'),
        ('checkup', 'Routine Checkup'), ('quarantine', 'Quarantine'), ('death', 'Death'),
    ]
    SEVERITY_CHOICES = [
        ('none', 'None / Routine'), ('mild', 'Mild'), ('moderate', 'Moderate'),
        ('severe', 'Severe'), ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    animal = models.ForeignKey(AnimalRecord, on_delete=models.CASCADE, related_name='health_events')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='none')
    diagnosis = models.CharField(max_length=255, blank=True)
    treatment = models.TextField(blank=True)
    medication = models.CharField(max_length=255, blank=True)
    dosage = models.CharField(max_length=100, blank=True)
    withholding_days = models.PositiveSmallIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vet_name = models.CharField(max_length=255, blank=True)
    event_date = models.DateField()
    follow_up_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'animal_health_events'
        ordering = ['-event_date']


class HeatEvent(models.Model):
    STATUS_CHOICES = [
        ('detected', 'Detected'), ('served', 'Served / Mated'),
        ('confirmed_pregnant', 'Confirmed Pregnant'), ('not_pregnant', 'Not In Calf'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    animal = models.ForeignKey(AnimalRecord, on_delete=models.CASCADE, related_name='heat_events')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    detected_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='detected')
    detection_method = models.CharField(max_length=100, blank=True, help_text='RFID pedometer / visual / hormonal')
    sire_used = models.CharField(max_length=255, blank=True)
    service_date = models.DateField(null=True, blank=True)
    expected_calving = models.DateField(null=True, blank=True)
    is_ai = models.BooleanField(default=False, help_text='Artificial insemination')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'heat_events'
        ordering = ['-detected_at']

    def save(self, *args, **kwargs):
        if self.status == 'confirmed_pregnant' and self.expected_calving:
            AnimalRecord.objects.filter(pk=self.animal_id).update(
                is_pregnant=True, expected_delivery=self.expected_calving
            )
        super().save(*args, **kwargs)


class FeedingRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    animal = models.ForeignKey(AnimalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='feeding_records')
    pen = models.CharField(max_length=100, blank=True, help_text='Pen/group if not per-animal')
    feed_type = models.CharField(max_length=255)
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3)
    cost_per_kg = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    dispensed_by = models.CharField(max_length=100, blank=True, help_text='Smart feeder ID or worker name')
    feed_date = models.DateField()
    feed_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'feeding_records'
        ordering = ['-feed_date', '-feed_time']

    def save(self, *args, **kwargs):
        self.total_cost = float(self.quantity_kg) * float(self.cost_per_kg)
        super().save(*args, **kwargs)


class SmartFeeder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='smart_feeders')
    name = models.CharField(max_length=255)
    pen = models.CharField(max_length=100, blank=True)
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='smart_feeders')
    device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='smart_feeders')
    capacity_kg = models.DecimalField(max_digits=8, decimal_places=2, default=50)
    current_level_pct = models.PositiveSmallIntegerField(default=100)
    low_level_alert_pct = models.PositiveSmallIntegerField(default=20)
    ration_per_dispense_kg = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    dispense_times = models.JSONField(default=list, help_text='["06:00","12:00","18:00"]')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'smart_feeders'
        ordering = ['name']

    def __str__(self):
        return self.name


class FeederDispenseEvent(models.Model):
    TRIGGER_CHOICES = [
        ('scheduled', 'Scheduled'), ('manual', 'Manual'), ('appetite_low', 'Low Appetite Alert'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    feeder = models.ForeignKey(SmartFeeder, on_delete=models.CASCADE, related_name='dispense_events')
    quantity_kg = models.DecimalField(max_digits=8, decimal_places=3)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='scheduled')
    level_before_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    level_after_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    consumption_kg = models.DecimalField(max_digits=8, decimal_places=3, default=0, help_text='Measured since last dispense')
    is_appetite_alert = models.BooleanField(default=False)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'feeder_dispense_events'
        ordering = ['-dispensed_at']


class CoopDoor(models.Model):
    CONTROL_MODE_CHOICES = [
        ('schedule', 'Time Schedule'), ('light', 'Light Sensor'), ('manual', 'Manual Only'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='coop_doors')
    name = models.CharField(max_length=255)
    pen = models.CharField(max_length=100, blank=True)
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='coop_doors')
    device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True, related_name='coop_doors')
    control_mode = models.CharField(max_length=20, choices=CONTROL_MODE_CHOICES, default='schedule')
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    open_light_lux = models.PositiveIntegerField(default=500, help_text='Open when light > this value')
    close_light_lux = models.PositiveIntegerField(default=100, help_text='Close when light < this value')
    is_open = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coop_doors'
        ordering = ['name']


class CoopDoorEvent(models.Model):
    ACTION_CHOICES = [('opened', 'Opened'), ('closed', 'Closed'), ('fault', 'Fault')]
    TRIGGER_CHOICES = [
        ('schedule', 'Schedule'), ('light_sensor', 'Light Sensor'),
        ('manual', 'Manual'), ('system', 'System Override'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    door = models.ForeignKey(CoopDoor, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='schedule')
    light_level_lux = models.PositiveIntegerField(null=True, blank=True)
    fault_description = models.CharField(max_length=255, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coop_door_events'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.action in ('opened', 'closed'):
            CoopDoor.objects.filter(pk=self.door_id).update(is_open=(self.action == 'opened'))
