"""Copy the legacy Programme.indicators JSON list into Indicator rows and link
existing readings to them."""
from django.db import migrations


def forwards(apps, schema_editor):
    Programme = apps.get_model('partners', 'Programme')
    Indicator = apps.get_model('partners', 'Indicator')
    IndicatorReading = apps.get_model('partners', 'IndicatorReading')
    for p in Programme.objects.all():
        seen = set()
        for order, ind in enumerate(p.indicators or []):
            key = (ind.get('key') or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            obj, _ = Indicator.objects.get_or_create(
                programme=p, key=key,
                defaults=dict(label=ind.get('label') or key, unit=ind.get('unit') or '',
                              target=ind.get('target'), order=order))
            IndicatorReading.objects.filter(programme=p, indicator_key=key, indicator__isnull=True).update(indicator=obj)


class Migration(migrations.Migration):
    dependencies = [('partners', '0003_indicatorreading_disaggregation_indicator_and_more')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
