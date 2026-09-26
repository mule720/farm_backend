"""
Vendor-side GraphQL: everything a provider organisation (agro dealer, vet,
equipment hire, agrifood seller, agri-supply, agri-services, processor,
transporter) needs to run its business — its own profile, staff, services,
certifications, fleet, inbound bookings and appointments, walk-in clients,
orders, jobs, processing lots, invoices, clients and revenue.

Ownership rule everywhere: the caller's organisation must be
``Provider.registered_by``. ``ensureMyProvider`` creates the profile from the
organisation the first time.
"""
import graphene
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.utils.text import slugify
from graphene_django import DjangoObjectType

from apps.accounts.models import Organization
from .provider_models import (Provider, ProviderStaff, ProviderService, ProviderCertification, ProviderReview,
                              EquipmentCatalog, HireBooking, VetAppointment, BUSINESS_TO_PROVIDER_TYPE, PROVIDER_TYPE_CHOICES)
from .provider_schema import (ProviderType, ProviderStaffType, ProviderServiceType, ProviderCertificationType, ProviderReviewType,
                              EquipmentCatalogType, HireBookingType, VetAppointmentType)
from .vendor_models import VendorOrder, WorkOrder, EquipmentMaintenance, ProcessingBatch, VendorInvoice
from .models import MarketListing
from .schema import MarketListingType


# ─── helpers ─────────────────────────────────────────────────────────────────

def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    if user.organization is None:
        raise Exception('No organisation on this account')
    return user.organization


def _dec(v):
    return Decimal(str(v)) if v is not None else None


def _f(v):
    return float(v) if v is not None else 0.0


def _my_provider(info, create=False):
    org = _org(info)
    p = Provider.objects.filter(registered_by=org).order_by('created_at').first()
    if p or not create:
        return p
    ptype = BUSINESS_TO_PROVIDER_TYPE.get(org.business_type or '', 'agri_services')
    base = slugify(org.name) or f'vendor-{str(org.id)[:8]}'
    slug, n = base, 1
    while Provider.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'; n += 1
    p = Provider.objects.create(provider_type=ptype, name=org.name, slug=slug, district=org.district or '', status='active',
                                coverage_districts=[org.district] if org.district else [], registered_by=org, created_by=info.context.user)
    p.refresh_from_db()  # Decimal defaults come back as Decimal, not int
    return p


def _require_provider(info):
    p = _my_provider(info)
    if p is None:
        raise Exception('No marketplace profile yet — call ensureMyProvider first')
    return p


def _owned(model, info, pk, **extra):
    p = _require_provider(info)
    obj = model.objects.filter(pk=pk, provider=p, **extra).first()
    if obj is None:
        raise Exception(f'{model.__name__} not found')
    return obj, p


def _client_fields(input, provider_id=None):
    """Resolve client org by id (must be a real organisation) or free-text name."""
    org = None
    if input.get('client_org_id'):
        org = Organization.objects.filter(id=input.client_org_id).first()
        if org is None:
            raise Exception('Client organisation not found')
    return org, (input.get('client_name') or (org.name if org else '')).strip(), (input.get('client_phone') or '').strip()


def _items_total(items):
    total = Decimal('0')
    clean = []
    for it in items or []:
        try:
            q = Decimal(str(it.get('quantity', 1) or 0)); up = Decimal(str(it.get('unit_price', 0) or 0))
        except Exception:
            raise Exception('Item quantity and unit price must be numbers')
        if q < 0 or up < 0:
            raise Exception('Item values cannot be negative')
        clean.append({'listing_id': str(it['listing_id']) if it.get('listing_id') else None, 'name': (it.get('name') or it.get('description') or '').strip(), 'description': (it.get('description') or it.get('name') or '').strip(),
                      'quantity': float(q), 'unit': it.get('unit') or '', 'unit_price': float(up), 'line_total': float(q * up)})
        total += q * up
    return clean, total


# ─── Types ────────────────────────────────────────────────────────────────────

class VendorOrderType(DjangoObjectType):
    client_org_name = graphene.String()
    items = graphene.JSONString()

    class Meta:
        model = VendorOrder
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_client_org_name(self, info):
        return self.client_org.name if self.client_org else None

    def resolve_items(self, info):
        return self.items or []


class WorkOrderType(DjangoObjectType):
    client_org_name = graphene.String()
    service_name = graphene.String()
    staff_name = graphene.String()
    equipment_name = graphene.String()

    class Meta:
        model = WorkOrder
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_client_org_name(self, info):
        return self.client_org.name if self.client_org else None

    def resolve_service_name(self, info):
        return self.service.name if self.service else None

    def resolve_staff_name(self, info):
        return self.assigned_staff.name if self.assigned_staff else None

    def resolve_equipment_name(self, info):
        return self.equipment.name if self.equipment else None


class EquipmentMaintenanceType(DjangoObjectType):
    equipment_name = graphene.String()

    class Meta:
        model = EquipmentMaintenance
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_equipment_name(self, info):
        return self.equipment.name


class ProcessingBatchType(DjangoObjectType):
    yield_pct = graphene.Float()
    source_org_name = graphene.String()
    quantity_remaining = graphene.Float()

    class Meta:
        model = ProcessingBatch
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_yield_pct(self, info):
        return self.yield_pct

    def resolve_source_org_name(self, info):
        return self.source_org.name if self.source_org else None

    def resolve_quantity_remaining(self, info):
        return _f(self.output_quantity) - _f(self.quantity_sold) if self.output_quantity is not None else None


class VendorInvoiceType(DjangoObjectType):
    client_org_name = graphene.String()
    items = graphene.JSONString()

    class Meta:
        model = VendorInvoice
        fields = '__all__'
        convert_choices_to_enum = False

    def resolve_client_org_name(self, info):
        return self.client_org.name if self.client_org else None

    def resolve_items(self, info):
        return self.items or []


class VendorClientType(graphene.ObjectType):
    key = graphene.String()
    org_id = graphene.ID()
    name = graphene.String()
    phone = graphene.String()
    district = graphene.String()
    business_type = graphene.String()
    interactions = graphene.Int()
    last_date = graphene.Date()
    total_value = graphene.Float()
    outstanding = graphene.Float()
    kinds = graphene.List(graphene.String)


class VetPatientType(graphene.ObjectType):
    key = graphene.String()
    org_id = graphene.ID()
    client_name = graphene.String()
    client_phone = graphene.String()
    species = graphene.String()
    animal_count = graphene.Int()
    visits = graphene.Int()
    last_visit = graphene.Date()
    next_follow_up = graphene.Date()
    conditions = graphene.List(graphene.String)
    medications = graphene.List(graphene.String)
    outstanding = graphene.Float()


