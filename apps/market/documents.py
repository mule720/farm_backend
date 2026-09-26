"""
Export & trade document generation (PDF, reportlab).

One generator per document type on ExportDocument.DOC_TYPE_CHOICES, plus a
sale/trade contract. All documents share a header (exporter, buyer, doc
number, dates), a commodity table, and a signature block; the per-type
sections carry the declarations each certificate actually needs
(phytosanitary → ISPM 12 wording, CoO → origin declaration, etc.).

Files are written to MEDIA_ROOT/export_docs/ and the relative URL is stored
on the model (document_url) so the frontend can open it.
"""
import os
from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

GREEN = colors.HexColor('#2D5016')
GREY = colors.HexColor('#6B7280')
LINE = colors.HexColor('#D1D5DB')
PALE = colors.HexColor('#F5F7F4')

DOC_PREFIX = {
    'phytosanitary': 'PHY', 'packing_list': 'PKL', 'invoice': 'INV', 'coo': 'COO',
    'health_cert': 'VHC', 'fumigation': 'FUM', 'customs': 'CUS', 'other': 'DOC',
}
DOC_TITLE = dict([
    ('phytosanitary', 'PHYTOSANITARY CERTIFICATE'), ('packing_list', 'PACKING LIST'),
    ('invoice', 'COMMERCIAL INVOICE'), ('coo', 'CERTIFICATE OF ORIGIN'),
    ('health_cert', 'VETERINARY HEALTH CERTIFICATE'), ('fumigation', 'FUMIGATION CERTIFICATE'),
    ('customs', 'CUSTOMS DECLARATION'), ('other', 'TRADE DOCUMENT'),
])
# Authority that normally issues each certificate in Zambia — pre-filled, editable
DEFAULT_AUTHORITY = {
    'phytosanitary': 'Plant Quarantine & Phytosanitary Service (PQPS), Ministry of Agriculture, Zambia',
    'health_cert': 'Department of Veterinary Services, Ministry of Fisheries & Livestock, Zambia',
    'coo': 'Zambia Chamber of Commerce and Industry / Zambia Revenue Authority',
    'fumigation': 'Licensed fumigation operator (ZEMA-registered)',
    'customs': 'Zambia Revenue Authority — Customs Services Division',
}


def _styles():
    ss = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('t', parent=ss['Title'], fontSize=16, textColor=GREEN, spaceAfter=2, alignment=TA_CENTER),
        'sub': ParagraphStyle('s', parent=ss['Normal'], fontSize=9, textColor=GREY, alignment=TA_CENTER),
        'h': ParagraphStyle('h', parent=ss['Heading4'], fontSize=10, textColor=GREEN, spaceBefore=8, spaceAfter=3),
        'n': ParagraphStyle('n', parent=ss['Normal'], fontSize=9, leading=12),
        'small': ParagraphStyle('sm', parent=ss['Normal'], fontSize=7.5, leading=10, textColor=GREY),
        'right': ParagraphStyle('r', parent=ss['Normal'], fontSize=9, alignment=TA_RIGHT),
        'label': ParagraphStyle('l', parent=ss['Normal'], fontSize=7.5, textColor=GREY),
        'val': ParagraphStyle('v', parent=ss['Normal'], fontSize=9.5, leading=12),
    }


def _fmt(v, places=2):
    try:
        return f'{float(v):,.{places}f}'
    except (TypeError, ValueError):
        return str(v or '')


def next_doc_number(org, doc_type):
    """ORG-PREFIX-YYYY-NNNN, sequential per organisation, type and year."""
    year = date.today().year
    from .models import ExportDocument
    prefix = f'{DOC_PREFIX.get(doc_type, "DOC")}-{year}-'
    existing = ExportDocument.objects.filter(organization=org, doc_type=doc_type, doc_number__startswith=prefix) \
        .aggregate(m=Max('doc_number'))['m']
    seq = int(existing.rsplit('-', 1)[-1]) + 1 if existing else 1
    return f'{prefix}{seq:04d}'


# ─── Shared blocks ───────────────────────────────────────────────────────────

def _kv_table(pairs, st, col_widths=(45 * mm, 45 * mm, 45 * mm, 45 * mm)):
    """2-column label/value grid, 2 pairs per row."""
    rows, cur = [], []
    for label, value in pairs:
        cur += [Paragraph(label.upper(), st['label']), Paragraph(str(value or '—'), st['val'])]
        if len(cur) == 4:
            rows.append(cur); cur = []
    if cur:
        rows.append(cur + [''] * (4 - len(cur)))
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                           ('LINEBELOW', (0, 0), (-1, -1), 0.25, LINE)]))
    return t


