"""Report exporters: PDF, Excel, CSV."""
import csv
import io
import os
from django.conf import settings
from django.utils import timezone


def build_report(report) -> str:
    """
    Build report file, save to MEDIA_ROOT/reports/, return relative URL.
    """
    reports_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    data = _collect_data(report)

    if report.output_format == 'csv':
        file_path = _export_csv(report, data, reports_dir)
    elif report.output_format == 'excel':
        file_path = _export_excel(report, data, reports_dir)
    else:
        file_path = _export_pdf(report, data, reports_dir)

    filename = os.path.basename(file_path)
    return f'{settings.MEDIA_URL}reports/{filename}'


def _collect_data(report):
    """Fetch data for the report based on type and parameters."""
    org = report.organization
    date_from = report.date_from
    date_to = report.date_to or timezone.now().date()
    enterprise_id = report.enterprise_id

    if report.report_type == 'production':
        from apps.production.models import ProductionRecord
        qs = ProductionRecord.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if date_from:
            qs = qs.filter(record_date__gte=date_from)
        qs = qs.filter(record_date__lte=date_to)
        return [
            {
                'date': str(r.record_date),
                'enterprise': r.enterprise.name,
                'batch': r.batch.name if r.batch else '',
                'type': r.record_type,
                **{k: str(v) for k, v in (r.data or {}).items()},
            }
            for r in qs.select_related('enterprise', 'batch')
        ]

    elif report.report_type == 'inventory':
        from apps.inventory.models import InventoryItem
        qs = InventoryItem.objects.filter(organization=org)
        return [
            {
                'name': i.name, 'category': i.category, 'unit': i.unit,
                'current_stock': str(i.current_stock),
                'reorder_level': str(i.reorder_level),
                'unit_cost': str(i.unit_cost or ''),
                'supplier': i.supplier,
                'low_stock': 'Yes' if i.is_low_stock else 'No',
            }
            for i in qs
        ]

    elif report.report_type == 'health':
        from apps.kpis.models import KPIValue
        qs = KPIValue.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if date_from:
            qs = qs.filter(recorded_at__date__gte=date_from)
        return [
            {
                'kpi': v.kpi.name, 'value': str(v.value),
                'unit': v.kpi.unit, 'source': v.source,
                'date': str(v.recorded_at.date()),
            }
            for v in qs.select_related('kpi')[:500]
        ]

    return []


def _export_csv(report, data, directory) -> str:
    if not data:
        data = [{'message': 'No data available for this report.'}]
    filename = f'report_{report.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}.csv'
    path = os.path.join(directory, filename)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    return path


def _export_excel(report, data, directory) -> str:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = report.report_type.capitalize()

    if data:
        headers = list(data[0].keys())
        ws.append(headers)
        for row in data:
            ws.append([row.get(h, '') for h in headers])
    else:
        ws.append(['No data available'])

    # Auto-width columns
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    filename = f'report_{report.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}.xlsx'
    path = os.path.join(directory, filename)
    wb.save(path)
    return path


def _export_pdf(report, data, directory) -> str:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    filename = f'report_{report.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}.pdf'
    path = os.path.join(directory, filename)

    doc = SimpleDocTemplate(path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f'AgroNexus — {report.name}', styles['Title']))
    story.append(Paragraph(
        f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M")} | '
        f'Period: {report.date_from or "All time"} to {report.date_to or "Today"}',
        styles['Normal'],
    ))
    story.append(Spacer(1, 12))

    if data:
        headers = list(data[0].keys())
        table_data = [headers] + [[str(row.get(h, '')) for h in headers] for row in data[:200]]
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2D5016')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7F4')]),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#D1D5DB')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
    else:
        story.append(Paragraph('No data available for this report.', styles['Normal']))

    doc.build(story)
    return path
