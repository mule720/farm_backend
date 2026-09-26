"""
Donor results report for a programme — PDF (reportlab) and Excel (openpyxl).

Sections: cover (programme, funder, period, partner), summary KPIs, enrolment
by district, results framework (indicator vs target with reading history),
support delivered (by type + ledger), production evidence from enrolled farms,
notices issued, methodology note. Everything is computed from the same
resolvers the dashboard uses so the report never disagrees with the screen.
"""
import os
from collections import defaultdict
from datetime import date

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import Organization
from .models import Programme, ProgrammeEnrollment, ProgrammeSupport, IndicatorReading


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v, d=0):
    return f'{_f(v):,.{d}f}'


def collect_report_data(programme, period_start=None, period_end=None):
    """One dict feeding both renderers."""
    from .schema import _results
    from apps.production.models import ProductionRecord
    from apps.notifications.models import Notification

    ps = period_start or programme.start_date
    pe = period_end or timezone.localdate()
    res = _results(programme)
    enr = list(ProgrammeEnrollment.objects.filter(programme=programme).select_related('farm').order_by('farm__district', 'farm__name'))
    ids = [e.farm_id for e in enr]

    # District rollup
    by_d = defaultdict(lambda: {'farms': 0, 'active': 0, 'records': 0, 'harvest': 0.0, 'support': 0.0})
    for e in enr:
        k = (e.farm.province or 'Unspecified', e.farm.district or 'Unspecified')
        by_d[k]['farms'] += 1
        by_d[k]['active'] += e.status == 'active'
    geo = {e.farm_id: (e.farm.province or 'Unspecified', e.farm.district or 'Unspecified') for e in enr}
    for r in ProductionRecord.objects.filter(organization_id__in=ids, record_date__gte=ps, record_date__lte=pe).values('organization_id', 'record_type', 'data'):
        k = geo[r['organization_id']]
        by_d[k]['records'] += 1
        if r['record_type'] == 'harvest':
            try:
                by_d[k]['harvest'] += float((r['data'] or {}).get('quantity') or 0)
            except (TypeError, ValueError):
                pass
    for r in ProgrammeSupport.objects.filter(programme=programme, delivered_on__gte=ps, delivered_on__lte=pe).values('farm_id').annotate(v=Sum('value')):
        if r['farm_id'] in geo:
            by_d[geo[r['farm_id']]]['support'] += _f(r['v'])
    districts = [{'province': k[0], 'district': k[1], **v} for k, v in sorted(by_d.items())]

    # Support
    support_qs = ProgrammeSupport.objects.filter(programme=programme, delivered_on__gte=ps, delivered_on__lte=pe).select_related('farm').order_by('delivered_on')
    labels = dict(ProgrammeSupport.TYPE_CHOICES)
    by_type = [{'type': labels.get(r['support_type'], r['support_type']), 'events': r['n'], 'farms': r['farms'], 'value': _f(r['v'])}
               for r in support_qs.values('support_type').annotate(n=Count('id'), farms=Count('farm', distinct=True), v=Sum('value')).order_by('-v')]
    ledger = [{'date': s.delivered_on.isoformat(), 'farm': s.farm.name, 'district': s.farm.district, 'type': labels.get(s.support_type, s.support_type),
               'description': s.description, 'qty': f'{_f(s.quantity):g} {s.unit}'.strip(), 'value': _f(s.value), 'currency': s.currency, 'ref': s.reference} for s in support_qs]

    # Indicators with history
    readings = defaultdict(list)
    for r in IndicatorReading.objects.filter(programme=programme).order_by('period', 'created_at'):
        readings[r.indicator_key].append({'period': r.period.isoformat(), 'value': _f(r.value), 'notes': r.notes})
    from .logframe import indicator_status, SEX_LABELS
    indicators = []
    for row in indicator_status(programme):
        ind = row['indicator']
        hist = readings.get(ind.key, [])
        bd = row['breakdown'] or {}
        parts = []
        if 'sex' in bd:
            parts.append(' · '.join(f"{SEX_LABELS.get(k, k)} {v:g}" for k, v in bd['sex'].items()))
        if 'age' in bd:
            parts.append(' · '.join(f"{k.title()} {v:g}" for k, v in bd['age'].items()))
        indicators.append({'key': ind.key, 'label': ind.label, 'unit': ind.unit or '', 'target': row['target'], 'baseline': row['baseline'],
                           'result': (f"{ind.result.code} {ind.result.statement}".strip() if ind.result else ''), 'level': ind.result.level if ind.result else '',
                           'latest': row['value'], 'latest_period': row['period'].isoformat() if row['period'] else None,
                           'progress_pct': row['progress_pct'], 'history': hist, 'auto': bool(ind.auto_source), 'breakdown': ' | '.join(parts)})

    notices = Notification.objects.filter(ref_id=str(programme.id), title__startswith=f'[{programme.name}]').values('title').distinct().count()

    return {
        'programme': programme, 'partner': programme.organization.name, 'period_start': ps, 'period_end': pe, 'generated_at': timezone.now(),
        'results': res, 'enrolled': enr, 'districts': districts, 'support_by_type': by_type, 'ledger': ledger, 'indicators': indicators,
        'notices': notices,
    }