def _parties(org, buyer, contract, st):
    exporter = [org.name, org.district and f'{org.district}, {org.province}' or org.province or '', org.country or 'Zambia']
    consignee = [buyer.name, buyer.contact_person and f'Attn: {buyer.contact_person}' or '', buyer.address or '',
                 f'{buyer.town}, {buyer.country}'.strip(', '), buyer.phone or '', buyer.email or ''] if buyer else ['—']
    data = [[Paragraph('EXPORTER / CONSIGNOR', st['label']), Paragraph('CONSIGNEE / BUYER', st['label'])],
            [Paragraph('<br/>'.join(x for x in exporter if x), st['val']), Paragraph('<br/>'.join(x for x in consignee if x), st['val'])]]
    t = Table(data, colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), 0.5, LINE),
                           ('INNERGRID', (0, 0), (-1, -1), 0.25, LINE), ('BACKGROUND', (0, 0), (-1, 0), PALE),
                           ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    return t


def _commodity_table(rows, st, money=True, currency='ZMW'):
    head = ['#', 'Description of goods', 'Quantity', 'Unit'] + (['Unit price', 'Amount'] if money else [])
    data = [head]
    total = 0.0
    for i, r in enumerate(rows, 1):
        line = [str(i), Paragraph(r['description'], st['n']), _fmt(r['quantity']), r.get('unit', '')]
        if money:
            amt = float(r['quantity'] or 0) * float(r.get('price') or 0)
            total += amt
            line += [_fmt(r.get('price'), 4), _fmt(amt)]
        data.append(line)
    if money:
        data.append(['', Paragraph(f'<b>TOTAL ({currency})</b>', st['right']), '', '', '', Paragraph(f'<b>{_fmt(total)}</b>', st['right'])])
    widths = [8 * mm, 82 * mm, 25 * mm, 18 * mm] + ([23 * mm, 24 * mm] if money else [])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GREEN), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('GRID', (0, 0), (-1, -1), 0.25, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PALE]),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t, total


def _signatures(left, right, st):
    data = [[Paragraph(left, st['label']), Paragraph(right, st['label'])],
            [Spacer(1, 18 * mm), Spacer(1, 18 * mm)],
            [Paragraph('Signature / stamp ______________________  Date __________', st['small']),
             Paragraph('Signature / stamp ______________________  Date __________', st['small'])]]
    t = Table(data, colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('TOPPADDING', (0, 0), (-1, -1), 4)]))
    return KeepTogether([Spacer(1, 10), t])


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 12 * mm, f'Generated by AGRINUXES on {timezone.now().strftime("%Y-%m-%d %H:%M")} — document integrity: check the doc number against the issuing organisation.')
    canvas.drawRightString(190 * mm, 12 * mm, f'Page {doc.page}')
    canvas.restoreState()


def _header(story, st, org, title, doc_number, extra_lines=()):
    story.append(Paragraph(org.name, ParagraphStyle('org', fontSize=11, textColor=GREY, alignment=TA_CENTER)))
    story.append(Paragraph(title, st['title']))
    story.append(Paragraph(' · '.join([f'No. {doc_number}'] + [x for x in extra_lines if x]), st['sub']))
    story.append(Spacer(1, 8))


# ─── Per-type sections ───────────────────────────────────────────────────────

