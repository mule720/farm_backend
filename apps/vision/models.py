import uuid
from django.db import models
from django.conf import settings


class AIVisionAnalysis(models.Model):
    """Stores the result of an AI image analysis — crop, livestock, drone, or stock count."""

    ANALYSIS_TYPE_CHOICES = [
        ('crop_disease', 'Crop Disease Detection'),
        ('pest_identification', 'Pest Identification'),
        ('livestock_health', 'Livestock Health Assessment'),
        ('livestock_count', 'Livestock Count'),
        ('field_survey', 'Field Survey / NDVI'),
        ('weed_detection', 'Weed Detection'),
        ('soil_assessment', 'Soil Assessment'),
        ('general', 'General Farm Analysis'),
    ]
    SEVERITY_CHOICES = [
        ('none', 'None / Healthy'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='vision_analyses'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vision_analyses'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vision_analyses'
    )
    analysis_type = models.CharField(max_length=30, choices=ANALYSIS_TYPE_CHOICES)
    image_url = models.TextField(blank=True)
    # Farmer's own description of what they see / the problem
    user_description = models.TextField(blank=True)
    # Structured AI findings
    diagnosis = models.CharField(max_length=500, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='none')
    confidence_pct = models.PositiveSmallIntegerField(default=0)
    # JSON list of finding objects: [{title, detail}]
    findings = models.JSONField(default=list)
    # JSON list of action strings
    recommendations = models.JSONField(default=list)
    # Raw AI text response for display
    ai_summary = models.TextField(blank=True)
    # Extra structured data (count results, nutrient deficiencies, etc.)
    extra_data = models.JSONField(default=dict)
    # Community sharing
    is_public = models.BooleanField(default=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vision_analyses'
    )
    ai_model_used = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vision_analyses'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.analysis_type} — {self.diagnosis or "pending"} ({self.created_at.date()})'


class StockCountLog(models.Model):
    """
    Records from camera-based or manual livestock counts.
    Compared against the batch's recorded quantity to detect
    unauthorized stock movements.
    """
    STATUS_CHOICES = [
        ('ok', 'OK — within tolerance'),
        ('discrepancy', 'Discrepancy — no sales order'),
        ('authorized', 'Authorized movement'),
        ('under_review', 'Under Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='stock_count_logs'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='stock_count_logs'
    )
    batch = models.ForeignKey(
        'enterprises.EnterpriseBatch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_count_logs'
    )
    device = models.ForeignKey(
        'devices.Device', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_count_logs'
    )
    # Camera-detected or manually entered count
    counted_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    # Expected quantity from the batch records
    expected_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    # Difference: expected - counted (positive = missing animals)
    discrepancy = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discrepancy_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ok')
    # If True, there was a matching sales/transfer authorization
    is_authorized = models.BooleanField(default=False)
    authorization_ref = models.CharField(max_length=255, blank=True)
    snapshot_url = models.TextField(blank=True)
    vision_analysis = models.ForeignKey(
        AIVisionAnalysis, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_count_logs'
    )
    notes = models.TextField(blank=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_counts'
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_stock_counts'
    )
    counted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'stock_count_logs'
        ordering = ['-counted_at']

    def save(self, *args, **kwargs):
        self.discrepancy = self.expected_quantity - self.counted_quantity
        if self.expected_quantity > 0:
            self.discrepancy_pct = (self.discrepancy / self.expected_quantity) * 100
        else:
            self.discrepancy_pct = 0
        # Flag if >3% missing and not authorized
        if self.discrepancy_pct > 3 and not self.is_authorized:
            self.status = 'discrepancy'
        elif self.is_authorized:
            self.status = 'authorized'
        else:
            self.status = 'ok'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Count {self.counted_quantity}/{self.expected_quantity} — {self.status}'


class FarmerReport(models.Model):
    """
    Community intelligence: farmer-submitted photo + AI analysis,
    optionally shared across the platform for cross-farm learning.
    """
    CATEGORY_CHOICES = [
        ('crop_disease', 'Crop Disease'),
        ('pest', 'Pest / Insect'),
        ('animal_disease', 'Animal Disease'),
        ('nutritional', 'Nutritional Deficiency'),
        ('yield_issue', 'Yield Problem'),
        ('weed', 'Weed / Invasive'),
        ('soil', 'Soil Issue'),
        ('water', 'Water / Irrigation Issue'),
        ('equipment', 'Equipment Problem'),
        ('success', 'Success / Best Practice'),
        ('other', 'Other'),
    ]
    VISIBILITY_CHOICES = [
        ('private', 'Private'),
        ('community', 'Community'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='farmer_reports'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='farmer_reports'
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    crop_or_animal = models.CharField(max_length=100, blank=True)
    location_hint = models.CharField(max_length=255, blank=True)
    image_url = models.TextField(blank=True)
    vision_analysis = models.OneToOneField(
        AIVisionAnalysis, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='farmer_report'
    )
    is_resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='private')
    helpful_count = models.PositiveIntegerField(default=0)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='farmer_reports'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'farmer_reports'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.category} — {self.title}'


class DroneFieldReport(models.Model):
    """
    Structured analysis result from a drone survey flight.
    Links a DroneFlight to AI-analysed field health findings.
    """
    HEALTH_CHOICES = [
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='drone_field_reports'
    )
    flight = models.OneToOneField(
        'devices.DroneFlight', on_delete=models.CASCADE, related_name='field_report'
    )
    enterprise = models.ForeignKey(
        'enterprises.Enterprise', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='drone_field_reports'
    )
    overall_health = models.CharField(max_length=20, choices=HEALTH_CHOICES, default='good')
    health_score = models.PositiveSmallIntegerField(default=75)
    # Zone-level breakdown: [{zone, health_pct, issue, area_ha}]
    zones = models.JSONField(default=list)
    # Detected issues: [{type, severity, area_ha, recommended_action}]
    detected_issues = models.JSONField(default=list)
    # Recommended actions list
    action_plan = models.JSONField(default=list)
    estimated_yield_impact_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    ai_summary = models.TextField(blank=True)
    vision_analysis = models.ForeignKey(
        AIVisionAnalysis, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='drone_field_reports'
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'drone_field_reports'
        ordering = ['-generated_at']

    def __str__(self):
        return f'Field Report — {self.enterprise} — {self.overall_health}'