class ClientSearchType(graphene.ObjectType):
    id = graphene.ID()
    name = graphene.String()
    district = graphene.String()
    province = graphene.String()
    business_type = graphene.String()


class VendorSummaryType(graphene.ObjectType):
    provider_id = graphene.ID()
    provider_type = graphene.String()
    status = graphene.String()
    is_verified = graphene.Boolean()
    avg_rating = graphene.Float()
    review_count = graphene.Int()
    open_bookings = graphene.Int()
    upcoming_appointments = graphene.Int()
    follow_ups_due = graphene.Int()
    open_jobs = graphene.Int()
    open_orders = graphene.Int()
    unpaid_invoices = graphene.Int()
    unpaid_amount = graphene.Float()
    revenue_30d = graphene.Float()
    revenue_ytd = graphene.Float()
    revenue_series = graphene.JSONString(description='[[YYYY-MM, amount], …] last 6 months')
    revenue_by_kind = graphene.JSONString()
    clients = graphene.Int()
    listings_active = graphene.Int()
    low_stock = graphene.Int()
    equipment_count = graphene.Int()
    equipment_available = graphene.Int()
    maintenance_due = graphene.Int()
    batches_in_process = graphene.Int()
    finished_stock = graphene.Float()
    today = graphene.Date()


# ─── Revenue engine ──────────────────────────────────────────────────────────

def revenue_events(provider):
    """(date, amount, kind) for money actually received. Invoices win over their linked records."""
    ev = []
    linked = set()
    for inv in VendorInvoice.objects.filter(provider=provider, status='paid'):
        ev.append((inv.paid_on or inv.issued_on, _f(inv.total), inv.link_type or 'invoice'))
        if inv.link_id:
            linked.add(str(inv.link_id))
    for a in VetAppointment.objects.filter(provider=provider, paid=True, total_amount__isnull=False):
        if str(a.id) not in linked:
            ev.append((a.appt_date, _f(a.total_amount), 'vet'))
    for b in HireBooking.objects.filter(provider=provider, final_paid=True, agreed_amount__isnull=False):
        if str(b.id) not in linked:
            ev.append((b.end_date, _f(b.agreed_amount), 'hire'))
    for j in WorkOrder.objects.filter(provider=provider, paid=True, agreed_amount__isnull=False):
        if str(j.id) not in linked:
            ev.append(((j.completed_at.date() if j.completed_at else j.scheduled_date) or j.created_at.date(), _f(j.agreed_amount), 'job'))
    for o in VendorOrder.objects.filter(provider=provider, paid=True):
        if str(o.id) not in linked:
            ev.append(((o.delivered_at.date() if o.delivered_at else o.delivery_date) or o.created_at.date(), _f(o.total), 'order'))
    return ev


def revenue_summary(provider):
    today = timezone.localdate()
    ev = revenue_events(provider)
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        months.append(f'{y:04d}-{m:02d}')
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    series = {k: 0.0 for k in months}
    by_kind = defaultdict(float)
    r30 = rytd = 0.0
    for d, amt, kind in ev:
        if d is None:
            continue
        k = f'{d.year:04d}-{d.month:02d}'
        if k in series:
            series[k] += amt
        if d >= today - timedelta(days=30):
            r30 += amt
        if d.year == today.year:
            rytd += amt
        by_kind[kind] += amt
    return r30, rytd, [[k, round(v, 2)] for k, v in series.items()], {k: round(v, 2) for k, v in by_kind.items()}


# ─── Queries ──────────────────────────────────────────────────────────────────