def _section_phytosanitary(story, st, d, org):
    story.append(Paragraph('Declared name and address of exporter, consignee and place of origin as above.', st['n']))
    story.append(Paragraph('Description of consignment', st['h']))
    story.append(_kv_table([
        ('Botanical name / commodity', d.commodity), ('Declared quantity', f'{_fmt(d.quantity)} {d.unit}'),
        ('Country of destination', d.destination_country), ('Place of origin', f'{org.district or ""} {org.province or ""}'.strip() or org.country or 'Zambia'),
        ('Means of conveyance', d.notes and '' or '—'), ('Distinguishing marks', d.doc_number),
    ], st))
    story.append(Paragraph('Certification', st['h']))
    story.append(Paragraph(
        'This is to certify that the plants, plant products or other regulated articles described herein have been '
        'inspected and/or tested according to appropriate official procedures and are considered to be free from the '
        'quarantine pests specified by the importing contracting party and to conform with the current phytosanitary '
        'requirements of the importing contracting party, including those for regulated non-quarantine pests. '
        '(Model certificate wording, IPPC ISPM 12.)', st['n']))
    story.append(Paragraph('Disinfestation and/or disinfection treatment', st['h']))
    story.append(_kv_table([('Treatment', '—'), ('Chemical (active ingredient)', '—'), ('Duration & temperature', '—'), ('Concentration', '—'), ('Date', '—'), ('Additional information', '—')], st))
    story.append(Paragraph('Additional declaration', st['h']))
    story.append(Paragraph(d.notes or 'None.', st['n']))
    story.append(_signatures(f'Issuing authority: {d.issuing_authority or DEFAULT_AUTHORITY["phytosanitary"]}<br/>Name of authorised officer', 'Exporter declaration — the above particulars are true and correct', st))


def _section_invoice(story, st, d, org, contract, buyer):
    story.append(Paragraph('Goods', st['h']))
    t, total = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit,
                                  'price': contract.agreed_price if contract else 0}], st,
                                currency=contract.currency if contract else 'ZMW')
    story.append(t)
    story.append(Paragraph('Terms', st['h']))
    story.append(_kv_table([
        ('Currency', contract.currency if contract else 'ZMW'), ('Total invoice value', _fmt(total)),
        ('Payment terms', (contract and contract.payment_terms) or (buyer and buyer.payment_terms) or '—'),
        ('Delivery date', contract and contract.delivery_date or '—'),
        ('Deposit', contract and f'{contract.deposit_pct}% {"(paid)" if contract.deposit_paid else "(due)"}' or '—'),
        ('Destination', d.destination_country or (buyer and buyer.country) or '—'),
        ('Delivery address', contract and contract.delivery_address or (buyer and buyer.address) or '—'),
        ('Contract reference', contract and str(contract.id)[:8].upper() or '—'),
    ], st))
    story.append(Paragraph('Declaration', st['h']))
    story.append(Paragraph('We declare that this invoice shows the actual price of the goods described, that no other invoice has been issued, and that all particulars are true and correct.', st['n']))
    story.append(_signatures(f'For {org.name}', 'Received by consignee', st))


def _section_packing_list(story, st, d, org, contract):
    story.append(Paragraph('Packages', st['h']))
    t, _ = _commodity_table([{'description': f'{d.commodity} — packed for export', 'quantity': d.quantity, 'unit': d.unit}], st, money=False)
    story.append(t)
    story.append(_kv_table([
        ('Total packages', '—'), ('Package type', '—'), ('Gross weight (kg)', '—'), ('Net weight (kg)', _fmt(d.quantity) if (d.unit or '').lower() in ('kg', 'kgs') else '—'),
        ('Marks & numbers', d.doc_number), ('Destination', d.destination_country), ('Delivery date', contract and contract.delivery_date or '—'), ('Cold chain', 'See cold-chain log if applicable'),
    ], st))
    story.append(Paragraph(d.notes or '', st['n']))
    story.append(_signatures(f'Packed & checked for {org.name}', 'Carrier / forwarder', st))


def _section_coo(story, st, d, org, buyer):
    story.append(Paragraph('Goods', st['h']))
    t, _ = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit}], st, money=False)
    story.append(t)
    story.append(Paragraph('Origin', st['h']))
    story.append(_kv_table([
        ('Country of origin', org.country or 'Zambia'), ('Country of destination', d.destination_country or (buyer and buyer.country) or '—'),
        ('Producer', org.name), ('Place of production', f'{org.district or ""} {org.province or ""}'.strip() or '—'),
        ('HS code', '—'), ('Preferential scheme', 'COMESA / SADC (if applicable)'),
    ], st))
    story.append(Paragraph('Declaration by the exporter', st['h']))
    story.append(Paragraph('The undersigned hereby declares that the above details and statements are correct; that all the goods were produced in the country shown and that they comply with the origin requirements specified for those goods.', st['n']))
    story.append(Paragraph(d.notes or '', st['n']))
    story.append(_signatures(f'Exporter: {org.name}', f'Certifying body: {d.issuing_authority or DEFAULT_AUTHORITY["coo"]}', st))


