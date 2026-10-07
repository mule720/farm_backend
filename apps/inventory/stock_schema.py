"""Stock — GraphQL for the farm shell's Inventory page and for automatic postings from production, sales and processing."""
from datetime import date as date_cls
from decimal import Decimal

import graphene
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts import rbac
from .models import InventoryItem, InventoryTransaction
from .service import CATEGORIES, KINDS, TYPE_TO_KIND, StockError, apply_movement, dec, post_stock_in, post_stock_out

MAX_IMPORT = 3000
AUTO_SOURCES = ('production', 'sales', 'processing')
SOURCE_MODULES = {
    'production': ['production', 'poultry', 'village-chicken', 'piggery', 'fish', 'duck', 'goat-sheep', 'horticulture'],
    'processing': ['production'],
    'sales': ['sales'],
}


def _user(info):
    u = info.context.user
    if u.is_anonymous:
        raise Exception('Not authenticated')
    if not u.organization_id:
        raise Exception('Account has no organisation')
    return u


def _can_post(user, source):
    if rbac.can(user, 'inventory', 'create'):
        return True
    return any(rbac.can(user, m, 'create') or rbac.can(user, m, 'edit') for m in SOURCE_MODULES.get(source, []))


def _get_item(u, item_id):
    try:
        return InventoryItem.objects.get(id=item_id, organization_id=u.organization_id)
    except (InventoryItem.DoesNotExist, ValueError, ValidationError):
        raise Exception('Item not found')


# ─── Types ────────────────────────────────────────────────────────────────────

class StockItemType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    sku = graphene.String()
    category = graphene.String()
    unit = graphene.String()
    current_qty = graphene.Float()
    min_stock_level = graphene.Float()
    cost_per_unit = graphene.Float()
    location = graphene.String()
    supplier = graphene.String()
    expiry_date = graphene.Date()
    notes = graphene.String()
    created_at = graphene.DateTime()

    def resolve_id(self, info): return str(self.id)
    def resolve_current_qty(self, info): return float(self.current_stock)
    def resolve_min_stock_level(self, info): return float(self.reorder_level)
    def resolve_cost_per_unit(self, info): return float(self.unit_cost) if self.unit_cost is not None else None


class StockMovementType(graphene.ObjectType):
    id = graphene.String()
    item_id = graphene.String()
    type = graphene.String()
    qty = graphene.Float()
    date = graphene.Date()
    reference = graphene.String()
    destination = graphene.String()
    unit_cost = graphene.Float()
    notes = graphene.String()
    source = graphene.String()
    recorded_by = graphene.String()
    created_at = graphene.DateTime()

    def resolve_id(self, info): return str(self.id)
    def resolve_item_id(self, info): return str(self.item_id)
    def resolve_type(self, info): return TYPE_TO_KIND.get(self.transaction_type, 'adjustment')
    def resolve_qty(self, info): return float(abs(self.quantity)) if self.transaction_type != 'adjustment' else float(self.quantity)
    def resolve_date(self, info): return self.movement_date or self.recorded_at.date()
    def resolve_unit_cost(self, info): return float(self.unit_cost) if self.unit_cost is not None else None
    def resolve_recorded_by(self, info): return self.recorded_by.full_name if self.recorded_by else None
    def resolve_created_at(self, info): return self.recorded_at


# ─── Inputs ───────────────────────────────────────────────────────────────────

class StockItemInput(graphene.InputObjectType):
    id = graphene.String(description='Set to update an existing item')
    name = graphene.String(required=True)
    sku = graphene.String()
    category = graphene.String()
    unit = graphene.String()
    opening_qty = graphene.Float(description='Stock on hand when the item is first created')
    min_stock_level = graphene.Float()
    cost_per_unit = graphene.Float()
    location = graphene.String()
    supplier = graphene.String()
    expiry_date = graphene.Date()
    notes = graphene.String()


class AutoStockInput(graphene.InputObjectType):
    source_ref = graphene.String(required=True, description='Stable key — the same key is never posted twice')
    direction = graphene.String(required=True, description='in | out')
    name = graphene.String(required=True)
    qty = graphene.Float(required=True)
    unit = graphene.String()
    date = graphene.Date(required=True)
    cost_per_unit = graphene.Float()
    reference = graphene.String()
    destination = graphene.String()
    notes = graphene.String()


class LegacyItemInput(graphene.InputObjectType):
    legacy_id = graphene.String(required=True)
    name = graphene.String(required=True)
    sku = graphene.String()
    category = graphene.String()
    unit = graphene.String()
    current_qty = graphene.Float()
    min_stock_level = graphene.Float()
    cost_per_unit = graphene.Float()
    location = graphene.String()
    supplier = graphene.String()
    expiry_date = graphene.Date()
    notes = graphene.String()


class LegacyMovementInput(graphene.InputObjectType):
    legacy_id = graphene.String(required=True)
    legacy_item_id = graphene.String(required=True)
    type = graphene.String(required=True)
    qty = graphene.Float(required=True)
    date = graphene.Date()
    reference = graphene.String()
    destination = graphene.String()
    unit_cost = graphene.Float()
    notes = graphene.String()