class VendorQuery(graphene.ObjectType):
    my_provider = graphene.Field(ProviderType)
    vendor_summary = graphene.Field(VendorSummaryType)
    provider_hire_bookings = graphene.List(HireBookingType, status=graphene.String())
    provider_vet_appointments = graphene.List(VetAppointmentType, status=graphene.String(), upcoming=graphene.Boolean(), with_medications=graphene.Boolean())
    vet_patients = graphene.List(VetPatientType)
    vendor_work_orders = graphene.List(WorkOrderType, status=graphene.String(), kind=graphene.String())
    vendor_orders = graphene.List(VendorOrderType, status=graphene.String())
    vendor_invoices = graphene.List(VendorInvoiceType, status=graphene.String())
    vendor_batches = graphene.List(ProcessingBatchType, status=graphene.String())
    vendor_equipment = graphene.List(EquipmentCatalogType)
    vendor_maintenance = graphene.List(EquipmentMaintenanceType, equipment_id=graphene.UUID())
    my_staff = graphene.List(ProviderStaffType)
    my_services = graphene.List(ProviderServiceType)
    my_certifications = graphene.List(ProviderCertificationType)
    my_provider_reviews = graphene.List(ProviderReviewType)
    vendor_clients = graphene.List(VendorClientType)
    vendor_listings = graphene.List(MarketListingType)
    provider_type_choices = graphene.JSONString()
    vendor_client_search = graphene.List(ClientSearchType, search=graphene.String(required=True))

    def resolve_vendor_client_search(self, info, search):
        org = _org(info)
        q = (search or '').strip()
        if len(q) < 2:
            return []
        qs = Organization.objects.filter(org_type='farm', is_active=True, name__icontains=q).exclude(id=org.id).order_by('name')[:10]
        return [ClientSearchType(id=o.id, name=o.name, district=o.district, province=o.province, business_type=o.business_type) for o in qs]

    def resolve_my_provider(self, info):
        return _my_provider(info)

    def resolve_provider_type_choices(self, info):
        return [[k, v] for k, v in PROVIDER_TYPE_CHOICES]

    def resolve_vendor_summary(self, info):
        p = _my_provider(info)
        if p is None:
            return None
        today = timezone.localdate()
        org = _org(info)
        r30, rytd, series, by_kind = revenue_summary(p)
        unpaid = VendorInvoice.objects.filter(provider=p, status__in=('sent', 'overdue'))
        listings = MarketListing.objects.filter(organization=org)
        eq = EquipmentCatalog.objects.filter(provider=p)
        batches = ProcessingBatch.objects.filter(provider=p)
        finished = sum(max(0.0, _f(b.output_quantity) - _f(b.quantity_sold)) for b in batches.filter(status='completed'))
        clients = {c.key for c in VendorQuery.resolve_vendor_clients(self, info)}
        return VendorSummaryType(
            provider_id=p.id, provider_type=p.provider_type, status=p.status, is_verified=p.is_verified, avg_rating=_f(p.avg_rating), review_count=p.review_count,
            open_bookings=HireBooking.objects.filter(provider=p, status__in=('enquiry', 'quoted', 'confirmed', 'active')).count(),
            upcoming_appointments=VetAppointment.objects.filter(provider=p, appt_date__gte=today, status__in=('requested', 'confirmed')).count(),
            follow_ups_due=VetAppointment.objects.filter(provider=p, follow_up_date__isnull=False, follow_up_date__lte=today + timedelta(days=7)).exclude(status='cancelled').count(),
            open_jobs=WorkOrder.objects.filter(provider=p, status__in=('requested', 'quoted', 'scheduled', 'in_progress')).count(),
            open_orders=VendorOrder.objects.filter(provider=p, status__in=('new', 'confirmed', 'packed', 'out_for_delivery')).count(),
            unpaid_invoices=unpaid.count(), unpaid_amount=_f(unpaid.aggregate(v=Sum('total'))['v']),
            revenue_30d=round(r30, 2), revenue_ytd=round(rytd, 2), revenue_series=series, revenue_by_kind=by_kind,
            clients=len(clients), listings_active=listings.filter(status='active').count(),
            low_stock=listings.filter(status='active', quantity_available__lte=Decimal('10')).count(),
            equipment_count=eq.count(), equipment_available=eq.filter(is_available=True).count(),
            maintenance_due=EquipmentMaintenance.objects.filter(equipment__provider=p, next_due_date__isnull=False, next_due_date__lte=today + timedelta(days=14)).values('equipment').distinct().count(),
            batches_in_process=batches.filter(status__in=('received', 'processing')).count(), finished_stock=round(finished, 2), today=today,
        )

    def resolve_provider_hire_bookings(self, info, status=None):
        p = _require_provider(info)
        qs = HireBooking.objects.filter(provider=p).select_related('organization', 'equipment')
        return qs.filter(status=status) if status else qs

    def resolve_provider_vet_appointments(self, info, status=None, upcoming=None, with_medications=None):
        p = _require_provider(info)
        qs = VetAppointment.objects.filter(provider=p).select_related('organization', 'vet_officer')
        if status:
            qs = qs.filter(status=status)
        if upcoming:
            qs = qs.filter(appt_date__gte=timezone.localdate()).exclude(status__in=('completed', 'cancelled', 'no_show')).order_by('appt_date', 'appt_time')
        if with_medications:
            qs = [a for a in qs if a.medications]
        return qs

    def resolve_vet_patients(self, info):
        p = _require_provider(info)
        groups = {}
        for a in VetAppointment.objects.filter(provider=p).exclude(status='cancelled').select_related('organization').order_by('appt_date'):
            name = a.organization.name if a.organization else (a.client_name or 'Walk-in')
            key = f"{a.organization_id or name}|{(a.species or 'unspecified').lower()}"
            g = groups.setdefault(key, dict(key=key, org_id=a.organization_id, client_name=name, client_phone=a.client_phone or '', species=a.species or 'Unspecified',
                                            animal_count=0, visits=0, last_visit=None, next_follow_up=None, conditions=[], medications=[], outstanding=0.0))
            g['visits'] += 1
            g['animal_count'] = max(g['animal_count'], a.animal_count or 0)
            g['last_visit'] = a.appt_date
            if a.follow_up_date and a.follow_up_date >= timezone.localdate() and (g['next_follow_up'] is None or a.follow_up_date < g['next_follow_up']):
                g['next_follow_up'] = a.follow_up_date
            if a.diagnosis and a.diagnosis not in g['conditions']:
                g['conditions'].append(a.diagnosis)
            for m in a.medications or []:
                nm = m.get('name') if isinstance(m, dict) else str(m)
                if nm and nm not in g['medications']:
                    g['medications'].append(nm)
            if a.total_amount and not a.paid:
                g['outstanding'] += _f(a.total_amount)
        return [VetPatientType(**g) for g in sorted(groups.values(), key=lambda g: (g['last_visit'] or date.min), reverse=True)]

    def resolve_vendor_work_orders(self, info, status=None, kind=None):
        p = _require_provider(info)
        qs = WorkOrder.objects.filter(provider=p)
        if status:
            qs = qs.filter(status=status)
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def resolve_vendor_orders(self, info, status=None):
        p = _require_provider(info)
        qs = VendorOrder.objects.filter(provider=p)
        return qs.filter(status=status) if status else qs

    def resolve_vendor_invoices(self, info, status=None):
        p = _require_provider(info)
        today = timezone.localdate()
        VendorInvoice.objects.filter(provider=p, status='sent', due_on__lt=today).update(status='overdue')
        qs = VendorInvoice.objects.filter(provider=p)
        return qs.filter(status=status) if status else qs

    def resolve_vendor_batches(self, info, status=None):
        p = _require_provider(info)
        qs = ProcessingBatch.objects.filter(provider=p)
        return qs.filter(status=status) if status else qs

    def resolve_vendor_equipment(self, info):
        return EquipmentCatalog.objects.filter(provider=_require_provider(info))

    def resolve_vendor_maintenance(self, info, equipment_id=None):
        qs = EquipmentMaintenance.objects.filter(equipment__provider=_require_provider(info))
        return qs.filter(equipment_id=equipment_id) if equipment_id else qs

    def resolve_my_staff(self, info):
        return ProviderStaff.objects.filter(provider=_require_provider(info))

    def resolve_my_services(self, info):
        return ProviderService.objects.filter(provider=_require_provider(info))

    def resolve_my_certifications(self, info):
        return ProviderCertification.objects.filter(provider=_require_provider(info))

    def resolve_my_provider_reviews(self, info):
        return ProviderReview.objects.filter(provider=_require_provider(info))

    def resolve_vendor_listings(self, info):
        return MarketListing.objects.filter(organization=_org(info)).exclude(status='cancelled')

    def resolve_vendor_clients(self, info):
        p = _my_provider(info)
        if p is None:
            return []
        acc = {}

        def add(org, name, phone, d, value, kind, outstanding=0.0):
            key = str(org.id) if org else f'walkin:{(name or "").strip().lower()}'
            c = acc.setdefault(key, dict(key=key, org_id=org.id if org else None, name=(org.name if org else name) or 'Walk-in', phone=phone or '',
                                         district=(org.district if org else '') or '', business_type=(org.business_type if org else '') or '', interactions=0,
                                         last_date=None, total_value=0.0, outstanding=0.0, kinds=set()))
            c['interactions'] += 1
            if d and (c['last_date'] is None or d > c['last_date']):
                c['last_date'] = d
            c['total_value'] += value
            c['outstanding'] += outstanding
            c['kinds'].add(kind)
            if not c['phone'] and phone:
                c['phone'] = phone

        for b in HireBooking.objects.filter(provider=p).select_related('organization'):
            add(b.organization, b.client_name, b.client_phone, b.start_date, _f(b.agreed_amount), 'hire', 0.0 if b.final_paid else _f(b.agreed_amount))
        for a in VetAppointment.objects.filter(provider=p).select_related('organization'):
            add(a.organization, a.client_name, a.client_phone, a.appt_date, _f(a.total_amount), 'vet', 0.0 if a.paid else _f(a.total_amount))
        for j in WorkOrder.objects.filter(provider=p).select_related('client_org'):
            add(j.client_org, j.client_name, j.client_phone, j.scheduled_date or j.created_at.date(), _f(j.agreed_amount), 'job', 0.0 if j.paid else _f(j.agreed_amount))
        for o in VendorOrder.objects.filter(provider=p).select_related('client_org'):
            add(o.client_org, o.client_name, o.client_phone, o.created_at.date(), _f(o.total), 'order', 0.0 if o.paid else _f(o.total))
        for b in ProcessingBatch.objects.filter(provider=p).select_related('source_org'):
            add(b.source_org, b.source_name, '', b.received_on, 0.0, 'supplier')
        out = []
        for c in acc.values():
            c['kinds'] = sorted(c['kinds'])
            c['total_value'] = round(c['total_value'], 2); c['outstanding'] = round(c['outstanding'], 2)
            out.append(VendorClientType(**c))
        return sorted(out, key=lambda c: (c.last_date or date.min), reverse=True)


