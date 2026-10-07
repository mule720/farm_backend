"""Sales — GraphQL for customers, orders and payments. Totals and order numbers are always computed here."""
import uuid
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

import graphene
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.financials.models import FarmTransaction
from .models import SaleCustomer, SaleOrder, SalePayment

MAX_LINES = 100
MAX_IMPORT = 2000
CENT = Decimal('0.01')


def _user(info):
    u = info.context.user
    if u.is_anonymous:
        raise Exception('Not authenticated')
    if not u.organization_id:
        raise Exception('Account has no organisation')
    return u


def _money(v, what='amount'):
    try:
        d = Decimal(str(round(float(v), 2)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{what} is not a number')
    return d


def _clean_lines(raw):
    """Validate order lines and return (lines, subtotal)."""
    if not raw or len(raw) > MAX_LINES:
        raise ValueError(f'An order needs between 1 and {MAX_LINES} lines')
    lines, subtotal = [], Decimal('0')
    for l in raw:
        desc = (l.get('description') or '').strip()
        if not desc:
            raise ValueError('Every line needs a description')
        qty = _money(l.get('qty'), 'quantity')
        price = _money(l.get('unitPrice'), 'price')
        if qty <= 0:
            raise ValueError(f'"{desc}": quantity must be greater than zero')
        if price < 0:
            raise ValueError(f'"{desc}": price cannot be negative')
        lines.append({'id': str(l.get('id') or uuid.uuid4()), 'description': desc[:255], 'qty': float(qty),
                      'unit': (l.get('unit') or '')[:30], 'unitPrice': float(price)})
        subtotal += qty * price
    return lines, subtotal.quantize(CENT)


def _totals(subtotal, tax_pct, discount):
    tax = Decimal('0') if tax_pct is None else _money(tax_pct, 'tax')
    if tax < 0 or tax > 100:
        raise ValueError('Tax must be between 0 and 100 %')
    disc = _money(discount or 0, 'discount')
    if disc < 0:
        raise ValueError('Discount cannot be negative')
    total = max(Decimal('0'), (subtotal * (1 + tax / 100) - disc)).quantize(CENT)
    return (tax or None), disc, total


def _next_number(org_id, when):
    prefix = f'ORD-{when:%Y%m}-'
    seq = 0
    for n in SaleOrder.objects.filter(organization_id=org_id, order_number__startswith=prefix).values_list('order_number', flat=True):
        try:
            seq = max(seq, int(n[len(prefix):]))
        except ValueError:
            pass
    return f'{prefix}{seq + 1:03d}'


def _get(model, u, pk, what):
    try:
        return model.objects.get(id=pk, organization_id=u.organization_id)
    except (model.DoesNotExist, ValueError, ValidationError):
        raise Exception(f'{what} not found')


# ─── Types ────────────────────────────────────────────────────────────────────

class SaleCustomerType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    type = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    address = graphene.String()
    notes = graphene.String()
    created_at = graphene.DateTime()

    def resolve_id(self, info): return str(self.id)
    def resolve_type(self, info): return self.customer_type


class SalePaymentType(graphene.ObjectType):
    id = graphene.String()
    amount = graphene.Float()
    paid_on = graphene.Date()
    note = graphene.String()
    recorded_by = graphene.String()

    def resolve_id(self, info): return str(self.id)
    def resolve_amount(self, info): return float(self.amount)
    def resolve_recorded_by(self, info): return self.recorded_by.full_name if self.recorded_by else None


class SaleOrderType(graphene.ObjectType):
    id = graphene.String()
    order_number = graphene.String()
    customer_id = graphene.String()
    customer_name = graphene.String()
    date = graphene.Date()
    due_date = graphene.Date()
    status = graphene.String()
    payment_status = graphene.String()
    lines = graphene.JSONString()
    subtotal = graphene.Float()
    tax_pct = graphene.Float()
    discount_amt = graphene.Float()
    total = graphene.Float()
    amount_paid = graphene.Float()
    cycle_ref = graphene.String()
    notes = graphene.String()
    fulfilled_at = graphene.DateTime()
    created_at = graphene.DateTime()
    payments = graphene.List(SalePaymentType)

    def resolve_id(self, info): return str(self.id)
    def resolve_customer_id(self, info): return str(self.customer_id) if self.customer_id else None
    def resolve_subtotal(self, info): return float(self.subtotal)
    def resolve_tax_pct(self, info): return float(self.tax_pct) if self.tax_pct is not None else None
    def resolve_discount_amt(self, info): return float(self.discount_amt)
    def resolve_total(self, info): return float(self.total)
    def resolve_amount_paid(self, info): return float(self.amount_paid)
    def resolve_payments(self, info): return list(self.payments.all())


# ─── Inputs ───────────────────────────────────────────────────────────────────

class SaleCustomerInput(graphene.InputObjectType):
    id = graphene.String()
    name = graphene.String(required=True)
    type = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    address = graphene.String()
    notes = graphene.String()


class SaleLineInput(graphene.InputObjectType):
    id = graphene.String()
    description = graphene.String(required=True)
    qty = graphene.Float(required=True)
    unit = graphene.String()
    unit_price = graphene.Float(required=True)


class SaleOrderInput(graphene.InputObjectType):
    customer_id = graphene.String(description='An existing customer…')
    new_customer_name = graphene.String(description='…or the name of a new one to add')
    date = graphene.Date(required=True)
    due_date = graphene.Date()
    lines = graphene.List(graphene.NonNull(SaleLineInput), required=True)
    tax_pct = graphene.Float()
    discount_amt = graphene.Float()
    cycle_ref = graphene.String()
    notes = graphene.String()


class LegacyCustomerInput(graphene.InputObjectType):
    legacy_id = graphene.String(required=True)
    name = graphene.String(required=True)
    type = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    address = graphene.String()
    notes = graphene.String()


class LegacyOrderInput(graphene.InputObjectType):
    legacy_id = graphene.String(required=True)
    order_number = graphene.String()
    legacy_customer_id = graphene.String()
    customer_name = graphene.String()
    date = graphene.Date(required=True)
    due_date = graphene.Date()
    status = graphene.String()
    lines = graphene.List(graphene.NonNull(SaleLineInput), required=True)
    tax_pct = graphene.Float()
    discount_amt = graphene.Float()
    amount_paid = graphene.Float()
    cycle_ref = graphene.String()
    notes = graphene.String()


# ─── Queries ──────────────────────────────────────────────────────────────────

class SalesQuery(graphene.ObjectType):
    sale_customers = graphene.List(SaleCustomerType)
    sale_orders = graphene.List(SaleOrderType, since=graphene.Date())

    def resolve_sale_customers(self, info):
        u = rbac.require_module(_user(info), 'sales', 'view')
        return list(SaleCustomer.objects.filter(organization_id=u.organization_id))

    def resolve_sale_orders(self, info, since=None):
        u = rbac.require_module(_user(info), 'sales', 'view')
        qs = SaleOrder.objects.filter(organization_id=u.organization_id).prefetch_related('payments__recorded_by')
        if since:
            qs = qs.filter(date__gte=since)
        return list(qs[:5000])


# ─── Mutations ────────────────────────────────────────────────────────────────

def _set_customer(c, name, ctype, phone, email, address, notes):
    name = (name or '').strip()
    if not name:
        raise Exception('Customer name is required')
    ctype = ctype or 'individual'
    if ctype not in SaleCustomer.TYPES:
        raise Exception('Unknown customer type')
    c.name, c.customer_type = name[:255], ctype
    c.phone, c.email, c.address, c.notes = (phone or '')[:40], (email or '')[:254], address or '', notes or ''


class SaveSaleCustomer(graphene.Mutation):
    class Arguments:
        input = SaleCustomerInput(required=True)

    customer = graphene.Field(SaleCustomerType)

    def mutate(self, info, input):
        u = _user(info)
        if input.get('id'):
            rbac.require_module(u, 'sales', 'edit')
            c = _get(SaleCustomer, u, input.id, 'Customer')
        else:
            rbac.require_module(u, 'sales', 'create')
            c = SaleCustomer(organization_id=u.organization_id, created_by=u)
        _set_customer(c, input.name, input.get('type'), input.get('phone'), input.get('email'), input.get('address'), input.get('notes'))
        c.save()
        if input.get('id'):  # keep the name on their orders in step
            SaleOrder.objects.filter(organization_id=u.organization_id, customer=c).update(customer_name=c.name)
        return SaveSaleCustomer(customer=c)


class DeleteSaleCustomer(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        u = rbac.require_module(_user(info), 'sales', 'delete')
        _get(SaleCustomer, u, id, 'Customer').delete()  # their orders stay, with the name kept on them
        return DeleteSaleCustomer(ok=True)


class CreateSaleOrder(graphene.Mutation):
    class Arguments:
        input = SaleOrderInput(required=True)

    order = graphene.Field(SaleOrderType)

    def mutate(self, info, input):
        u = rbac.require_module(_user(info), 'sales', 'create')
        try:
            lines, subtotal = _clean_lines([{'id': l.get('id'), 'description': l.description, 'qty': l.qty, 'unit': l.get('unit'), 'unitPrice': l.unit_price} for l in input.lines])
            tax, disc, total = _totals(subtotal, input.get('tax_pct') or None, input.get('discount_amt'))
        except ValueError as e:
            raise Exception(str(e))
        if input.get('due_date') and input.due_date < input.date:
            raise Exception('The due date is before the order date')
        with transaction.atomic():
            if input.get('customer_id'):
                cust = _get(SaleCustomer, u, input.customer_id, 'Customer')
            elif (input.get('new_customer_name') or '').strip():
                cust = SaleCustomer(organization_id=u.organization_id, created_by=u)
                _set_customer(cust, input.new_customer_name, 'individual', None, None, None, None)
                cust.save()
            else:
                raise Exception('Choose a customer or add a new one')
            for _ in range(5):
                try:
                    with transaction.atomic():
                        order = SaleOrder.objects.create(
                            organization_id=u.organization_id, order_number=_next_number(u.organization_id, input.date),
                            customer=cust, customer_name=cust.name, date=input.date, due_date=input.get('due_date'),
                            status='draft', lines=lines, subtotal=subtotal, tax_pct=tax, discount_amt=disc, total=total,
                            cycle_ref=(input.get('cycle_ref') or '')[:64], notes=input.get('notes') or '', created_by=u)
                    break
                except IntegrityError:  # two orders raced for the same number
                    continue
            else:
                raise Exception('Could not allocate an order number — please try again')
        return CreateSaleOrder(order=order)


def _post_to_ledger(order, user):
    """Income for a fulfilled order, posted once (the key is the order id)."""
    if order.total <= 0:
        return
    FarmTransaction.objects.get_or_create(
        organization_id=order.organization_id, source_ref=f'sale:{order.id}',
        defaults=dict(tx_type='income', category='sale_income', description=f'Sales order {order.order_number} — {order.customer_name}'[:255],
                      amount=order.total, date=timezone.localdate(), cycle_ref=order.cycle_ref, reference=order.order_number,
                      notes='Auto-recorded from sales', source='sales', created_by=user))


class UpdateSaleOrder(graphene.Mutation):
    """Move an order along its flow (draft → confirmed → fulfilled, or cancel) and/or change its notes."""
    class Arguments:
        id = graphene.String(required=True)
        status = graphene.String()
        notes = graphene.String()

    order = graphene.Field(SaleOrderType)

    def mutate(self, info, id, status=None, notes=None):
        u = rbac.require_module(_user(info), 'sales', 'edit')
        with transaction.atomic():
            try:
                order = SaleOrder.objects.select_for_update().get(id=id, organization_id=u.organization_id)
            except (SaleOrder.DoesNotExist, ValueError, ValidationError):
                raise Exception('Order not found')
            if status is not None and status != order.status:
                if status not in SaleOrder.FLOW.get(order.status, set()):
                    raise Exception(f'A {order.status} order cannot become {status}')
                order.status = status
                if status == 'fulfilled':
                    order.fulfilled_at = timezone.now()
            if notes is not None:
                order.notes = notes
            order.save()
            if order.status == 'fulfilled':
                _post_to_ledger(order, u)
        return UpdateSaleOrder(order=order)


class RecordSalePayment(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)
        amount = graphene.Float(required=True)
        paid_on = graphene.Date()
        note = graphene.String()

    order = graphene.Field(SaleOrderType)

    def mutate(self, info, order_id, amount, paid_on=None, note=None):
        u = rbac.require_module(_user(info), 'sales', 'edit')
        try:
            amt = _money(amount)
        except ValueError as e:
            raise Exception(str(e))
        if amt <= 0:
            raise Exception('The payment must be greater than zero')
        with transaction.atomic():
            try:
                order = SaleOrder.objects.select_for_update().get(id=order_id, organization_id=u.organization_id)
            except (SaleOrder.DoesNotExist, ValueError, ValidationError):
                raise Exception('Order not found')
            if order.status == 'cancelled':
                raise Exception('A cancelled order cannot receive payments')
            outstanding = order.total - order.amount_paid
            if amt > outstanding:
                raise Exception(f'That is more than the balance due ({outstanding})')
            SalePayment.objects.create(order=order, amount=amt, paid_on=paid_on or timezone.localdate(), note=(note or '')[:255], recorded_by=u)
            order.amount_paid = order.amount_paid + amt
            order.save(update_fields=['amount_paid', 'updated_at'])
        return RecordSalePayment(order=order)


class ImportSalesData(graphene.Mutation):
    """
    Bring an old browser-only customer and order list across. Safe to repeat:
    anything already imported (same legacy id) is skipped. Imported orders do
    not post to the ledger — the old flow already recorded fulfilled ones.
    """
    class Arguments:
        customers = graphene.List(graphene.NonNull(LegacyCustomerInput), required=True)
        orders = graphene.List(graphene.NonNull(LegacyOrderInput), required=True)

    customers_created = graphene.Int()
    orders_created = graphene.Int()
    skipped = graphene.Int()
    rejected = graphene.Int()

    def mutate(self, info, customers, orders):
        u = rbac.require_module(_user(info), 'sales', 'create')
        if len(customers) + len(orders) > MAX_IMPORT:
            raise Exception(f'Too many records in one request (max {MAX_IMPORT})')
        org = u.organization_id
        cust_by_legacy = {c.legacy_id: c for c in SaleCustomer.objects.filter(organization_id=org).exclude(legacy_id='')}
        c_new = o_new = skipped = rejected = 0
        for ci in customers:
            if ci.legacy_id in cust_by_legacy:
                skipped += 1
                continue
            try:
                c = SaleCustomer(organization_id=org, legacy_id=ci.legacy_id[:64], created_by=u)
                _set_customer(c, ci.name, ci.get('type') if ci.get('type') in SaleCustomer.TYPES else 'individual',
                              ci.get('phone'), ci.get('email'), ci.get('address'), ci.get('notes'))
                c.save()
            except Exception:
                rejected += 1
                continue
            cust_by_legacy[ci.legacy_id] = c
            c_new += 1
        have = set(SaleOrder.objects.filter(organization_id=org).exclude(legacy_id='').values_list('legacy_id', flat=True))
        for oi in orders:
            if oi.legacy_id in have:
                skipped += 1
                continue
            try:
                lines, subtotal = _clean_lines([{'id': l.get('id'), 'description': l.description, 'qty': l.qty, 'unit': l.get('unit'), 'unitPrice': l.unit_price} for l in oi.lines])
                tax, disc, total = _totals(subtotal, oi.get('tax_pct') or None, oi.get('discount_amt'))
                status = oi.get('status') if oi.get('status') in SaleOrder.STATUSES else 'draft'
                number = (oi.get('order_number') or '').strip()[:40] or _next_number(org, oi.date)
                if SaleOrder.objects.filter(organization_id=org, order_number=number).exists():
                    number = _next_number(org, oi.date)
                cust = cust_by_legacy.get(oi.get('legacy_customer_id') or '')
                paid = min(max(_money(oi.get('amount_paid') or 0), Decimal('0')), total)
                with transaction.atomic():
                    order = SaleOrder.objects.create(
                        organization_id=org, order_number=number, customer=cust,
                        customer_name=(cust.name if cust else (oi.get('customer_name') or 'Customer'))[:255],
                        date=oi.date, due_date=oi.get('due_date'), status=status, lines=lines, subtotal=subtotal, tax_pct=tax,
                        discount_amt=disc, total=total, amount_paid=paid, cycle_ref=(oi.get('cycle_ref') or '')[:64],
                        notes=oi.get('notes') or '', legacy_id=oi.legacy_id[:64], created_by=u,
                        fulfilled_at=timezone.now() if status == 'fulfilled' else None)
                    if paid > 0:
                        SalePayment.objects.create(order=order, amount=paid, paid_on=oi.date, note='Imported from browser records', recorded_by=u)
            except Exception:
                rejected += 1
                continue
            have.add(oi.legacy_id)
            o_new += 1
        return ImportSalesData(customers_created=c_new, orders_created=o_new, skipped=skipped, rejected=rejected)


class SalesMutation(graphene.ObjectType):
    save_sale_customer = SaveSaleCustomer.Field()
    delete_sale_customer = DeleteSaleCustomer.Field()
    create_sale_order = CreateSaleOrder.Field()
    update_sale_order = UpdateSaleOrder.Field()
    record_sale_payment = RecordSalePayment.Field()
    import_sales_data = ImportSalesData.Field()
