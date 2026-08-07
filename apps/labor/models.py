import uuid
from django.db import models
from django.conf import settings
from django.db.models import Sum, Avg


class WorkerProfile(models.Model):
    CONTRACT_CHOICES = [
        ('permanent', 'Permanent'), ('seasonal', 'Seasonal'),
        ('casual', 'Casual / Daily'), ('contract', 'Fixed Term Contract'),
    ]
    PAY_TYPE_CHOICES = [
        ('hourly', 'Hourly Rate'), ('daily', 'Daily Rate'),
        ('piece_rate', 'Piece Rate'), ('monthly', 'Monthly Salary'), ('mixed', 'Mixed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='worker_profiles')
    profile = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='worker_profile', null=True, blank=True)
    employee_id = models.CharField(max_length=50, blank=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=100, blank=True, help_text='e.g. Poultry, Horticulture, General')
    job_title = models.CharField(max_length=100, blank=True)
    contract_type = models.CharField(max_length=20, choices=CONTRACT_CHOICES, default='casual')
    pay_type = models.CharField(max_length=20, choices=PAY_TYPE_CHOICES, default='daily')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    piece_rate_per_unit = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    piece_rate_unit = models.CharField(max_length=50, blank=True, help_text='e.g. per bird processed, per crate picked')
    # Biometric
    biometric_id = models.CharField(max_length=100, blank=True, help_text='Fingerprint / face ID reference')
    nrc_number = models.CharField(max_length=50, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    bank_account = models.CharField(max_length=100, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    photo_url = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'worker_profiles'
        ordering = ['full_name']
        unique_together = [('organization', 'employee_id')]

    def __str__(self):
        return f'{self.full_name} ({self.employee_id})'


class AttendanceRecord(models.Model):
    METHOD_CHOICES = [
        ('biometric', 'Biometric (Fingerprint/Face)'),
        ('gps', 'GPS Check-in'), ('manual', 'Manual Entry'), ('qr', 'QR Code'),
    ]
    STATUS_CHOICES = [
        ('present', 'Present'), ('absent', 'Absent'),
        ('half_day', 'Half Day'), ('leave', 'On Leave'), ('late', 'Late'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='attendance_records')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    clock_in = models.TimeField(null=True, blank=True)
    clock_out = models.TimeField(null=True, blank=True)
    hours_worked = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='manual')
    clock_in_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    clock_in_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    piece_rate_units = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_records'
        ordering = ['-date', 'worker']
        unique_together = [('organization', 'worker', 'date')]

    def save(self, *args, **kwargs):
        if self.clock_in and self.clock_out:
            from datetime import datetime, date
            ci = datetime.combine(date.today(), self.clock_in)
            co = datetime.combine(date.today(), self.clock_out)
            diff = (co - ci).total_seconds() / 3600
            if diff > 0:
                standard = 8.0
                self.hours_worked = min(diff, standard)
                self.overtime_hours = max(0, diff - standard)
        super().save(*args, **kwargs)


class TaskAssignment(models.Model):
    STATUS_CHOICES = [
        ('assigned', 'Assigned'), ('in_progress', 'In Progress'),
        ('done', 'Completed'), ('overdue', 'Overdue'), ('cancelled', 'Cancelled'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('urgent', 'Urgent'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='task_assignments')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='task_assignments')
    enterprise = models.ForeignKey('enterprises.Enterprise', on_delete=models.SET_NULL, null=True, blank=True, related_name='task_assignments')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    field_name = models.CharField(max_length=255, blank=True)
    target_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    target_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    target_radius_m = models.PositiveIntegerField(default=100, help_text='GPS valid radius in metres')
    assigned_date = models.DateField()
    due_time = models.TimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    quality_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text='1-5 rating by supervisor')
    gps_verified = models.BooleanField(default=False)
    piece_rate_units_completed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'task_assignments'
        ordering = ['-assigned_date', 'priority']


class GPSCheckIn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='gps_checkins')
    task = models.ForeignKey(TaskAssignment, on_delete=models.SET_NULL, null=True, blank=True, related_name='gps_checkins')
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    distance_from_target_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_valid = models.BooleanField(default=True)
    checked_in_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gps_checkins'
        ordering = ['-checked_in_at']


class PayrollRun(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('under_review', 'Under Review'),
        ('approved', 'Approved'), ('paid', 'Paid'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='payroll_runs')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    total_gross = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    worker_count = models.PositiveIntegerField(default=0)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=100, blank=True, help_text='Bank transfer, mobile money, cash')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_runs_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payroll_runs'
        ordering = ['-period_end']

    def recalculate_totals(self):
        agg = self.lines.aggregate(
            gross=Sum('gross_pay'), deductions=Sum('total_deductions'), net=Sum('net_pay')
        )
        self.total_gross = agg['gross'] or 0
        self.total_deductions = agg['deductions'] or 0
        self.total_net = agg['net'] or 0
        self.worker_count = self.lines.count()
        self.save(update_fields=['total_gross', 'total_deductions', 'total_net', 'worker_count', 'updated_at'])


class PayrollLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='lines')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='payroll_lines')
    # Hours
    regular_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    days_worked = models.PositiveSmallIntegerField(default=0)
    days_absent = models.PositiveSmallIntegerField(default=0)
    # Pay components
    base_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    overtime_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    piece_rate_units = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    piece_rate_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Deductions
    napsa_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    nhima_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paye_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payroll_lines'
        unique_together = [('payroll_run', 'worker')]

    def save(self, *args, **kwargs):
        self.gross_pay = (
            float(self.base_pay) + float(self.overtime_pay) +
            float(self.piece_rate_pay) + float(self.bonus)
        )
        self.total_deductions = (
            float(self.napsa_deduction) + float(self.nhima_deduction) +
            float(self.paye_deduction) + float(self.other_deductions)
        )
        self.net_pay = self.gross_pay - self.total_deductions
        super().save(*args, **kwargs)
        self.payroll_run.recalculate_totals()


class PerformanceSummary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='performance_summaries')
    period_start = models.DateField()
    period_end = models.DateField()
    tasks_assigned = models.PositiveIntegerField(default=0)
    tasks_completed = models.PositiveIntegerField(default=0)
    tasks_overdue = models.PositiveIntegerField(default=0)
    avg_quality_score = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    attendance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_hours_worked = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total_piece_rate_units = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    supervisor_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'performance_summaries'
        ordering = ['-period_end']
        unique_together = [('organization', 'worker', 'period_start', 'period_end')]

    @property
    def completion_rate_pct(self):
        if not self.tasks_assigned:
            return 0
        return round(self.tasks_completed / self.tasks_assigned * 100, 1)