# ─── Inputs ──────────────────────────────────────────────────────────────────

class VendorProfileInput(graphene.InputObjectType):
    provider_type = graphene.String()
    name = graphene.String()
    tagline = graphene.String()
    description = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    website = graphene.String()
    whatsapp = graphene.String()
    district = graphene.String()
    town = graphene.String()
    address = graphene.String()
    coverage_districts = graphene.List(graphene.String)
    mobile_service = graphene.Boolean()
    emergency_available = graphene.Boolean()
    service_hours = graphene.String()
    tags = graphene.List(graphene.String)
    specialties = graphene.List(graphene.String)
    year_established = graphene.Int()
    business_reg_no = graphene.String()
    tax_id = graphene.String()
    logo_url = graphene.String()
    latitude = graphene.Float()
    longitude = graphene.Float()


class StaffInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    role = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    bio = graphene.String()
    qualifications = graphene.List(graphene.String)
    licence_no = graphene.String()
    active = graphene.Boolean()


class ServiceInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    description = graphene.String()
    category = graphene.String()
    pricing_model = graphene.String()
    price = graphene.Float()
    price_max = graphene.Float()
    currency = graphene.String()
    unit_label = graphene.String()
    lead_time_days = graphene.Int()
    is_available = graphene.Boolean()
    notes = graphene.String()


class CertificationInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    issuing_body = graphene.String()
    cert_number = graphene.String()
    issued_date = graphene.Date()
    expiry_date = graphene.Date()
    status = graphene.String()
    document_url = graphene.String()


class EquipmentInput(graphene.InputObjectType):
    equipment_type = graphene.String(required=True)
    name = graphene.String(required=True)
    make = graphene.String()
    model = graphene.String()
    year = graphene.Int()
    capacity = graphene.String()
    daily_rate = graphene.Float()
    per_ha_rate = graphene.Float()
    currency = graphene.String()
    operator_included = graphene.Boolean()
    fuel_included = graphene.Boolean()
    min_hire_days = graphene.Int()
    is_available = graphene.Boolean()
    notes = graphene.String()


class MaintenanceInput(graphene.InputObjectType):
    equipment_id = graphene.UUID(required=True)
    kind = graphene.String()
    date = graphene.Date(required=True)
    description = graphene.String(required=True)
    cost = graphene.Float()
    hours_reading = graphene.Float()
    downtime_days = graphene.Int()
    next_due_date = graphene.Date()
    performed_by = graphene.String()
    notes = graphene.String()


class ClientMixin:
    client_org_id = graphene.ID()
    client_name = graphene.String()
    client_phone = graphene.String()


class ProviderBookingInput(ClientMixin, graphene.InputObjectType):
    equipment_id = graphene.UUID()
    start_date = graphene.Date(required=True)
    end_date = graphene.Date(required=True)
    hectares = graphene.Float()
    status = graphene.String()
    quoted_amount = graphene.Float()
    agreed_amount = graphene.Float()
    deposit_paid = graphene.Boolean()
    final_paid = graphene.Boolean()
    delivery_address = graphene.String()
    provider_notes = graphene.String()


class HireBookingUpdateInput(graphene.InputObjectType):
    status = graphene.String()
    equipment_id = graphene.UUID()
    start_date = graphene.Date()
    end_date = graphene.Date()
    quoted_amount = graphene.Float()
    agreed_amount = graphene.Float()
    deposit_paid = graphene.Boolean()
    final_paid = graphene.Boolean()
    provider_notes = graphene.String()


class ProviderAppointmentInput(ClientMixin, graphene.InputObjectType):
    appt_type = graphene.String(required=True)
    appt_date = graphene.Date(required=True)
    appt_time = graphene.Time()
    vet_officer_id = graphene.UUID()
    species = graphene.String()
    animal_count = graphene.Int()
    symptoms = graphene.String()
    consultation_fee = graphene.Float()
    status = graphene.String()


class MedicationInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    dose = graphene.String()
    route = graphene.String()
    days = graphene.Int()
    withdrawal_days = graphene.Int()
    notes = graphene.String()


class VetOutcomeInput(graphene.InputObjectType):
    status = graphene.String()
    appt_date = graphene.Date()
    appt_time = graphene.Time()
    vet_officer_id = graphene.UUID()
    species = graphene.String()
    animal_count = graphene.Int()
    symptoms = graphene.String()
    diagnosis = graphene.String()
    treatment_given = graphene.String()
    medications = graphene.List(MedicationInput)
    follow_up_date = graphene.Date()
    outcome_notes = graphene.String()
    consultation_fee = graphene.Float()
    total_amount = graphene.Float()
    paid = graphene.Boolean()


class WorkOrderInput(ClientMixin, graphene.InputObjectType):
    service_id = graphene.UUID()
    kind = graphene.String()
    title = graphene.String(required=True)
    description = graphene.String()
    location = graphene.String()
    destination = graphene.String()
    district = graphene.String()
    distance_km = graphene.Float()
    quantity = graphene.Float()
    unit = graphene.String()
    scheduled_date = graphene.Date()
    scheduled_time = graphene.Time()
    assigned_staff_id = graphene.UUID()
    equipment_id = graphene.UUID()
    status = graphene.String()
    quoted_amount = graphene.Float()
    agreed_amount = graphene.Float()
    paid = graphene.Boolean()
    completion_notes = graphene.String()
    notes = graphene.String()


class OrderItemInput(graphene.InputObjectType):
    listing_id = graphene.UUID()
    name = graphene.String(required=True)
    quantity = graphene.Float(required=True)
    unit = graphene.String()
    unit_price = graphene.Float(required=True)