def _out(name):
    d = os.path.join(settings.MEDIA_ROOT, 'reports')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name), f'{settings.MEDIA_URL}reports/{name}'


# ─── PDF ─────────────────────────────────────────────────────────────────────

def build_programme_report_pdf(programme, period_start=None, period_end=None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak, KeepTogether

    d = collect_report_data(programme, period_start, period_end)
    p, r = d['programme'], d['results']
    ss = getSampleStyleSheet()
    green, grey, line, pale = colors.HexColor('#0F2B1A'), colors.HexColor('#6B7280'), colors.HexColor('#D1D5DB'), colors.HexColor('#F5F7F4')
    st = {'title': ParagraphStyle('t', parent=ss['Title'], fontSize=20, textColor=green, alignment=TA_CENTER, spaceAfter=4, leading=24),
          'sub': ParagraphStyle('s', parent=ss['Normal'], fontSize=10, textColor=grey, alignment=TA_CENTER, leading=14),
          'h1': ParagraphStyle('h1', parent=ss['Heading2'], fontSize=13, textColor=green, spaceBefore=12, spaceAfter=4),
          'h2': ParagraphStyle('h2', parent=ss['Heading4'], fontSize=10, textColor=green, spaceBefore=8, spaceAfter=3),
          'n': ParagraphStyle('n', parent=ss['Normal'], fontSize=9, leading=12), 'sm': ParagraphStyle('sm', parent=ss['Normal'], fontSize=7.5, leading=10, textColor=grey),
          'big': ParagraphStyle('big', parent=ss['Normal'], fontSize=18, leading=22, textColor=green), 'lbl': ParagraphStyle('lbl', parent=ss['Normal'], fontSize=7, textColor=grey)}
    name = f'programme_report_{p.id.hex[:8]}_{d["generated_at"]:%Y%m%d%H%M%S}.pdf'
    path, url = _out(name)
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f'{p.name} — Results report', author=d['partner'])
    W = 174 * mm

    def footer(c, doc_):
        c.saveState(); c.setFont('Helvetica', 7); c.setFillColor(grey)
        c.drawString(18 * mm, 10 * mm, f'{p.name} · Results report · generated {d["generated_at"]:%Y-%m-%d %H:%M} from AGRINUXES farm records')
        c.drawRightString(192 * mm, 10 * mm, f'Page {doc_.page}'); c.restoreState()

    def table(rows, widths, head=True, align_right_from=None):
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
        style = [('FONTSIZE', (0, 0), (-1, -1), 8), ('GRID', (0, 0), (-1, -1), 0.25, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                 ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
        if head:
            style += [('BACKGROUND', (0, 0), (-1, 0), green), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                      ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, pale])]
        if align_right_from is not None:
            style.append(('ALIGN', (align_right_from, 1), (-1, -1), 'RIGHT'))
        t.setStyle(TableStyle(style)); return t

    story = []
    # Cover
    story += [Spacer(1, 40 * mm), Paragraph(d['partner'].upper(), st['sub']), Spacer(1, 4), Paragraph(p.name, st['title']),
              Paragraph('PROGRAMME RESULTS REPORT', ParagraphStyle('x', parent=st['sub'], fontSize=12, textColor=green)), Spacer(1, 6),
              Paragraph(f'Reporting period {d["period_start"]} to {d["period_end"]}', st['sub']),
              Paragraph(' · '.join(x for x in [f'Funder: {p.funder}' if p.funder else '', f'Ref: {p.code}' if p.code else '', f'Status: {p.get_status_display()}',
                                                f'Programme dates: {p.start_date} → {p.end_date or "open"}'] if x), st['sub']),
              Spacer(1, 30 * mm)]
    if p.description:
        story += [Paragraph('Objective', st['h2']), Paragraph(p.description, st['n'])]
    story += [Paragraph('Targeting', st['h2']),
              Paragraph(', '.join(x for x in [', '.join(p.target_provinces or []) or '', ', '.join(p.target_districts or []) or '',
                                                (', '.join(c.title() for c in p.target_enterprise_categories) + ' enterprises') if p.target_enterprise_categories else ''] if x) or 'National, all enterprise types', st['n']),
              PageBreak()]

    # 1 Summary
    story.append(Paragraph('1. Summary of results', st['h1']))
    kpis = [('Farms enrolled', f'{r.farms_enrolled}' + (f' / {p.target_farms} ({_fmt(r.enrolment_pct, 1)}%)' if p.target_farms else '')),
            ('Districts reached', str(r.districts)), ('Active batches / cycles', str(r.active_batches)),
            ('Production records', _fmt(r.records_since_start)), ('Harvest logged', f'{_fmt(r.harvest_quantity_since_start)} units ({r.harvest_records_since_start} records)'),
            ('Support delivered', f'{p.currency} {_fmt(r.support_value)} · {r.support_events} records · {r.farms_supported} farms'),
            ('Budget used', f'{_fmt(r.budget_used_pct, 1)}% of {p.currency} {_fmt(p.budget)}'), ('Farmer issues resolved / open', f'{r.reports_resolved_since_start} / {r.reports_open}'),
            ('Programme notices issued', str(d['notices']))]
    cells = [[Paragraph(k.upper(), st['lbl']), Paragraph(str(v), st['n'])] for k, v in kpis]
    grid = [cells[i] + (cells[i + 1] if i + 1 < len(cells) else ['', '']) for i in range(0, len(cells), 2)]
    t = Table(grid, colWidths=[38 * mm, 49 * mm, 38 * mm, 49 * mm])
    t.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.25, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    story.append(t)

    # 2 Results framework
    story.append(Paragraph('2. Results framework — indicators against targets', st['h1']))
    if not d['indicators']:
        story.append(Paragraph('No indicators defined for this programme.', st['n']))
    else:
        rows = [['Result / indicator', 'Unit', 'Baseline', 'Target', 'Achieved', 'Progress']]
        for i in d['indicators']:
            label = i['label'] + (f"<br/><font size=7 color='#64748b'>{i['result']}</font>" if i['result'] else '') + (f"<br/><font size=7 color='#64748b'>{i['breakdown']}</font>" if i['breakdown'] else '')
            rows.append([Paragraph(label, st['n']), i['unit'], _fmt(i['baseline'], 2) if i['baseline'] is not None else '—',
                         _fmt(i['target'], 2) if i['target'] is not None else '—',
                         (_fmt(i['latest'], 2) if i['latest'] is not None else '—') + (' *' if i['auto'] else ''),
                         f'{i["progress_pct"]:.0f}%' if i['progress_pct'] is not None else '—'])
        story.append(table(rows, [70 * mm, 18 * mm, 20 * mm, 20 * mm, 24 * mm, 22 * mm], align_right_from=2))
        story.append(Paragraph('* computed automatically from participants’ own platform records.', st['sm']))
        res = d['results']
        story.append(Paragraph(f'Participants: {res.farms_active} active — {res.participants_women} women-headed, {res.participants_men} men-headed, {res.participants_youth} youth-led, {res.participants_disability} with a household member with a disability; {res.households_reached} household members reached ({res.participants_with_profile} profiles recorded).', st['n']))
        hist = [(i['label'], h) for i in d['indicators'] for h in i['history']]
        if hist:
            story.append(Paragraph('Reading history', st['h2']))
            story.append(table([['Indicator', 'Period', 'Value', 'Source / notes']] + [[Paragraph(l, st['n']), h['period'], _fmt(h['value'], 2), Paragraph(h['notes'] or '', st['sm'])] for l, h in hist],
                               [54 * mm, 24 * mm, 22 * mm, 74 * mm], align_right_from=2))

    # 3 Enrolment by district
    story.append(Paragraph('3. Enrolment and production evidence by district', st['h1']))
    if d['districts']:
        rows = [['Province', 'District', 'Farms', 'Active', 'Records', 'Harvest', f'Support ({p.currency})']]
        for x in d['districts']:
            rows.append([x['province'], x['district'], x['farms'], x['active'], x['records'], _fmt(x['harvest']), _fmt(x['support'])])
        rows.append(['Total', '', sum(x['farms'] for x in d['districts']), sum(x['active'] for x in d['districts']), sum(x['records'] for x in d['districts']),
                     _fmt(sum(x['harvest'] for x in d['districts'])), _fmt(sum(x['support'] for x in d['districts']))])
        story.append(table(rows, [28 * mm, 34 * mm, 18 * mm, 18 * mm, 22 * mm, 26 * mm, 28 * mm], align_right_from=2))
        story.append(Paragraph('Enrolled farms', st['h2']))
        story.append(table([['Participant', 'Type', 'District', 'Cohort', 'Status', 'Enrolled']] + [[Paragraph(e.farm.name, st['n']), e.farm.get_business_type_display(), e.farm.district, e.cohort or '—', e.get_status_display(), e.enrolled_at.strftime('%Y-%m-%d')] for e in d['enrolled']],
                           [50 * mm, 30 * mm, 28 * mm, 30 * mm, 18 * mm, 18 * mm]))
    else:
        story.append(Paragraph('No farms enrolled.', st['n']))

    # 4 Support
    story.append(Paragraph('4. Support delivered', st['h1']))
    if d['support_by_type']:
        story.append(table([['Type', 'Records', 'Farms', f'Value ({p.currency})']] + [[x['type'], x['events'], x['farms'], _fmt(x['value'])] for x in d['support_by_type']] +
                           [['Total', sum(x['events'] for x in d['support_by_type']), '', _fmt(sum(x['value'] for x in d['support_by_type']))]],
                           [74 * mm, 30 * mm, 30 * mm, 40 * mm], align_right_from=1))
        story.append(Paragraph('Ledger', st['h2']))
        story.append(table([['Date', 'Farm', 'Type', 'Description', 'Qty', 'Value', 'Ref']] +
                           [[l['date'], Paragraph(l['farm'], st['sm']), Paragraph(l['type'], st['sm']), Paragraph(l['description'], st['sm']), l['qty'], f'{l["currency"]} {_fmt(l["value"])}', l['ref'] or '—'] for l in d['ledger']],
                           [20 * mm, 34 * mm, 24 * mm, 46 * mm, 18 * mm, 20 * mm, 12 * mm]))
    else:
        story.append(Paragraph('No support recorded in the period.', st['n']))

    story += [Spacer(1, 8), Paragraph('Methodology', st['h2']),
              Paragraph('Enrolment, support and indicator readings are recorded by the partner in AGRINUXES. Production records, harvest quantities and farmer-reported issues come directly '
                        'from the enrolled farms\' own record-keeping in the platform and are aggregated for the reporting period; farms are included only after opting in to data sharing. '
                        'Harvest units follow each farm\'s recorded unit (kg, bags, birds, etc.).', st['sm'])]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return url