def _section_health_cert(story, st, d, org):
    story.append(Paragraph('Identification of animals / animal products', st['h']))
    t, _ = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit}], st, money=False)
    story.append(t)
    story.append(_kv_table([('Species / product', d.commodity), ('Origin holding', org.name), ('Destination', d.destination_country), ('Identification marks', d.doc_number)], st))
    story.append(Paragraph('Health attestation', st['h']))
    story.append(Paragraph(
        'I, the undersigned official veterinarian, certify that the animals / products described above: were examined '
        'and found free from clinical signs of infectious or contagious disease; originate from a holding not under '
        'restriction for notifiable diseases; and comply with the animal health requirements of the importing country. '
        'Vaccinations, tests and treatments: see additional declaration.', st['n']))
    story.append(Paragraph('Additional declaration', st['h']))
    story.append(Paragraph(d.notes or 'None.', st['n']))
    story.append(_signatures(f'Official veterinarian — {d.issuing_authority or DEFAULT_AUTHORITY["health_cert"]}', f'Owner / keeper: {org.name}', st))


def _section_fumigation(story, st, d, org):
    story.append(Paragraph('Consignment', st['h']))
    t, _ = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit}], st, money=False)
    story.append(t)
    story.append(Paragraph('Treatment details', st['h']))
    story.append(_kv_table([('Fumigant', '—'), ('Dosage (g/m³)', '—'), ('Exposure period (h)', '—'), ('Temperature (°C)', '—'),
                            ('Date of fumigation', d.issue_date or '—'), ('Place of fumigation', f'{org.district or ""} {org.province or ""}'.strip() or '—'),
                            ('Container / stack no.', d.doc_number), ('Destination', d.destination_country)], st))
    story.append(Paragraph('Certification', st['h']))
    story.append(Paragraph('This is to certify that the goods described were fumigated under gas-tight conditions in accordance with the treatment schedule above and that the consignment was ventilated to safe levels before release.', st['n']))
    story.append(Paragraph(d.notes or '', st['n']))
    story.append(_signatures(f'Fumigation operator: {d.issuing_authority or DEFAULT_AUTHORITY["fumigation"]}', f'Exporter: {org.name}', st))


def _section_customs(story, st, d, org, contract, buyer):
    story.append(Paragraph('Goods declared', st['h']))
    t, total = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit, 'price': contract.agreed_price if contract else 0}], st,
                                currency=contract.currency if contract else 'ZMW')
    story.append(t)
    story.append(_kv_table([
        ('Declarant / exporter TPIN', '—'), ('Customs procedure', 'Export (permanent)'), ('Country of destination', d.destination_country or (buyer and buyer.country) or '—'),
        ('Customs value', _fmt(total)), ('Currency', contract.currency if contract else 'ZMW'), ('HS code', '—'),
        ('Port / border of exit', '—'), ('Supporting documents', 'Invoice, packing list, CoO, phytosanitary / health certificate as applicable'),
    ], st))
    story.append(Paragraph('Declaration', st['h']))
    story.append(Paragraph('I declare that the particulars given in this declaration are true and complete.', st['n']))
    story.append(Paragraph(d.notes or '', st['n']))
    story.append(_signatures(f'Declarant: {org.name}', f'Customs officer — {d.issuing_authority or DEFAULT_AUTHORITY["customs"]}', st))


def _section_other(story, st, d, org):
    t, _ = _commodity_table([{'description': d.commodity, 'quantity': d.quantity, 'unit': d.unit}], st, money=False)
    story.append(t)
    story.append(Paragraph(d.notes or '', st['n']))
    story.append(_signatures(f'For {org.name}', 'Counterparty', st))


# ─── Entry points ────────────────────────────────────────────────────────────

