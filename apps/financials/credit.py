"""
Credit summary for lenders — computed from the farm's own records.

Nothing here is self-reported at application time: every number comes from
production records, batch financials, trade contracts, programme support and
extension activity already captured in the app. The score is a transparent,
rule-based 0–100 with five weighted factors so a credit officer can see *why*.

Factors (weights sum to 100):
  record_consistency  25  — months with production records in the last 12; recency
  profitability       25  — ROI / margin across batch financials, revenue trend
  trading_history     20  — fulfilled contracts, value, marketplace activity
  tenure_and_scale    15  — months on platform, enterprises, batches completed, area
  verification        15  — data-sharing consent, extension officer, programme
                            enrolment, certifications, insurance, buyer verification
"""
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum, Count, Q
from django.utils import timezone

WEIGHTS = {'record_consistency': 25, 'profitability': 25, 'trading_history': 20, 'tenure_and_scale': 15, 'verification': 15}
BANDS = [(80, 'A', 'Strong — eligible for standard terms'), (65, 'B', 'Good — eligible, standard monitoring'),
         (50, 'C', 'Fair — consider with collateral or group guarantee'), (35, 'D', 'Weak — small ticket / input-in-kind only'),
         (0, 'E', 'Insufficient history — not yet scoreable')]


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _month_key(d):
    return f'{d.year}-{d.month:02d}'