class VendorOrderInput(ClientMixin, graphene.InputObjectType):
    source = graphene.String()
    items = graphene.List(OrderItemInput)
    discount = graphene.Float()
    status = graphene.String()
    delivery_required = graphene.Boolean()
    delivery_address = graphene.String()
    delivery_date = graphene.Date()
    paid = graphene.Boolean()
    notes = graphene.String()


class BatchInput(graphene.InputObjectType):
    source_org_id = graphene.ID()
    source_name = graphene.String()
    source_district = graphene.String()
    input_commodity = graphene.String(required=True)
    input_quantity = graphene.Float(required=True)
    input_unit = graphene.String()
    price_paid = graphene.Float()
    received_on = graphene.Date(required=True)
    product = graphene.String()
    output_quantity = graphene.Float()
    output_unit = graphene.String()
    quantity_sold = graphene.Float()
    started_on = graphene.Date()
    completed_on = graphene.Date()
    expiry_date = graphene.Date()
    status = graphene.String()
    qc_passed = graphene.Boolean()
    qc_notes = graphene.String()
    notes = graphene.String()


class InvoiceItemInput(graphene.InputObjectType):
    description = graphene.String(required=True)
    quantity = graphene.Float(required=True)
    unit_price = graphene.Float(required=True)


class InvoiceInput(ClientMixin, graphene.InputObjectType):
    items = graphene.List(InvoiceItemInput)
    tax = graphene.Float()
    issued_on = graphene.Date()
    due_on = graphene.Date()
    notes = graphene.String()
    link_type = graphene.String()
    link_id = graphene.UUID()
    status = graphene.String()


class ListingUpdateInput(graphene.InputObjectType):
    commodity = graphene.String()
    description = graphene.String()
    quantity_available = graphene.Float()
    unit = graphene.String()
    asking_price = graphene.Float()
    min_order_quantity = graphene.Float()
    status = graphene.String()
    delivery_available = graphene.Boolean()
    location = graphene.String()
    available_until = graphene.Date()


# ─── Mutations ───────────────────────────────────────────────────────────────

def _apply(obj, input, fields, decimals=()):
    for f in fields:
        if f in input and input.get(f) is not None:
            v = input[f]
            setattr(obj, f, _dec(v) if f in decimals else (v.strip() if isinstance(v, str) else v))


def _check_choice(value, choices, label):
    if value is not None and value not in dict(choices):
        raise Exception(f'Invalid {label}: {value}')


class EnsureMyProvider(graphene.Mutation):
    class Arguments:
        input = VendorProfileInput()

    provider = graphene.Field(ProviderType)
    created = graphene.Boolean()

    def mutate(self, info, input=None):
        existed = _my_provider(info) is not None
        p = _my_provider(info, create=True)
        if input:
            UpdateMyProvider.apply(p, input)
        return EnsureMyProvider(provider=p, created=not existed)


class UpdateMyProvider(graphene.Mutation):
    class Arguments:
        input = VendorProfileInput(required=True)

    provider = graphene.Field(ProviderType)

    @staticmethod
    def apply(p, input):
        if input.get('provider_type'):
            _check_choice(input.provider_type, PROVIDER_TYPE_CHOICES, 'provider type')
            p.provider_type = input.provider_type
        _apply(p, input, ['name', 'tagline', 'description', 'phone', 'email', 'website', 'whatsapp', 'district', 'town', 'address', 'service_hours',
                          'year_established', 'business_reg_no', 'tax_id', 'logo_url', 'mobile_service', 'emergency_available', 'coverage_districts', 'tags', 'specialties'])
        if input.get('latitude') is not None:
            p.latitude = _dec(input.latitude)
        if input.get('longitude') is not None:
            p.longitude = _dec(input.longitude)
        if not p.name:
            raise Exception('Name is required')
        p.save()

    def mutate(self, info, input):
        p = _require_provider(info)
        UpdateMyProvider.apply(p, input)
        return UpdateMyProvider(provider=p)