# ─── Queries ──────────────────────────────────────────────────────────────────

class StockQuery(graphene.ObjectType):
    stock_items = graphene.List(StockItemType)
    stock_movements = graphene.List(StockMovementType, item_id=graphene.String(required=True), limit=graphene.Int())

    def resolve_stock_items(self, info):
        u = rbac.require_module(_user(info), 'inventory', 'view')
        return list(InventoryItem.objects.filter(organization_id=u.organization_id))

    def resolve_stock_movements(self, info, item_id, limit=50):
        u = rbac.require_module(_user(info), 'inventory', 'view')
        item = _get_item(u, item_id)
        qs = InventoryTransaction.objects.filter(organization_id=u.organization_id, item=item).select_related('recorded_by')
        return list(qs.order_by('-recorded_at')[:max(1, min(limit or 50, 500))])


# ─── Mutations ────────────────────────────────────────────────────────────────

def _fill_item(item, input, creating):
    name = (input.name or '').strip()
    if not name:
        raise Exception('The item needs a name')
    category = input.get('category') or 'other'
    if category not in CATEGORIES:
        raise Exception('Unknown category')
    unit = (input.get('unit') or 'kg').strip()
    try:
        reorder = dec(input.get('min_stock_level') or 0, 'minimum stock')
        cost = Decimal(str(round(float(input.cost_per_unit), 2))) if input.get('cost_per_unit') else None
    except ValueError as e:
        raise Exception(str(e))
    if reorder < 0 or (cost is not None and cost < 0):
        raise Exception('Minimum stock and cost cannot be negative')
    item.name, item.category, item.unit = name[:255], category, unit[:50]
    item.sku = (input.get('sku') or '')[:100]
    item.reorder_level, item.unit_cost = reorder, cost
    item.location, item.supplier, item.notes = (input.get('location') or '')[:255], (input.get('supplier') or '')[:255], input.get('notes') or ''
    item.expiry_date = input.get('expiry_date')
    return item


class SaveStockItem(graphene.Mutation):
    """Create or edit an item's details. Stock quantity changes only through movements."""
    class Arguments:
        input = StockItemInput(required=True)

    item = graphene.Field(StockItemType)

    def mutate(self, info, input):
        u = _user(info)
        if input.get('id'):
            rbac.require_module(u, 'inventory', 'edit')
            item = _fill_item(_get_item(u, input.id), input, False)
            item.save()
        else:
            rbac.require_module(u, 'inventory', 'create')
            item = _fill_item(InventoryItem(organization_id=u.organization_id, created_by=u), input, True)
            opening = dec(input.get('opening_qty') or 0, 'opening stock')
            if opening < 0:
                raise Exception('Opening stock cannot be negative')
            with transaction.atomic():
                item.current_stock = Decimal('0')
                item.save()
                if opening > 0:   # opening stock is a movement like any other, so it shows in the history
                    apply_movement(u.organization_id, item.id, 'in', opening, user=u, when=date_cls.today(), notes='Opening stock',
                                   unit_cost=item.unit_cost)
            item.refresh_from_db()
        return SaveStockItem(item=item)