def compute_credit_summary(org, as_of=None):
    """Return a plain dict (JSON-serialisable) with metrics, factors, score and band."""
    from apps.enterprises.models import Enterprise, EnterpriseBatch
    from apps.production.models import ProductionRecord
    from apps.financials.models import BatchFinancials, RevenueEntry, InsuranceClaim, LoanApplication
    from apps.market.models import TradeContract, MarketListing
    from apps.sustainability.models import CertificationRecord
    from apps.weather.models import FarmField

    today = as_of or timezone.localdate()
    since_12 = today - timedelta(days=365)
    months_12 = [_month_key(date(today.year, today.month, 1) - timedelta(days=30 * i)) for i in range(12)]

    # ── Tenure & scale ────────────────────────────────────────────────────
    tenure_months = max(0, (today - org.created_at.date()).days // 30)
    enterprises = list(Enterprise.objects.filter(organization=org, is_active=True).values('category'))
    batches_total = EnterpriseBatch.objects.filter(organization=org).count()
    batches_completed = EnterpriseBatch.objects.filter(organization=org, status='completed').count()
    area_ha = _f(FarmField.objects.filter(organization=org).aggregate(a=Sum('area_ha'))['a'])

    # ── Record consistency ────────────────────────────────────────────────
    recs = ProductionRecord.objects.filter(organization=org, record_date__gte=since_12)
    records_12m = recs.count()
    by_month = defaultdict(int)
    for d in recs.values_list('record_date', flat=True):
        by_month[_month_key(d)] += 1
    active_months = sum(1 for m in months_12 if by_month.get(m))
    last_record = ProductionRecord.objects.filter(organization=org).order_by('-record_date').values_list('record_date', flat=True).first()
    days_since_record = (today - last_record).days if last_record else None

    # ── Profitability ─────────────────────────────────────────────────────
    fin = list(BatchFinancials.objects.filter(organization=org))
    fin_12 = [b for b in fin if b.start_date >= since_12 or (b.end_date and b.end_date >= since_12)]
    revenue_life = sum(_f(b.total_revenue) for b in fin)
    costs_life = sum(_f(b.total_costs) for b in fin)
    revenue_12 = sum(_f(b.total_revenue) for b in fin_12)
    costs_12 = sum(_f(b.total_costs) for b in fin_12)
    profit_12 = revenue_12 - costs_12
    roi_12 = (profit_12 / costs_12 * 100) if costs_12 else None
    margin_12 = (profit_12 / revenue_12 * 100) if revenue_12 else None
    profitable_batches = sum(1 for b in fin if _f(b.total_revenue) > _f(b.total_costs) and _f(b.total_costs) > 0)
    scored_batches = sum(1 for b in fin if _f(b.total_costs) > 0)
    monthly_revenue = defaultdict(float)
    for r in RevenueEntry.objects.filter(organization=org, entry_date__gte=since_12).values('entry_date', 'amount'):
        monthly_revenue[_month_key(r['entry_date'])] += _f(r['amount'])
    revenue_series = [{'month': m, 'revenue': round(monthly_revenue.get(m, 0.0), 2)} for m in reversed(months_12)]
    first_half = sum(x['revenue'] for x in revenue_series[:6])
    second_half = sum(x['revenue'] for x in revenue_series[6:])
    revenue_trend_pct = ((second_half - first_half) / first_half * 100) if first_half else None

    # ── Trading history ───────────────────────────────────────────────────
    contracts = TradeContract.objects.filter(organization=org)
    fulfilled = contracts.filter(status='fulfilled')
    contracts_fulfilled = fulfilled.count()
    contracts_disputed = contracts.filter(status__in=['disputed', 'cancelled']).count()
    contracts_value_fulfilled = _f(fulfilled.aggregate(v=Sum('total_value'))['v'])
    contracts_open = contracts.filter(status__in=['accepted', 'in_progress']).count()
    verified_buyers = contracts.filter(buyer__is_verified=True).values('buyer').distinct().count()
    listings_active = MarketListing.objects.filter(organization=org, status='active').count()
    fulfil_rate = (contracts_fulfilled / (contracts_fulfilled + contracts_disputed)) if (contracts_fulfilled + contracts_disputed) else None

    # ── Verification ──────────────────────────────────────────────────────
    from apps.extension.models import ExtensionCaseload, ExtensionVisit
    from apps.partners.models import ProgrammeEnrollment, ProgrammeSupport
    has_officer = ExtensionCaseload.objects.filter(farm=org, is_active=True).exists()
    visits_12m = ExtensionVisit.objects.filter(farm=org, visit_date__gte=since_12).count()
    programmes = list(ProgrammeEnrollment.objects.filter(farm=org, status__in=['active', 'completed'])
                      .select_related('programme', 'programme__organization'))
    support_value = _f(ProgrammeSupport.objects.filter(farm=org).aggregate(v=Sum('value'))['v'])
    certifications = list(CertificationRecord.objects.filter(organization=org, status='certified').values_list('certification_name', flat=True))
    insurance_active = InsuranceClaim.objects.filter(organization=org).exclude(status__in=['draft', 'rejected']).exists()
    loans = list(LoanApplication.objects.filter(organization=org).values('lender_name', 'status', 'amount_requested', 'amount_approved', 'loan_type'))
    loans_repaid = sum(1 for l in loans if l['status'] == 'repaid')
    loans_defaulted = sum(1 for l in loans if l['status'] == 'defaulted')

    # ── Factor scores (0–1) ───────────────────────────────────────────────
    f_records = _clamp(active_months / 12) * 0.8 + (0.2 if days_since_record is not None and days_since_record <= 14 else 0.1 if days_since_record is not None and days_since_record <= 45 else 0)
    if scored_batches == 0:
        f_profit = 0.0
    else:
        roi_component = _clamp((roi_12 if roi_12 is not None else -100) / 60)  # 60% ROI = full marks
        consistency = profitable_batches / scored_batches
        trend = 0.5 if revenue_trend_pct is None else _clamp(0.5 + revenue_trend_pct / 100, 0, 1)
        f_profit = 0.5 * roi_component + 0.3 * consistency + 0.2 * trend
    f_trade = (_clamp(contracts_fulfilled / 6) * 0.5 + (fulfil_rate if fulfil_rate is not None else 0) * 0.3
               + _clamp(verified_buyers / 3) * 0.1 + _clamp(listings_active / 3) * 0.1)
    f_tenure = _clamp(tenure_months / 24) * 0.4 + _clamp(len(enterprises) / 3) * 0.2 + _clamp(batches_completed / 6) * 0.3 + _clamp(area_ha / 10) * 0.1
    f_verify = (0.25 * org.data_sharing_consent + 0.2 * has_officer + 0.2 * bool(programmes) + 0.15 * bool(certifications)
                + 0.1 * insurance_active + 0.1 * (1 if loans_repaid and not loans_defaulted else 0))
    if loans_defaulted:
        f_verify = max(0.0, f_verify - 0.5)

    factors = [
        {'key': 'record_consistency', 'label': 'Record-keeping consistency', 'weight': WEIGHTS['record_consistency'], 'score': round(f_records * WEIGHTS['record_consistency'], 1),
         'evidence': f'{active_months} of last 12 months with production records ({records_12m} records); last record {days_since_record} days ago' if days_since_record is not None else 'No production records yet'},
        {'key': 'profitability', 'label': 'Profitability', 'weight': WEIGHTS['profitability'], 'score': round(f_profit * WEIGHTS['profitability'], 1),
         'evidence': (f'ROI {roi_12:.0f}% and margin {margin_12:.0f}% over 12 months; {profitable_batches}/{scored_batches} batches profitable'
                      if roi_12 is not None else 'No batch financials with costs recorded')},
        {'key': 'trading_history', 'label': 'Trading history', 'weight': WEIGHTS['trading_history'], 'score': round(f_trade * WEIGHTS['trading_history'], 1),
         'evidence': f'{contracts_fulfilled} contracts fulfilled (ZMW {contracts_value_fulfilled:,.0f}), {contracts_disputed} disputed/cancelled, {verified_buyers} verified buyers'},
        {'key': 'tenure_and_scale', 'label': 'Tenure & scale', 'weight': WEIGHTS['tenure_and_scale'], 'score': round(f_tenure * WEIGHTS['tenure_and_scale'], 1),
         'evidence': f'{tenure_months} months on platform, {len(enterprises)} enterprises, {batches_completed} batches completed, {area_ha:.1f} ha registered'},
        {'key': 'verification', 'label': 'Verification & support network', 'weight': WEIGHTS['verification'], 'score': round(f_verify * WEIGHTS['verification'], 1),
         'evidence': ', '.join(x for x in [
             'data sharing consented' if org.data_sharing_consent else 'no data-sharing consent',
             'extension officer assigned' if has_officer else None,
             f'{len(programmes)} programme(s)' if programmes else None,
             f'{len(certifications)} certification(s)' if certifications else None,
             'insured' if insurance_active else None,
             f'{loans_repaid} loan(s) repaid' if loans_repaid else None,
             f'{loans_defaulted} DEFAULT(S)' if loans_defaulted else None] if x)},
    ]
    score = round(sum(f['score'] for f in factors))
    # Thin-file rule: fewer than 3 active months or no financials caps the band at D
    thin_file = active_months < 3 and scored_batches == 0
    band, band_label = next((b, l) for t, b, l in BANDS if score >= t)
    if thin_file and band in ('A', 'B', 'C'):
        band, band_label = 'D', 'Thin file — fewer than 3 months of records; score provisional'

    return {
        'generated_at': timezone.now().isoformat(), 'as_of': today.isoformat(),
        'farm': {'name': org.name, 'province': org.province, 'district': org.district, 'country': org.country or 'Zambia',
                 'member_since': org.created_at.date().isoformat(), 'tenure_months': tenure_months,
                 'enterprises': sorted({e['category'] for e in enterprises}), 'enterprise_count': len(enterprises), 'area_ha': round(area_ha, 2)},
        'score': score, 'band': band, 'band_label': band_label, 'thin_file': thin_file, 'factors': factors,
        'records': {'records_12m': records_12m, 'active_months_12': active_months, 'days_since_last_record': days_since_record,
                    'batches_total': batches_total, 'batches_completed': batches_completed},
        'financials': {'revenue_12m': round(revenue_12, 2), 'costs_12m': round(costs_12, 2), 'profit_12m': round(profit_12, 2),
                       'roi_pct_12m': round(roi_12, 1) if roi_12 is not None else None, 'margin_pct_12m': round(margin_12, 1) if margin_12 is not None else None,
                       'revenue_lifetime': round(revenue_life, 2), 'costs_lifetime': round(costs_life, 2),
                       'profitable_batches': profitable_batches, 'scored_batches': scored_batches,
                       'revenue_trend_pct': round(revenue_trend_pct, 1) if revenue_trend_pct is not None else None, 'monthly_revenue': revenue_series},
        'trading': {'contracts_fulfilled': contracts_fulfilled, 'contracts_open': contracts_open, 'contracts_disputed': contracts_disputed,
                    'fulfilled_value': round(contracts_value_fulfilled, 2), 'fulfilment_rate_pct': round(fulfil_rate * 100) if fulfil_rate is not None else None,
                    'verified_buyers': verified_buyers, 'active_listings': listings_active},
        'verification': {'data_sharing_consent': org.data_sharing_consent, 'extension_officer': has_officer, 'extension_visits_12m': visits_12m,
                         'programmes': [{'name': p.programme.name, 'partner': p.programme.organization.name, 'status': p.status} for p in programmes],
                         'support_value': round(support_value, 2), 'certifications': certifications, 'insurance_active': insurance_active,
                         'loans': [{'lender': l['lender_name'], 'type': l['loan_type'], 'status': l['status'],
                                    'requested': _f(l['amount_requested']), 'approved': _f(l['amount_approved'])} for l in loans]},
    }


# ─── PDF ─────────────────────────────────────────────────────────────────────

def build_credit_summary_pdf(org, summary=None, for_lender=None):
    """Render the summary as a one/two-page PDF under MEDIA_ROOT/credit/. Returns the relative URL."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    s = summary or compute_credit_summary(org)
    ss = getSampleStyleSheet()
    green, grey, line, pale = colors.HexColor('#2D5016'), colors.HexColor('#6B7280'), colors.HexColor('#D1D5DB'), colors.HexColor('#F5F7F4')
    st = {'t': ParagraphStyle('t', parent=ss['Title'], fontSize=16, textColor=green, alignment=TA_CENTER, spaceAfter=2),
          'sub': ParagraphStyle('s', parent=ss['Normal'], fontSize=9, textColor=grey, alignment=TA_CENTER),
          'h': ParagraphStyle('h', parent=ss['Heading4'], fontSize=10, textColor=green, spaceBefore=8, spaceAfter=3),
          'n': ParagraphStyle('n', parent=ss['Normal'], fontSize=9, leading=12), 'sm': ParagraphStyle('sm', parent=ss['Normal'], fontSize=7.5, leading=10, textColor=grey)}
    d = os.path.join(settings.MEDIA_ROOT, 'credit')
    os.makedirs(d, exist_ok=True)
    name = f'credit_{org.slug}_{timezone.now():%Y%m%d%H%M%S}.pdf'
    path = os.path.join(d, name)
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title=f'Credit summary — {org.name}')
    story = [Paragraph('AGRINUXES FARM CREDIT SUMMARY', st['t']),
             Paragraph(f'{s["farm"]["name"]} · {s["farm"]["district"] or ""} {s["farm"]["province"] or ""} · as of {s["as_of"]}' + (f' · prepared for {for_lender}' if for_lender else ''), st['sub']),
             Spacer(1, 8)]
    f = s['financials']; t = s['trading']; r = s['records']; v = s['verification']
    big = ParagraphStyle('big', parent=ss['Normal'], fontSize=28, leading=34)
    mid = ParagraphStyle('mid', parent=ss['Normal'], fontSize=12, leading=16)
    score_tbl = Table([[Paragraph(f'<b>{s["score"]}</b> <font size=9>/ 100</font>', big),
                        Paragraph(f'<font size=20><b>Band {s["band"]}</b></font><br/>{s["band_label"]}', mid)]], colWidths=[50 * mm, 120 * mm], rowHeights=[22 * mm])
    score_tbl.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.5, line), ('BACKGROUND', (0, 0), (-1, -1), pale), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 10)]))
    story.append(score_tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph('Score factors', st['h']))
    ft = [['Factor', 'Score', 'Weight', 'Evidence from farm records']] + [[x['label'], f'{x["score"]:.1f}', str(x['weight']), Paragraph(x['evidence'], st['sm'])] for x in s['factors']]
    tb = Table(ft, colWidths=[45 * mm, 15 * mm, 15 * mm, 95 * mm], repeatRows=1)
    tb.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), green), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
                            ('GRID', (0, 0), (-1, -1), 0.25, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 1), (2, -1), 'RIGHT')]))
    story.append(tb)

    def kv(pairs):
        rows = [[Paragraph(k.upper(), st['sm']), Paragraph(str(val), st['n'])] for k, val in pairs]
        tt = Table(rows, colWidths=[60 * mm, 110 * mm])
        tt.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.25, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
        return tt
    story.append(Paragraph('Farm', st['h']))
    story.append(kv([('Member since', f'{s["farm"]["member_since"]} ({s["farm"]["tenure_months"]} months)'), ('Enterprises', ', '.join(s['farm']['enterprises']) or '—'),
                     ('Registered area', f'{s["farm"]["area_ha"]} ha'), ('Batches / cycles', f'{r["batches_completed"]} completed of {r["batches_total"]}'),
                     ('Production records (12 m)', f'{r["records_12m"]} across {r["active_months_12"]} active months')]))
    story.append(Paragraph('Financial performance (from batch financials)', st['h']))
    story.append(kv([('Revenue, 12 months', f'ZMW {f["revenue_12m"]:,.0f}'), ('Costs, 12 months', f'ZMW {f["costs_12m"]:,.0f}'), ('Gross profit, 12 months', f'ZMW {f["profit_12m"]:,.0f}'),
                     ('ROI / margin', f'{f["roi_pct_12m"]}% / {f["margin_pct_12m"]}%' if f['roi_pct_12m'] is not None else '—'),
                     ('Profitable batches', f'{f["profitable_batches"]} of {f["scored_batches"]}'), ('Lifetime revenue', f'ZMW {f["revenue_lifetime"]:,.0f}'),
                     ('Revenue trend (H2 vs H1)', f'{f["revenue_trend_pct"]:+.0f}%' if f['revenue_trend_pct'] is not None else '—')]))
    story.append(Paragraph('Trading history', st['h']))
    story.append(kv([('Contracts fulfilled', f'{t["contracts_fulfilled"]} (ZMW {t["fulfilled_value"]:,.0f})'), ('Fulfilment rate', f'{t["fulfilment_rate_pct"]}%' if t['fulfilment_rate_pct'] is not None else '—'),
                     ('Open / disputed', f'{t["contracts_open"]} / {t["contracts_disputed"]}'), ('Verified buyers', t['verified_buyers'])]))
    story.append(Paragraph('Verification & support network', st['h']))
    story.append(kv([('Data-sharing consent', 'Yes' if v['data_sharing_consent'] else 'No'), ('Extension officer', f'Yes — {v["extension_visits_12m"]} visits in 12 m' if v['extension_officer'] else 'No'),
                     ('Programmes', '; '.join(f'{p["name"]} ({p["partner"]}, {p["status"]})' for p in v['programmes']) or '—'),
                     ('Support received', f'ZMW {v["support_value"]:,.0f}'), ('Certifications', ', '.join(v['certifications']) or '—'),
                     ('Loan history', '; '.join(f'{l["lender"]} {l["type"]} — {l["status"]}' for l in v['loans']) or 'None on record')]))
    story.append(Spacer(1, 8))
    story.append(Paragraph('This summary is generated automatically from records the farm keeps in AGRINUXES and is shared at the farm\'s request. It is decision support, not a credit decision; verify against the lender\'s own KYC. Score methodology: five weighted, rule-based factors (25/25/20/15/15).', st['sm']))
    doc.build(story)
    return f'{settings.MEDIA_URL}credit/{name}'
