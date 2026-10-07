"""
Stock movements — the one place that changes how much of something is in stock.

A person recording a movement is told if it cannot be done (taking out more than
is there). An automatic posting (a sale being fulfilled, a harvest sent to
stock) never fails the business event that caused it: it takes what is
available, records what actually moved, and notes any shortfall.
"""
import re
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import InventoryItem, InventoryTransaction

KINDS = ('in', 'out', 'adjustment', 'transfer')
# what the farm shell calls a movement → what the transaction table calls it
KIND_TO_TYPE = {'in': 'purchase', 'out': 'usage', 'adjustment': 'adjustment', 'transfer': 'transfer'}
TYPE_TO_KIND = {v: k for k, v in KIND_TO_TYPE.items()}
TYPE_TO_KIND.update({'disposal': 'out'})
CATEGORIES = tuple(c for c, _ in InventoryItem.CATEGORY_CHOICES)
QTY = Decimal('0.001')


def slug(text):
    """'Broilers (live)' → 'broilers-live' — used to match a name from another module to a stock item."""
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')


def infer_category(name):
    n = (name or '').lower()
    for pattern, cat in (
        (r'feed|bran|meal|hay|silage|fodder', 'feed'),
        (r'seed|grain|maize|wheat|soy|rice', 'seed'),
        (r'vaccine|antibiotic|drug|medicine|deworm', 'medicine'),
        (r'fertiliser|fertilizer|urea|npk|dap', 'fertiliser'),
        (r'pesticide|herbicide|fungicide|chemical', 'chemical'),
        (r'bag|box|crate|tray|sachet|packaging', 'packaging'),
        (r'milk|egg|honey|wax|meat|fish|carcass', 'produce'),
        (r'flour|oil|processed', 'processed'),
        (r'pump|pipe|equipment|tool|net', 'equipment'),
    ):
        if re.search(pattern, n):
            return cat
    return 'produce'   # harvest outputs default to produce


def dec(value, what='quantity'):
    try:
        return Decimal(str(round(float(value), 3)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{what} is not a number')


def find_item(org_id, name=None, sku=None):
    """The org's item whose name (or code) matches, ignoring case, spaces and punctuation. Oldest wins."""
    want = slug(name or sku)
    if not want:
        return None
    for item in InventoryItem.objects.filter(organization_id=org_id).order_by('created_at'):
        if slug(item.name) == want or (item.sku and slug(item.sku) == want):
            return item
    return None


class StockError(Exception):
    """A movement that cannot be done, with a message fit to show the person who asked."""


def apply_movement(org_id, item_id, kind, qty, *, user=None, when=None, reference='', destination='',
                   unit_cost=None, notes='', source='manual', source_ref='', allow_short=False):
    """
    Move stock. Returns the InventoryTransaction, or None when an automatic posting had nothing to take.
    Raises StockError for a person asking for something impossible.
    """
    if kind not in KINDS:
        raise StockError('Unknown movement type')
    qty = dec(qty)
    if kind == 'adjustment':
        if qty == 0:
            raise StockError('An adjustment cannot be zero')
    elif qty <= 0:
        raise StockError('The quantity must be greater than zero')
    with transaction.atomic():
        try:
            item = InventoryItem.objects.select_for_update().get(pk=item_id, organization_id=org_id)
        except (InventoryItem.DoesNotExist, ValueError, ValidationError):
            raise StockError('Item not found')
        stock = item.current_stock
        removing = kind in ('out', 'transfer') or (kind == 'adjustment' and qty < 0)
        want = abs(qty)
        if removing and want > stock:
            if not allow_short:
                raise StockError(f'Only {stock.normalize():f} {item.unit} in stock')
            if stock <= 0:
                return None
            notes = (notes + ' ' if notes else '') + f'(short by {(want - stock).normalize():f} {item.unit})'
            want = stock
            qty = -want if kind == 'adjustment' else want
        tx = InventoryTransaction(
            organization_id=org_id, item=item, transaction_type=KIND_TO_TYPE[kind], quantity=qty,
            unit_cost=Decimal(str(unit_cost)) if unit_cost not in (None, '') else None,
            reference=(reference or '')[:255], notes=notes or '', destination=(destination or '')[:255],
            movement_date=when if isinstance(when, date_cls) else None, source=source, source_ref=(source_ref or '')[:120],
            recorded_by=user)
        try:
            tx.save()          # also moves current_stock, in the same transaction
        except IntegrityError:  # the same automatic posting arrived twice
            return None
        return tx


def post_stock_in(org_id, *, name, qty, unit, when, cost_per_unit=None, reference='', notes='', user=None, source, source_ref):
    """Goods arriving from production or processing. Finds the item by name, or creates it."""
    if InventoryTransaction.objects.filter(organization_id=org_id, source_ref=source_ref).exists():
        return 'duplicate'
    with transaction.atomic():
        item = find_item(org_id, name=name)
        if item is None:
            item = InventoryItem.objects.create(
                organization_id=org_id, created_by=user, name=name.strip()[:255], sku=slug(name)[:100],
                category=infer_category(name), unit=(unit or 'kg')[:50], current_stock=Decimal('0'), reorder_level=Decimal('0'),
                unit_cost=Decimal(str(cost_per_unit)) if cost_per_unit else None, notes=f'Created automatically from {source}')
        tx = apply_movement(org_id, item.id, 'in', qty, user=user, when=when, reference=reference, unit_cost=cost_per_unit,
                            notes=notes, source=source, source_ref=source_ref)
    return 'created' if tx else 'duplicate'


def post_stock_out(org_id, *, name, qty, when, reference='', destination='', notes='', user=None, source, source_ref):
    """Goods leaving for a sale or into processing. Takes what is there; nothing happens if the item is unknown."""
    if InventoryTransaction.objects.filter(organization_id=org_id, source_ref=source_ref).exists():
        return 'duplicate'
    item = find_item(org_id, name=name)
    if item is None:
        return 'unmatched'
    tx = apply_movement(org_id, item.id, 'out', qty, user=user, when=when, reference=reference, destination=destination,
                        notes=notes, source=source, source_ref=source_ref, allow_short=True)
    return 'created' if tx else 'empty'


def release_stock_for_order(order, user):
    """When an order is fulfilled, take its lines out of stock (once per line, whoever triggers it)."""
    from django.utils import timezone
    for line in order.lines or []:
        try:
            post_stock_out(order.organization_id, name=line.get('description'), qty=line.get('qty'), when=timezone.localdate(),
                           reference=order.order_number, destination=order.customer_name,
                           notes=f'Sale order {order.order_number} to {order.customer_name}', user=user,
                           source='sales', source_ref=f"sale:{order.id}:{line.get('id')}")
        except (StockError, ValueError):
            continue   # a bad line must never block fulfilling the order