class DeleteStockItem(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        u = rbac.require_module(_user(info), 'inventory', 'delete')
        _get_item(u, id).delete()      # its movement history goes with it
        return DeleteStockItem(ok=True)


class RecordStockMovement(graphene.Mutation):
    class Arguments:
        item_id = graphene.String(required=True)
        type = graphene.String(required=True, description='in | out | adjustment | transfer')
        qty = graphene.Float(required=True)
        date = graphene.Date()
        reference = graphene.String()
        destination = graphene.String()
        unit_cost = graphene.Float()
        notes = graphene.String()

    item = graphene.Field(StockItemType)
    movement = graphene.Field(StockMovementType)

    def mutate(self, info, item_id, type, qty, date=None, reference=None, destination=None, unit_cost=None, notes=None):
        u = rbac.require_module(_user(info), 'inventory', 'create' if type == 'in' else 'edit')
        if type == 'transfer' and not (destination or '').strip():
            raise Exception('Say where the stock is going')
        try:
            tx = apply_movement(u.organization_id, item_id, type, qty, user=u, when=date, reference=reference or '',
                                destination=destination or '', unit_cost=unit_cost, notes=notes or '')
        except (StockError, ValueError) as e:
            raise Exception(str(e))
        tx.item.refresh_from_db()
        return RecordStockMovement(item=tx.item, movement=tx)


class PostStock(graphene.Mutation):
    """
    Automatic postings from production (harvest, purchases, eggs, milk), sales (fulfilled orders) and
    processing batches. Idempotent: a key already posted is skipped. Unknown items on the way out are
    ignored; goods coming in create their item.
    """
    class Arguments:
        source = graphene.String(required=True, description='production | sales | processing')
        items = graphene.List(graphene.NonNull(AutoStockInput), required=True)

    created = graphene.Int()
    duplicates = graphene.Int()
    unmatched = graphene.Int()
    rejected = graphene.Int()

    def mutate(self, info, source, items):
        u = _user(info)
        if source not in AUTO_SOURCES:
            raise Exception('Unknown source')
        if not _can_post(u, source):
            raise Exception('Permission denied: you cannot post stock movements')
        if len(items) > MAX_IMPORT:
            raise Exception(f'Too many entries in one request (max {MAX_IMPORT})')
        out = {'created': 0, 'duplicate': 0, 'unmatched': 0, 'empty': 0}
        rejected = 0
        for i in items:
            key = (i.source_ref or '').strip()[:120]
            try:
                if not key or not (i.name or '').strip() or i.direction not in ('in', 'out') or dec(i.qty) <= 0:
                    raise ValueError
                if i.direction == 'in':
                    r = post_stock_in(u.organization_id, name=i.name, qty=i.qty, unit=i.get('unit'), when=i.date, cost_per_unit=i.get('cost_per_unit'),
                                      reference=i.get('reference') or '', notes=i.get('notes') or '', user=u, source=source, source_ref=key)
                else:
                    r = post_stock_out(u.organization_id, name=i.name, qty=i.qty, when=i.date, reference=i.get('reference') or '',
                                       destination=i.get('destination') or '', notes=i.get('notes') or '', user=u, source=source, source_ref=key)
            except (ValueError, StockError):
                rejected += 1
                continue
            out[r] = out.get(r, 0) + 1
        return PostStock(created=out['created'], duplicates=out['duplicate'], unmatched=out['unmatched'] + out['empty'], rejected=rejected)


class ImportStockData(graphene.Mutation):
    """
    Bring an old browser-only item list and movement history across. Safe to repeat. Stock levels are taken
    exactly as they were; the imported movements are history only and do not change them.
    """
    class Arguments:
        items = graphene.List(graphene.NonNull(LegacyItemInput), required=True)
        movements = graphene.List(graphene.NonNull(LegacyMovementInput), required=True)

    items_created = graphene.Int()
    movements_created = graphene.Int()
    skipped = graphene.Int()
    rejected = graphene.Int()

    def mutate(self, info, items, movements):
        u = rbac.require_module(_user(info), 'inventory', 'create')
        if len(items) + len(movements) > MAX_IMPORT:
            raise Exception(f'Too many records in one request (max {MAX_IMPORT})')
        org = u.organization_id
        by_legacy = {i.legacy_id: i for i in InventoryItem.objects.filter(organization_id=org).exclude(legacy_id='')}
        i_new = m_new = skipped = rejected = 0
        for it in items:
            if it.legacy_id in by_legacy:
                skipped += 1
                continue
            try:
                cat = it.get('category') if it.get('category') in CATEGORIES else 'other'
                item = InventoryItem.objects.create(
                    organization_id=org, created_by=u, legacy_id=it.legacy_id[:64], name=(it.name or '').strip()[:255] or 'Item',
                    sku=(it.get('sku') or '')[:100], category=cat, unit=(it.get('unit') or 'kg')[:50],
                    current_stock=max(dec(it.get('current_qty') or 0), Decimal('0')), reorder_level=max(dec(it.get('min_stock_level') or 0), Decimal('0')),
                    unit_cost=Decimal(str(round(float(it.cost_per_unit), 2))) if it.get('cost_per_unit') else None,
                    location=(it.get('location') or '')[:255], supplier=(it.get('supplier') or '')[:255],
                    expiry_date=it.get('expiry_date'), notes=it.get('notes') or '')
            except Exception:
                rejected += 1
                continue
            by_legacy[it.legacy_id] = item
            i_new += 1
        have = set(InventoryTransaction.objects.filter(organization_id=org, source='import').values_list('source_ref', flat=True))
        batch = []
        for mv in movements:
            key = f'local:{mv.legacy_id}'[:120]
            item = by_legacy.get(mv.legacy_item_id)
            if key in have:
                skipped += 1
                continue
            if item is None or mv.type not in KINDS:
                rejected += 1
                continue
            try:
                q = dec(mv.qty)
                if q == 0:
                    raise ValueError
                batch.append(InventoryTransaction(
                    organization_id=org, item=item, transaction_type={'in': 'purchase', 'out': 'usage', 'adjustment': 'adjustment', 'transfer': 'transfer'}[mv.type],
                    quantity=q, unit_cost=Decimal(str(round(float(mv.unit_cost), 2))) if mv.get('unit_cost') else None,
                    reference=(mv.get('reference') or '')[:255], notes=mv.get('notes') or '', destination=(mv.get('destination') or '')[:255],
                    movement_date=mv.get('date'), source='import', source_ref=key, recorded_by=u))
            except ValueError:
                rejected += 1
                continue
            have.add(key)
            m_new += 1
        # bulk_create skips save(), so stock levels are left exactly as imported
        InventoryTransaction.objects.bulk_create(batch)
        return ImportStockData(items_created=i_new, movements_created=m_new, skipped=skipped, rejected=rejected)


class StockMutation(graphene.ObjectType):
    save_stock_item = SaveStockItem.Field()
    delete_stock_item = DeleteStockItem.Field()
    record_stock_movement = RecordStockMovement.Field()
    post_stock = PostStock.Field()
    import_stock_data = ImportStockData.Field()
