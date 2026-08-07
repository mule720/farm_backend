import graphene
from graphene_django import DjangoObjectType
from .models import InventoryItem, InventoryTransaction


class InventoryItemType(DjangoObjectType):
    is_low_stock = graphene.Boolean()
    stock_value = graphene.Float()

    class Meta:
        model = InventoryItem
        fields = ['id', 'name', 'category', 'sku', 'unit', 'current_stock',
                  'reorder_level', 'unit_cost', 'supplier', 'notes',
                  'enterprise', 'created_at', 'updated_at']

    def resolve_is_low_stock(self, info):
        return self.is_low_stock

    def resolve_stock_value(self, info):
        v = self.stock_value
        return float(v) if v is not None else None


class InventoryTransactionType(DjangoObjectType):
    class Meta:
        model = InventoryTransaction
        fields = ['id', 'item', 'batch', 'transaction_type', 'quantity',
                  'unit_cost', 'total_cost', 'reference', 'notes',
                  'recorded_by', 'recorded_at']
        convert_choices_to_enum = False


class InventorySummaryType(graphene.ObjectType):
    total_items = graphene.Int()
    low_stock_count = graphene.Int()
    total_value = graphene.Float()
    categories = graphene.List(graphene.String)


# ─── Inputs ──────────────────────────────────────────────────────────────────

class InventoryItemInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    category = graphene.String()
    sku = graphene.String()
    unit = graphene.String()
    current_stock = graphene.Float()
    reorder_level = graphene.Float()
    unit_cost = graphene.Float()
    supplier = graphene.String()
    notes = graphene.String()
    enterprise_id = graphene.ID()


class TransactionInput(graphene.InputObjectType):
    item_id = graphene.ID(required=True)
    transaction_type = graphene.String(required=True)
    quantity = graphene.Float(required=True)
    batch_id = graphene.ID()
    unit_cost = graphene.Float()
    reference = graphene.String()
    notes = graphene.String()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class InventoryQuery(graphene.ObjectType):
    inventory_items = graphene.List(
        InventoryItemType,
        category=graphene.String(),
        enterprise_id=graphene.ID(),
        low_stock_only=graphene.Boolean(),
    )
    inventory_item = graphene.Field(InventoryItemType, id=graphene.ID(required=True))
    inventory_transactions = graphene.List(
        InventoryTransactionType,
        item_id=graphene.ID(),
        batch_id=graphene.ID(),
        transaction_type=graphene.String(),
        limit=graphene.Int(),
    )
    inventory_summary = graphene.Field(InventorySummaryType)

    def resolve_inventory_items(self, info, category=None, enterprise_id=None,
                                low_stock_only=None):
        org = _org(info)
        qs = InventoryItem.objects.filter(organization=org)
        if category:
            qs = qs.filter(category=category)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if low_stock_only:
            from django.db.models import F
            qs = qs.filter(current_stock__lte=F('reorder_level'))
        return qs

    def resolve_inventory_item(self, info, id):
        org = _org(info)
        return InventoryItem.objects.get(id=id, organization=org)

    def resolve_inventory_transactions(self, info, item_id=None, batch_id=None,
                                        transaction_type=None, limit=50):
        org = _org(info)
        qs = InventoryTransaction.objects.filter(organization=org)
        if item_id:
            qs = qs.filter(item_id=item_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if transaction_type:
            qs = qs.filter(transaction_type=transaction_type)
        return qs[:limit]

    def resolve_inventory_summary(self, info):
        from django.db.models import F, Sum
        org = _org(info)
        items = InventoryItem.objects.filter(organization=org)
        total = items.count()
        low = items.filter(current_stock__lte=F('reorder_level')).count()
        value = sum(
            (float(i.unit_cost or 0) * float(i.current_stock))
            for i in items if i.unit_cost
        )
        cats = list(items.values_list('category', flat=True).distinct())
        return InventorySummaryType(
            total_items=total, low_stock_count=low,
            total_value=value, categories=cats,
        )


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateInventoryItem(graphene.Mutation):
    class Arguments:
        input = InventoryItemInput(required=True)

    item = graphene.Field(InventoryItemType)

    def mutate(self, info, input):
        from decimal import Decimal
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        raw_cost = input.get('unit_cost')
        item = InventoryItem.objects.create(
            organization=user.organization,
            created_by=user,
            name=input.name,
            category=input.get('category', 'feed'),
            sku=input.get('sku', ''),
            unit=input.get('unit', 'kg'),
            current_stock=Decimal(str(input.get('current_stock') or 0)),
            reorder_level=Decimal(str(input.get('reorder_level') or 0)),
            unit_cost=Decimal(str(raw_cost)) if raw_cost is not None else None,
            supplier=input.get('supplier', ''),
            notes=input.get('notes', ''),
            enterprise_id=input.get('enterprise_id'),
        )
        return CreateInventoryItem(item=item)


class UpdateInventoryItem(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = InventoryItemInput(required=True)

    item = graphene.Field(InventoryItemType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        item = InventoryItem.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None and k != 'enterprise_id':
                setattr(item, k, v)
        item.save()
        return UpdateInventoryItem(item=item)


class DeleteInventoryItem(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'saas_admin'):
            raise Exception('Permission denied')
        InventoryItem.objects.get(id=id, organization=user.organization).delete()
        return DeleteInventoryItem(success=True)


class RecordTransaction(graphene.Mutation):
    class Arguments:
        input = TransactionInput(required=True)

    transaction = graphene.Field(InventoryTransactionType)

    def mutate(self, info, input):
        from decimal import Decimal
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        item = InventoryItem.objects.get(id=input.item_id, organization=user.organization)
        # Accept shorthand 'in'/'out' from the frontend, map to model choices
        tx_type_map = {'in': 'purchase', 'out': 'usage'}
        tx_type = tx_type_map.get(input.transaction_type, input.transaction_type)
        raw_cost = input.get('unit_cost')
        override_cost = Decimal(str(raw_cost)) if raw_cost is not None else None
        tx = InventoryTransaction(
            organization=user.organization,
            item=item,
            transaction_type=tx_type,
            quantity=Decimal(str(input.quantity)),
            batch_id=input.get('batch_id'),
            unit_cost=override_cost or item.unit_cost,
            reference=input.get('reference', ''),
            notes=input.get('notes', ''),
            recorded_by=user,
        )
        tx.save()  # stock update happens in save()
        return RecordTransaction(transaction=tx)


class InventoryMutation(graphene.ObjectType):
    create_inventory_item = CreateInventoryItem.Field()
    update_inventory_item = UpdateInventoryItem.Field()
    delete_inventory_item = DeleteInventoryItem.Field()
    record_transaction = RecordTransaction.Field()
