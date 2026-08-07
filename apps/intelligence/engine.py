"""
AI Recommendation Engine.

Analyses production records, KPI values, inventory levels and sensor readings
to generate actionable recommendations. Rule-based for now; designed to be
replaced/augmented by an LLM or ML model later.
"""
from django.utils import timezone
from .models import AIRecommendation


def generate_recommendations(organization, enterprise_id=None, batch_id=None, user=None):
    """Generate and persist AI recommendations for the given context."""
    recs = []

    recs += _check_kpis(organization, enterprise_id, batch_id)
    recs += _check_inventory(organization, enterprise_id)
    recs += _check_sensor_alerts(organization, enterprise_id)
    recs += _check_overdue_tasks(organization, enterprise_id)
    recs += _check_mortality(organization, enterprise_id, batch_id)

    saved = []
    for rec_data in recs:
        rec = AIRecommendation.objects.create(
            organization=organization,
            enterprise_id=enterprise_id,
            batch_id=batch_id,
            model_version='rules-v1',
            **rec_data,
        )
        saved.append(rec)

    return saved


def _check_kpis(organization, enterprise_id, batch_id):
    from apps.kpis.models import KPIDefinition
    recs = []
    qs = KPIDefinition.objects.filter(organization=organization, is_active=True)
    if enterprise_id:
        qs = qs.filter(enterprise_id=enterprise_id)

    for kpi in qs:
        latest = kpi.values.first()
        if not latest:
            continue
        val = float(latest.value)

        if kpi.critical_threshold:
            c = float(kpi.critical_threshold)
            breached = (kpi.higher_is_better and val <= c) or (not kpi.higher_is_better and val >= c)
            if breached:
                recs.append({
                    'title': f'CRITICAL: {kpi.name} at {val:.2f} {kpi.unit}',
                    'detail': (
                        f'{kpi.name} has breached the critical threshold of {c} {kpi.unit}. '
                        f'Immediate action required to prevent production losses.'
                    ),
                    'recommendation_type': 'alert',
                    'urgency': 'critical',
                    'impact': f'Production loss risk if {kpi.name} is not corrected within 24 hours.',
                    'data_sources': ['kpi_values'],
                })
                continue

        if kpi.warning_threshold:
            w = float(kpi.warning_threshold)
            warned = (kpi.higher_is_better and val <= w) or (not kpi.higher_is_better and val >= w)
            if warned:
                recs.append({
                    'title': f'Warning: {kpi.name} approaching threshold',
                    'detail': (
                        f'{kpi.name} is at {val:.2f} {kpi.unit}, '
                        f'approaching the warning threshold of {w} {kpi.unit}.'
                    ),
                    'recommendation_type': 'operational',
                    'urgency': 'high',
                    'impact': 'Monitor closely and adjust management practices.',
                    'data_sources': ['kpi_values'],
                })

    return recs


def _check_inventory(organization, enterprise_id):
    from apps.inventory.models import InventoryItem
    from django.db.models import F
    recs = []
    low_items = InventoryItem.objects.filter(
        organization=organization,
        current_stock__lte=F('reorder_level'),
    )
    if enterprise_id:
        low_items = low_items.filter(enterprise_id=enterprise_id)

    for item in low_items:
        recs.append({
            'title': f'Low Stock: {item.name}',
            'detail': (
                f'{item.name} stock is at {item.current_stock:.1f} {item.unit}, '
                f'at or below the reorder level of {item.reorder_level:.1f} {item.unit}. '
                f'Place a purchase order to avoid production interruption.'
            ),
            'recommendation_type': 'operational',
            'urgency': 'high' if item.current_stock <= 0 else 'medium',
            'impact': 'Feed shortages directly impact growth rates and FCR.',
            'data_sources': ['inventory'],
        })
    return recs


def _check_sensor_alerts(organization, enterprise_id):
    from apps.devices.models import SensorReading
    recs = []
    alerts = SensorReading.objects.filter(
        organization=organization, is_alert=True
    ).order_by('-recorded_at')[:10]
    if enterprise_id:
        alerts = alerts.filter(enterprise_id=enterprise_id)

    for reading in alerts:
        recs.append({
            'title': f'Sensor Alert: {reading.metric.replace("_", " ").title()} — {reading.device.name}',
            'detail': (
                f'Sensor reading of {reading.value} {reading.unit} '
                f'for {reading.metric} at {reading.device.name} '
                f'has triggered an alert. Check device and environmental conditions.'
            ),
            'recommendation_type': 'alert',
            'urgency': 'critical',
            'impact': 'Abnormal sensor readings may indicate equipment failure or harmful conditions.',
            'data_sources': ['sensor_readings', 'devices'],
        })
    return recs


def _check_overdue_tasks(organization, enterprise_id):
    from apps.automation.models import Task
    recs = []
    overdue = Task.objects.filter(
        organization=organization,
        status__in=['pending', 'in_progress'],
        due_date__lt=timezone.now().date(),
    )
    if enterprise_id:
        overdue = overdue.filter(enterprise_id=enterprise_id)

    count = overdue.count()
    if count > 0:
        recs.append({
            'title': f'{count} Overdue Task{"s" if count > 1 else ""}',
            'detail': (
                f'There {"are" if count > 1 else "is"} {count} overdue '
                f'task{"s" if count > 1 else ""} that require attention. '
                f'Review the task list and reassign if necessary.'
            ),
            'recommendation_type': 'operational',
            'urgency': 'medium',
            'impact': 'Overdue tasks may affect operational continuity and compliance.',
            'data_sources': ['tasks'],
        })
    return recs


def _check_mortality(organization, enterprise_id, batch_id):
    from apps.production.models import ProductionRecord
    recs = []
    qs = ProductionRecord.objects.filter(
        organization=organization, record_type='mortality'
    ).order_by('-record_date')[:7]
    if enterprise_id:
        qs = qs.filter(enterprise_id=enterprise_id)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    total_mortality = 0
    for rec in qs:
        try:
            total_mortality += float(rec.data.get('mortality_count', 0))
        except (ValueError, TypeError):
            pass

    if total_mortality > 0:
        recs.append({
            'title': f'Mortality Report: {total_mortality:.0f} units in last 7 days',
            'detail': (
                f'A total of {total_mortality:.0f} units have died in the past 7 days. '
                f'Review housing conditions, feed quality, disease history, and veterinary records. '
                f'Consider calling a vet if the rate continues.'
            ),
            'recommendation_type': 'health',
            'urgency': 'high' if total_mortality > 50 else 'medium',
            'impact': 'High mortality reduces batch profitability and may indicate disease outbreak.',
            'data_sources': ['production_records'],
        })
    return recs