class UpsertStaff(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = StaffInput(required=True)

    staff = graphene.Field(ProviderStaffType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        s = ProviderStaff.objects.filter(pk=id, provider=p).first() if id else ProviderStaff(provider=p)
        if id and s is None:
            raise Exception('Staff member not found')
        _check_choice(input.get('role'), ProviderStaff.ROLE_CHOICES, 'role')
        _apply(s, input, ['name', 'role', 'phone', 'email', 'bio', 'qualifications', 'licence_no', 'active'])
        s.save()
        return UpsertStaff(staff=s)


class DeleteStaff(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        s, _ = _owned(ProviderStaff, info, id)
        s.delete()
        return DeleteStaff(ok=True)


class UpsertService(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = ServiceInput(required=True)

    service = graphene.Field(ProviderServiceType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        s = ProviderService.objects.filter(pk=id, provider=p).first() if id else ProviderService(provider=p)
        if id and s is None:
            raise Exception('Service not found')
        _check_choice(input.get('pricing_model'), ProviderService.PRICING_MODEL_CHOICES, 'pricing model')
        _apply(s, input, ['name', 'description', 'category', 'pricing_model', 'price', 'price_max', 'currency', 'unit_label', 'lead_time_days', 'is_available', 'notes'], decimals=('price', 'price_max'))
        s.save()
        return UpsertService(service=s)


class DeleteService(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        s, _ = _owned(ProviderService, info, id)
        s.delete()
        return DeleteService(ok=True)


class UpsertCertification(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = CertificationInput(required=True)

    certification = graphene.Field(ProviderCertificationType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        c = ProviderCertification.objects.filter(pk=id, provider=p).first() if id else ProviderCertification(provider=p)
        if id and c is None:
            raise Exception('Certification not found')
        _check_choice(input.get('status'), ProviderCertification.STATUS_CHOICES, 'status')
        _apply(c, input, ['name', 'issuing_body', 'cert_number', 'issued_date', 'expiry_date', 'status', 'document_url'])
        if c.expiry_date and c.expiry_date < timezone.localdate():
            c.status = 'expired'
        c.save()
        return UpsertCertification(certification=c)


class DeleteCertification(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        c, _ = _owned(ProviderCertification, info, id)
        c.delete()
        return DeleteCertification(ok=True)


class UpsertEquipment(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = EquipmentInput(required=True)

    equipment = graphene.Field(EquipmentCatalogType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        e = EquipmentCatalog.objects.filter(pk=id, provider=p).first() if id else EquipmentCatalog(provider=p)
        if id and e is None:
            raise Exception('Equipment not found')
        _check_choice(input.get('equipment_type'), EquipmentCatalog.EQUIPMENT_TYPE_CHOICES, 'equipment type')
        _apply(e, input, ['equipment_type', 'name', 'make', 'model', 'year', 'capacity', 'daily_rate', 'per_ha_rate', 'currency', 'operator_included', 'fuel_included', 'min_hire_days', 'is_available', 'notes'],
               decimals=('daily_rate', 'per_ha_rate'))
        e.save()
        return UpsertEquipment(equipment=e)


class DeleteEquipment(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        e, _ = _owned(EquipmentCatalog, info, id)
        if e.bookings.filter(status__in=('confirmed', 'active')).exists():
            raise Exception('Equipment has confirmed or active bookings — mark it unavailable instead')
        e.delete()
        return DeleteEquipment(ok=True)


class AddMaintenance(graphene.Mutation):
    class Arguments:
        input = MaintenanceInput(required=True)

    record = graphene.Field(EquipmentMaintenanceType)

    def mutate(self, info, input):
        e, _ = _owned(EquipmentCatalog, info, input.equipment_id)
        _check_choice(input.get('kind'), EquipmentMaintenance.KIND_CHOICES, 'kind')
        r = EquipmentMaintenance(equipment=e)
        _apply(r, input, ['kind', 'date', 'description', 'cost', 'hours_reading', 'downtime_days', 'next_due_date', 'performed_by', 'notes'], decimals=('cost', 'hours_reading'))
        r.save()
        if input.get('downtime_days'):
            pass
        return AddMaintenance(record=r)


class DeleteMaintenance(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        p = _require_provider(info)
        r = EquipmentMaintenance.objects.filter(pk=id, equipment__provider=p).first()
        if r is None:
            raise Exception('Record not found')
        r.delete()
        return DeleteMaintenance(ok=True)


class CreateProviderBooking(graphene.Mutation):
    """A hire booking entered by the provider (walk-in or phone customer)."""
    class Arguments:
        input = ProviderBookingInput(required=True)

    booking = graphene.Field(HireBookingType)

    def mutate(self, info, input):
        p = _require_provider(info)
        org, name, phone = _client_fields(input)
        if not org and not name:
            raise Exception('Give a client organisation or a client name')
        if input.end_date < input.start_date:
            raise Exception('End date must be on or after the start date')
        eq = None
        if input.get('equipment_id'):
            eq = EquipmentCatalog.objects.filter(pk=input.equipment_id, provider=p).first()
            if eq is None:
                raise Exception('Equipment not found')
        _check_choice(input.get('status'), HireBooking.STATUS_CHOICES, 'status')
        b = HireBooking(provider=p, equipment=eq, organization=org, client_name=name, client_phone=phone, requested_by=info.context.user,
                        start_date=input.start_date, end_date=input.end_date, status=input.get('status') or 'confirmed')
        _apply(b, input, ['hectares', 'quoted_amount', 'agreed_amount', 'deposit_paid', 'final_paid', 'delivery_address', 'provider_notes'], decimals=('hectares', 'quoted_amount', 'agreed_amount'))
        b.save()
        p.booking_count = p.hire_bookings.count() + p.vet_appointments.count()
        p.save(update_fields=['booking_count'])
        return CreateProviderBooking(booking=b)


class VendorUpdateHireBooking(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        input = HireBookingUpdateInput(required=True)

    booking = graphene.Field(HireBookingType)

    def mutate(self, info, id, input):
        b, p = _owned(HireBooking, info, id)
        _check_choice(input.get('status'), HireBooking.STATUS_CHOICES, 'status')
        if input.get('equipment_id'):
            eq = EquipmentCatalog.objects.filter(pk=input.equipment_id, provider=p).first()
            if eq is None:
                raise Exception('Equipment not found')
            b.equipment = eq
        _apply(b, input, ['status', 'start_date', 'end_date', 'quoted_amount', 'agreed_amount', 'deposit_paid', 'final_paid', 'provider_notes'], decimals=('quoted_amount', 'agreed_amount'))
        if b.end_date < b.start_date:
            raise Exception('End date must be on or after the start date')
        if input.get('status') == 'quoted' and b.quoted_amount is None:
            raise Exception('Enter a quoted amount to send a quote')
        b.save()
        return VendorUpdateHireBooking(booking=b)


class CreateProviderAppointment(graphene.Mutation):
    """A vet appointment entered by the practice (walk-in / phone / field call)."""
    class Arguments:
        input = ProviderAppointmentInput(required=True)

    appointment = graphene.Field(VetAppointmentType)

    def mutate(self, info, input):
        p = _require_provider(info)
        org, name, phone = _client_fields(input)
        if not org and not name:
            raise Exception('Give a client organisation or a client name')
        _check_choice(input.appt_type, VetAppointment.TYPE_CHOICES, 'appointment type')
        _check_choice(input.get('status'), VetAppointment.STATUS_CHOICES, 'status')
        vo = None
        if input.get('vet_officer_id'):
            vo = ProviderStaff.objects.filter(pk=input.vet_officer_id, provider=p).first()
            if vo is None:
                raise Exception('Vet officer not found')
        a = VetAppointment(provider=p, organization=org, client_name=name, client_phone=phone, requested_by=info.context.user, vet_officer=vo,
                           appt_type=input.appt_type, appt_date=input.appt_date, appt_time=input.get('appt_time'), status=input.get('status') or 'confirmed')
        _apply(a, input, ['species', 'animal_count', 'symptoms', 'consultation_fee'], decimals=('consultation_fee',))
        a.save()
        p.booking_count = p.hire_bookings.count() + p.vet_appointments.count()
        p.save(update_fields=['booking_count'])
        return CreateProviderAppointment(appointment=a)


class VendorUpdateVetAppointment(graphene.Mutation):
    """Practice-side update: schedule, officer, clinical outcome, prescription, billing."""
    class Arguments:
        id = graphene.UUID(required=True)
        input = VetOutcomeInput(required=True)

    appointment = graphene.Field(VetAppointmentType)

    def mutate(self, info, id, input):
        a, p = _owned(VetAppointment, info, id)
        _check_choice(input.get('status'), VetAppointment.STATUS_CHOICES, 'status')
        if input.get('vet_officer_id'):
            vo = ProviderStaff.objects.filter(pk=input.vet_officer_id, provider=p).first()
            if vo is None:
                raise Exception('Vet officer not found')
            a.vet_officer = vo
        if input.get('medications') is not None:
            meds = []
            for m in input.medications:
                if not (m.name or '').strip():
                    continue
                meds.append({'name': m.name.strip(), 'dose': (m.get('dose') or '').strip(), 'route': (m.get('route') or '').strip(),
                             'days': m.get('days'), 'withdrawal_days': m.get('withdrawal_days'), 'notes': (m.get('notes') or '').strip()})
            a.medications = meds
        _apply(a, input, ['status', 'appt_date', 'appt_time', 'species', 'animal_count', 'symptoms', 'diagnosis', 'treatment_given', 'follow_up_date', 'outcome_notes',
                          'consultation_fee', 'total_amount', 'paid'], decimals=('consultation_fee', 'total_amount'))
        if a.total_amount is None and a.consultation_fee is not None:
            a.total_amount = a.consultation_fee
        a.save()
        return VendorUpdateVetAppointment(appointment=a)


class UpsertWorkOrder(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = WorkOrderInput(required=True)

    job = graphene.Field(WorkOrderType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        j = WorkOrder.objects.filter(pk=id, provider=p).first() if id else WorkOrder(provider=p, created_by=info.context.user)
        if id and j is None:
            raise Exception('Job not found')
        _check_choice(input.get('kind'), WorkOrder.KIND_CHOICES, 'kind')
        _check_choice(input.get('status'), WorkOrder.STATUS_CHOICES, 'status')
        if any(k in input for k in ('client_org_id', 'client_name', 'client_phone')):
            org, name, phone = _client_fields(input)
            if org or name:
                j.client_org, j.client_name, j.client_phone = org, name, phone
        for fk, model, attr in (('service_id', ProviderService, 'service'), ('assigned_staff_id', ProviderStaff, 'assigned_staff'), ('equipment_id', EquipmentCatalog, 'equipment')):
            if input.get(fk):
                obj = model.objects.filter(pk=input[fk], provider=p).first()
                if obj is None:
                    raise Exception(f'{attr.replace("_", " ").title()} not found')
                setattr(j, attr, obj)
        _apply(j, input, ['kind', 'title', 'description', 'location', 'destination', 'district', 'distance_km', 'quantity', 'unit', 'scheduled_date', 'scheduled_time', 'status',
                          'quoted_amount', 'agreed_amount', 'paid', 'completion_notes', 'notes'], decimals=('distance_km', 'quantity', 'quoted_amount', 'agreed_amount'))
        if not j.client_org and not j.client_name:
            raise Exception('Give a client organisation or a client name')
        if j.status == 'completed' and not j.completed_at:
            j.completed_at = timezone.now()
        j.save()
        return UpsertWorkOrder(job=j)


class DeleteWorkOrder(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        j, _ = _owned(WorkOrder, info, id)
        j.delete()
        return DeleteWorkOrder(ok=True)


class UpsertVendorOrder(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = VendorOrderInput(required=True)

    order = graphene.Field(VendorOrderType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        org_self = _org(info)
        o = VendorOrder.objects.filter(pk=id, provider=p).first() if id else VendorOrder(provider=p, created_by=info.context.user)
        if id and o is None:
            raise Exception('Order not found')
        _check_choice(input.get('source'), VendorOrder.SOURCE_CHOICES, 'source')
        _check_choice(input.get('status'), VendorOrder.STATUS_CHOICES, 'status')
        if any(k in input for k in ('client_org_id', 'client_name', 'client_phone')):
            org, name, phone = _client_fields(input)
            if org or name:
                o.client_org, o.client_name, o.client_phone = org, name, phone
        prev_status = o.status if id else None
        if input.get('items') is not None:
            items, subtotal = _items_total([dict(i) for i in input.items])
            if not items:
                raise Exception('An order needs at least one item')
            o.items, o.subtotal = items, subtotal
        _apply(o, input, ['source', 'status', 'delivery_required', 'delivery_address', 'delivery_date', 'paid', 'notes', 'discount'], decimals=('discount',))
        o.total = max(Decimal('0'), Decimal(str(o.subtotal)) - Decimal(str(o.discount or 0)))
        if not o.client_org and not o.client_name:
            raise Exception('Give a client organisation or a client name')
        if o.status == 'delivered' and not o.delivered_at:
            o.delivered_at = timezone.now()
        o.save()
        # stock: decrement linked listings once when the order is confirmed
        if prev_status in (None, 'new') and o.status in ('confirmed', 'packed', 'out_for_delivery', 'delivered'):
            for it in o.items:
                if it.get('listing_id'):
                    lst = MarketListing.objects.filter(pk=it['listing_id'], organization=org_self).first()
                    if lst:
                        lst.quantity_available = max(Decimal('0'), Decimal(str(lst.quantity_available)) - Decimal(str(it['quantity'])))
                        if lst.quantity_available == 0 and lst.status == 'active':
                            lst.status = 'sold'
                        lst.save(update_fields=['quantity_available', 'status'])
        return UpsertVendorOrder(order=o)


class DeleteVendorOrder(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        o, _ = _owned(VendorOrder, info, id)
        if o.status not in ('new', 'cancelled'):
            raise Exception('Only new or cancelled orders can be deleted')
        o.delete()
        return DeleteVendorOrder(ok=True)


class UpsertBatch(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        input = BatchInput(required=True)

    batch = graphene.Field(ProcessingBatchType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        b = ProcessingBatch.objects.filter(pk=id, provider=p).first() if id else ProcessingBatch(provider=p, created_by=info.context.user)
        if id and b is None:
            raise Exception('Batch not found')
        _check_choice(input.get('status'), ProcessingBatch.STATUS_CHOICES, 'status')
        if input.get('source_org_id'):
            so = Organization.objects.filter(id=input.source_org_id).first()
            if so is None:
                raise Exception('Source organisation not found')
            b.source_org = so
            if not input.get('source_name'):
                b.source_name = so.name
            if not input.get('source_district'):
                b.source_district = so.district or ''
        _apply(b, input, ['source_name', 'source_district', 'input_commodity', 'input_quantity', 'input_unit', 'price_paid', 'received_on', 'product', 'output_quantity', 'output_unit',
                          'quantity_sold', 'started_on', 'completed_on', 'expiry_date', 'status', 'qc_passed', 'qc_notes', 'notes'],
               decimals=('input_quantity', 'price_paid', 'output_quantity', 'quantity_sold'))
        if b.input_quantity is not None and b.input_quantity <= 0:
            raise Exception('Input quantity must be positive')
        if b.status == 'completed' and not b.completed_on:
            b.completed_on = timezone.localdate()
        if b.status == 'processing' and not b.started_on:
            b.started_on = timezone.localdate()
        b.save()
        return UpsertBatch(batch=b)


class DeleteBatch(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        b, _ = _owned(ProcessingBatch, info, id)
        b.delete()
        return DeleteBatch(ok=True)


LINKS = {'hire': HireBooking, 'vet': VetAppointment, 'job': WorkOrder, 'order': VendorOrder}


class UpsertInvoice(graphene.Mutation):
    """Create or edit an invoice. With link_type + link_id and no items, the items are built from the linked record."""
    class Arguments:
        id = graphene.UUID()
        input = InvoiceInput(required=True)

    invoice = graphene.Field(VendorInvoiceType)

    def mutate(self, info, input, id=None):
        p = _require_provider(info)
        inv = VendorInvoice.objects.filter(pk=id, provider=p).first() if id else VendorInvoice(provider=p, created_by=info.context.user, issued_on=timezone.localdate())
        if id and inv is None:
            raise Exception('Invoice not found')
        if id and inv.status in ('paid', 'void'):
            raise Exception('Paid or void invoices cannot be edited')
        _check_choice(input.get('status'), VendorInvoice.STATUS_CHOICES, 'status')
        if any(k in input for k in ('client_org_id', 'client_name', 'client_phone')):
            org, name, phone = _client_fields(input)
            if org or name:
                inv.client_org, inv.client_name, inv.client_phone = org, name, phone
        items = None
        if input.get('link_type'):
            model = LINKS.get(input.link_type)
            if model is None:
                raise Exception('Unknown link type')
            rec = model.objects.filter(pk=input.get('link_id'), provider=p).first()
            if rec is None:
                raise Exception('Linked record not found')
            inv.link_type, inv.link_id = input.link_type, rec.id
            inv.link_ref = getattr(rec, 'booking_ref', None) or getattr(rec, 'appt_ref', None) or getattr(rec, 'job_ref', None) or getattr(rec, 'order_ref', '')
            corg = getattr(rec, 'organization', None) or getattr(rec, 'client_org', None)
            if not inv.client_org and not inv.client_name:
                inv.client_org, inv.client_name, inv.client_phone = corg, (corg.name if corg else rec.client_name), rec.client_phone
            if not input.get('items'):
                if input.link_type == 'order':
                    items = rec.items
                elif input.link_type == 'hire':
                    days = (rec.end_date - rec.start_date).days + 1
                    items = [{'description': f'Hire of {rec.equipment.name if rec.equipment else "equipment"} {rec.start_date} → {rec.end_date}', 'quantity': 1, 'unit_price': _f(rec.agreed_amount or rec.quoted_amount), 'unit': f'{days} day(s)'}]
                elif input.link_type == 'vet':
                    items = [{'description': f'{rec.get_appt_type_display()} — {rec.species or "animals"} ({rec.animal_count} head) on {rec.appt_date}', 'quantity': 1, 'unit_price': _f(rec.total_amount or rec.consultation_fee)}]
                    for m in rec.medications or []:
                        if m.get('name'):
                            items.append({'description': f"Medication: {m['name']} {m.get('dose', '')}".strip(), 'quantity': 1, 'unit_price': 0})
                else:
                    items = [{'description': rec.title, 'quantity': _f(rec.quantity) or 1, 'unit': rec.unit, 'unit_price': (_f(rec.agreed_amount or rec.quoted_amount) / (_f(rec.quantity) or 1))}]
        if input.get('items') is not None:
            items = [dict(i) for i in input.items]
        if items is not None:
            clean, subtotal = _items_total(items)
            if not clean:
                raise Exception('An invoice needs at least one line')
            inv.items, inv.subtotal = clean, subtotal
        _apply(inv, input, ['tax', 'issued_on', 'due_on', 'notes', 'status'], decimals=('tax',))
        inv.total = Decimal(str(inv.subtotal)) + Decimal(str(inv.tax or 0))
        if not inv.client_org and not inv.client_name:
            raise Exception('Give a client organisation or a client name')
        if not inv.due_on:
            inv.due_on = inv.issued_on + timedelta(days=14)
        inv.save()
        return UpsertInvoice(invoice=inv)


class SetInvoiceStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)
        paid_on = graphene.Date()
        payment_method = graphene.String()

    invoice = graphene.Field(VendorInvoiceType)

    def mutate(self, info, id, status, paid_on=None, payment_method=None):
        inv, p = _owned(VendorInvoice, info, id)
        _check_choice(status, VendorInvoice.STATUS_CHOICES, 'status')
        inv.status = status
        if status == 'paid':
            inv.paid_on = paid_on or timezone.localdate()
            inv.payment_method = (payment_method or inv.payment_method or 'cash').strip()
            # mark the linked record paid too
            model = LINKS.get(inv.link_type)
            if model and inv.link_id:
                rec = model.objects.filter(pk=inv.link_id, provider=p).first()
                if rec is not None:
                    if hasattr(rec, 'final_paid'):
                        rec.final_paid = True
                    elif hasattr(rec, 'paid'):
                        rec.paid = True
                    rec.save()
        inv.save()
        return SetInvoiceStatus(invoice=inv)


class DeleteInvoice(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        inv, _ = _owned(VendorInvoice, info, id)
        if inv.status != 'draft':
            raise Exception('Only draft invoices can be deleted — void it instead')
        inv.delete()
        return DeleteInvoice(ok=True)


class UpdateListing(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        input = ListingUpdateInput(required=True)

    listing = graphene.Field(MarketListingType)

    def mutate(self, info, id, input):
        org = _org(info)
        lst = MarketListing.objects.filter(pk=id, organization=org).first()
        if lst is None:
            raise Exception('Listing not found')
        _check_choice(input.get('status'), MarketListing.STATUS_CHOICES, 'status')
        _apply(lst, input, ['commodity', 'description', 'quantity_available', 'unit', 'asking_price', 'min_order_quantity', 'status', 'delivery_available', 'location', 'available_until'],
               decimals=('quantity_available', 'asking_price', 'min_order_quantity'))
        if lst.quantity_available < 0 or lst.asking_price < 0:
            raise Exception('Quantity and price cannot be negative')
        lst.save()
        return UpdateListing(listing=lst)


class VendorMutation(graphene.ObjectType):
    ensure_my_provider = EnsureMyProvider.Field()
    update_my_provider = UpdateMyProvider.Field()
    upsert_staff = UpsertStaff.Field()
    delete_staff = DeleteStaff.Field()
    upsert_service = UpsertService.Field()
    delete_service = DeleteService.Field()
    upsert_certification = UpsertCertification.Field()
    delete_certification = DeleteCertification.Field()
    upsert_equipment = UpsertEquipment.Field()
    delete_equipment = DeleteEquipment.Field()
    add_maintenance = AddMaintenance.Field()
    delete_maintenance = DeleteMaintenance.Field()
    create_provider_booking = CreateProviderBooking.Field()
    vendor_update_hire_booking = VendorUpdateHireBooking.Field()
    create_provider_appointment = CreateProviderAppointment.Field()
    vendor_update_vet_appointment = VendorUpdateVetAppointment.Field()
    upsert_work_order = UpsertWorkOrder.Field()
    delete_work_order = DeleteWorkOrder.Field()
    upsert_vendor_order = UpsertVendorOrder.Field()
    delete_vendor_order = DeleteVendorOrder.Field()
    upsert_batch = UpsertBatch.Field()
    delete_batch = DeleteBatch.Field()
    upsert_invoice = UpsertInvoice.Field()
    set_invoice_status = SetInvoiceStatus.Field()
    delete_invoice = DeleteInvoice.Field()
    update_listing = UpdateListing.Field()