# ─── Excel ───────────────────────────────────────────────────────────────────

def build_programme_report_xlsx(programme, period_start=None, period_end=None):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    d = collect_report_data(programme, period_start, period_end)
    p, r = d['programme'], d['results']
    wb = openpyxl.Workbook()
    head_font, head_fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='0F2B1A')

    def sheet(title, header, rows, widths=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill, c.alignment = head_font, head_fill, Alignment(vertical='center')
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths or [18] * len(header), 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = 'A2'
        return ws

    ws = wb.active; ws.title = 'Summary'
    ws['A1'] = p.name; ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = f'{d["partner"]} · Results report · {d["period_start"]} to {d["period_end"]} · generated {d["generated_at"]:%Y-%m-%d %H:%M}'
    for i, (k, v) in enumerate([('Funder', p.funder), ('Reference', p.code), ('Status', p.get_status_display()), ('Programme dates', f'{p.start_date} → {p.end_date or "open"}'),
                                ('Budget', f'{p.currency} {_fmt(p.budget)}'), ('Farms enrolled', r.farms_enrolled), ('Enrolment target', p.target_farms),
                                ('Enrolment %', r.enrolment_pct), ('Districts reached', r.districts), ('Active batches', r.active_batches),
                                ('Production records', r.records_since_start), ('Harvest records', r.harvest_records_since_start), ('Harvest quantity', r.harvest_quantity_since_start),
                                ('Support records', r.support_events), ('Support value', r.support_value), ('Farms supported', r.farms_supported), ('Budget used %', r.budget_used_pct),
                                ('Issues resolved', r.reports_resolved_since_start), ('Issues open', r.reports_open), ('Notices issued', d['notices'])], start=4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True); ws.cell(row=i, column=2, value=v)
    ws.column_dimensions['A'].width = 24; ws.column_dimensions['B'].width = 40

    sheet('Indicators', ['Indicator', 'Key', 'Unit', 'Target', 'Latest', 'As of', 'Progress %'],
          [[i['label'], i['key'], i['unit'], i['target'], i['latest'], i['latest_period'], i['progress_pct']] for i in d['indicators']], [34, 16, 12, 12, 12, 14, 12])
    sheet('Indicator readings', ['Indicator', 'Period', 'Value', 'Notes'],
          [[i['label'], h['period'], h['value'], h['notes']] for i in d['indicators'] for h in i['history']], [34, 14, 12, 60])
    sheet('Districts', ['Province', 'District', 'Farms', 'Active', 'Records', 'Harvest', f'Support ({p.currency})'],
          [[x['province'], x['district'], x['farms'], x['active'], x['records'], x['harvest'], x['support']] for x in d['districts']])
    sheet('Enrolled farms', ['Participant', 'Type', 'Province', 'District', 'Cohort', 'Status', 'Enrolled'],
          [[e.farm.name, e.farm.get_business_type_display(), e.farm.province, e.farm.district, e.cohort, e.get_status_display(), e.enrolled_at.date()] for e in d['enrolled']], [34, 20, 16, 16, 18, 12, 12])
    sheet('Support by type', ['Type', 'Records', 'Farms', f'Value ({p.currency})'], [[x['type'], x['events'], x['farms'], x['value']] for x in d['support_by_type']], [30, 12, 12, 16])
    sheet('Support ledger', ['Date', 'Farm', 'District', 'Type', 'Description', 'Quantity', 'Value', 'Currency', 'Reference'],
          [[l['date'], l['farm'], l['district'], l['type'], l['description'], l['qty'], l['value'], l['currency'], l['ref']] for l in d['ledger']], [12, 30, 14, 20, 50, 12, 12, 10, 14])
    name = f'programme_report_{p.id.hex[:8]}_{d["generated_at"]:%Y%m%d%H%M%S}.xlsx'
    path, url = _out(name)
    wb.save(path)
    return url