def _out_path(name):
    d = os.path.join(settings.MEDIA_ROOT, 'export_docs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name), f'{settings.MEDIA_URL}export_docs/{name}'


def build_export_document_pdf(doc):
    """Render the PDF for an ExportDocument, store it, set document_url, return the URL."""
    org = doc.organization
    contract = doc.contract
    buyer = contract.buyer if contract else None
    if not doc.doc_number:
        doc.doc_number = next_doc_number(org, doc.doc_type)
    if not doc.issuing_authority and doc.doc_type in DEFAULT_AUTHORITY:
        doc.issuing_authority = DEFAULT_AUTHORITY[doc.doc_type]
    st = _styles()
    path, url = _out_path(f'{doc.doc_number}_{str(doc.id)[:8]}.pdf')
    pdf = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                            title=f'{DOC_TITLE[doc.doc_type]} {doc.doc_number}', author=org.name)
    story = []
    _header(story, st, org, DOC_TITLE[doc.doc_type], doc.doc_number, [
        f'Issued {doc.issue_date}' if doc.issue_date else 'DRAFT — not yet issued',
        f'Expires {doc.expiry_date}' if doc.expiry_date else '',
        f'Status: {doc.get_status_display()}',
    ])
    story.append(_parties(org, buyer, contract, st))
    story.append(Spacer(1, 6))
    {
        'phytosanitary': lambda: _section_phytosanitary(story, st, doc, org),
        'invoice': lambda: _section_invoice(story, st, doc, org, contract, buyer),
        'packing_list': lambda: _section_packing_list(story, st, doc, org, contract),
        'coo': lambda: _section_coo(story, st, doc, org, buyer),
        'health_cert': lambda: _section_health_cert(story, st, doc, org),
        'fumigation': lambda: _section_fumigation(story, st, doc, org),
        'customs': lambda: _section_customs(story, st, doc, org, contract, buyer),
    }.get(doc.doc_type, lambda: _section_other(story, st, doc, org))()
    if doc.status == 'draft':
        story.append(Spacer(1, 6))
        story.append(Paragraph('DRAFT — this document has not been submitted to or issued by the certifying authority. Fields marked — must be completed before submission.', st['small']))
    pdf.build(story, onFirstPage=_footer, onLaterPages=_footer)
    with transaction.atomic():
        doc.document_url = url
        doc.save(update_fields=['document_url', 'doc_number', 'issuing_authority', 'updated_at'])
    return url


def build_contract_pdf(contract):
    """Sale / supply contract between the farm and the buyer."""
    org = contract.organization
    buyer = contract.buyer
    st = _styles()
    ref = f'TC-{contract.created_at:%Y}-{str(contract.id)[:8].upper()}'
    path, url = _out_path(f'{ref}.pdf')
    pdf = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                            title=f'Trade contract {ref}', author=org.name)
    story = []
    _header(story, st, org, 'PRODUCE SALE & SUPPLY CONTRACT', ref, [f'Dated {contract.created_at:%d %B %Y}', f'Status: {contract.get_status_display()}'])
    story.append(_parties(org, buyer, contract, st))
    story.append(Paragraph('1. Goods and price', st['h']))
    t, total = _commodity_table([{'description': contract.commodity, 'quantity': contract.quantity_agreed, 'unit': contract.unit, 'price': contract.agreed_price}], st, currency=contract.currency)
    story.append(t)
    story.append(Paragraph('2. Delivery and payment', st['h']))
    story.append(_kv_table([
        ('Delivery date', contract.delivery_date or 'To be agreed'), ('Delivery address', contract.delivery_address or (buyer and buyer.address) or 'Buyer premises'),
        ('Payment terms', contract.payment_terms or (buyer and buyer.payment_terms) or 'On delivery'), ('Deposit', f'{contract.deposit_pct}% of contract value' if contract.deposit_pct else 'None'),
        ('Contract value', f'{contract.currency} {_fmt(total)}'), ('Quantity delivered to date', f'{_fmt(contract.quantity_delivered)} {contract.unit}'),
    ], st))
    story.append(Paragraph('3. Terms and conditions', st['h']))
    default_terms = (
        '3.1 The Seller warrants that the goods are of merchantable quality, free from pests and contaminants, and produced in accordance with good agricultural practice. '
        '3.2 Quantity tolerance ±5% unless otherwise agreed; price adjusts pro rata. '
        '3.3 Risk passes to the Buyer on delivery; title passes on full payment. '
        '3.4 Either party may cancel on 7 days\' written notice before the delivery date; deposits are refundable only if the Seller cancels. '
        '3.5 Disputes shall first be referred to mediation; failing that, to the courts of Zambia.'
    )
    story.append(Paragraph(contract.terms_and_conditions or default_terms, st['n']))
    if contract.notes:
        story.append(Paragraph('4. Notes', st['h']))
        story.append(Paragraph(contract.notes, st['n']))
    story.append(_signatures(f'Seller: {org.name}', f'Buyer: {buyer.name if buyer else "—"}', st))
    pdf.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return url
